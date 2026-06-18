"""History tab: month-on-month goals and final status."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from month_history import finalize_due_months, load_history_records
from session_auth import current_user_id
from styles import card_container


def _pace_pill(tone: str, label: str) -> str:
    return f'<span class="ikr-pill ikr-pill-{tone}">{label}</span>'


def _render_trend_chart(records: list[dict]) -> None:
    if len(records) < 2:
        return
    rows = sorted(records, key=lambda r: r["month_key"])
    df = pd.DataFrame(
        {
            "month": [r["label"] for r in rows],
            "month_key": [r["month_key"] for r in rows],
            "score": [r["overall_pct"] for r in rows],
        }
    )
    chart = (
        alt.Chart(df)
        .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
        .encode(
            x=alt.X(
                "month:N",
                sort=alt.EncodingSortField(field="month_key", order="ascending"),
                title=None,
                axis=alt.Axis(labelAngle=-35),
            ),
            y=alt.Y("score:Q", title="Overall score %", scale=alt.Scale(domain=[0, 100])),
            color=alt.condition(
                "datum.score >= 100",
                alt.value("#16a34a"),
                alt.value("#4f46e5"),
            ),
            tooltip=["month:N", alt.Tooltip("score:Q", format=".1f", title="Score %")],
        )
        .properties(height=240)
    )
    st.altair_chart(chart, use_container_width=True)


def _render_overview_table(records: list[dict]) -> None:
    rows = []
    for r in records:
        finalized = " · locked" if r.get("is_finalized") else ""
        rows.append(
            {
                "Month": r["label"] + (" · current" if r["is_current"] else "") + finalized,
                "Goals": r["goal_count"],
                "Completed": f"{r['goals_completed']}/{r['goal_count']}",
                "Overall %": f"{r['overall_pct']:.0f}%",
                "Weighted": f"{r['earned']:.1f}/{r['total_weight']:.1f}",
                "Status": r["overall_status"],
            }
        )
    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
    )


def _render_month_detail(record: dict) -> None:
    tone = record["overall_tone"]
    as_of = record.get("score_as_of_date", "")
    as_of_note = f" · scored as of {as_of}" if as_of else ""
    finalized_note = " · **finalized**" if record.get("is_finalized") else " · live"
    st.markdown(
        f'{_pace_pill(tone, record["overall_status"])} '
        f'Overall **{record["overall_pct"]:.0f}%** '
        f'({record["earned"]:.1f}/{record["total_weight"]:.1f} weighted) · '
        f'{record["goals_completed"]}/{record["goal_count"]} goals at 100%'
        f"{as_of_note}{finalized_note}",
        unsafe_allow_html=True,
    )

    if not record["goals"]:
        st.caption("No goals recorded for this month.")
        return

    detail_rows = []
    for g in record["goals"]:
        detail_rows.append(
            {
                "Goal": g["name"],
                "Category": g["category"] or "—",
                "Progress": g.get("progress_display", f"{g['progress']:.2f} / {g['target']:.2f}"),
                "Done %": f"{g['completion_pct']:.0f}%",
                "Weight": f"{g['weightage']:.0f}%",
                "Status": g["status"],
                "Target met": "Yes" if g["met_target"] else "No",
            }
        )
    st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)


def render_history_tab() -> None:
    user_id = current_user_id()

    st.markdown("### History")
    st.caption(
        "Month-on-month view of all configured months. "
        "Locked months use stored final scores; the current month (and grace period) update live."
    )

    finalized = 0
    if st.session_state.pop("_history_force_finalize", False):
        finalized = finalize_due_months(user_id)
    elif not st.session_state.get("_history_finalized"):
        st.session_state["_history_finalized"] = True
        finalized = finalize_due_months(user_id)

    head_l, head_r = st.columns([4, 1])
    with head_r:
        if st.button("Refresh", key="history_refresh_btn", use_container_width=True):
            st.session_state["_history_force_finalize"] = True
            st.rerun()

    records = load_history_records(user_id)
    if not records:
        st.warning("No historical data yet. Add goals in the **Config** tab.")
        return

    if finalized:
        st.caption(f"Finalized {finalized} locked month(s) into history snapshots.")

    scores = [r["overall_pct"] for r in records if r["goal_count"] > 0]
    scored = [r for r in records if r["goal_count"] > 0]
    best = max(scored, key=lambda r: r["overall_pct"]) if scored else None
    total_goals = sum(r["goal_count"] for r in records)
    total_met = sum(r["goals_completed"] for r in records)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Months", len(records))
    m2.metric("Avg overall", f"{(sum(scores) / len(scores)):.0f}%" if scores else "—")
    m3.metric("Best month", best["label"] if best else "—")
    m4.metric("Goals at 100%", f"{total_met}/{total_goals}")

    with card_container():
        st.markdown("#### Overall trend")
        _render_trend_chart(records)

    with card_container():
        st.markdown("#### All months")
        _render_overview_table(records)

    st.markdown("#### Month details")
    for record in records:
        title = record["label"]
        if record["is_current"]:
            title += " (current)"
        with st.expander(
            f"{title} — {record['overall_pct']:.0f}% · "
            f"{record['goals_completed']}/{record['goal_count']} complete",
            expanded=record["is_current"],
        ):
            _render_month_detail(record)
