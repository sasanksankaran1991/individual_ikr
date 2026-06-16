"""History tab: month-on-month goals and final status."""

from __future__ import annotations

import calendar
from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from config import (
    current_month_key,
    format_month_label,
    goal_completion_pct,
    pace_info,
    parse_month_key,
    weighted_score,
)
from data import fetch_month_goals, fetch_month_progress, list_configured_months
from session_auth import current_user_id
from styles import card_container


def _month_end_date(month_key: str) -> date | None:
    parsed = parse_month_key(month_key)
    if not parsed:
        return None
    year, month = parsed
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, last_day)


def _status_date_for_month(month_key: str) -> date:
    current = current_month_key()
    if month_key == current:
        return date.today()
    end = _month_end_date(month_key)
    return end or date.today()


def _build_month_record(user_id: str, month_key: str) -> dict:
    goals = fetch_month_goals(user_id, month_key)
    progress = fetch_month_progress(user_id, month_key)
    earned, total_weight = weighted_score(goals, progress)
    overall_pct = (earned / total_weight * 100.0) if total_weight > 0 else 0.0
    on_date = _status_date_for_month(month_key)
    overall_info = pace_info(overall_pct, month_key, on_date=on_date)

    goal_rows: list[dict] = []
    completed = 0
    for g in goals:
        prog = progress.get(g["id"], 0.0)
        pct = goal_completion_pct(prog, g["target"])
        info = pace_info(pct, month_key, on_date=on_date)
        met = pct >= 100.0
        if met:
            completed += 1
        goal_rows.append(
            {
                "name": g["name"],
                "category": g.get("category", ""),
                "target": g["target"],
                "progress": prog,
                "weightage": g["weightage"],
                "completion_pct": pct,
                "status": info["label"],
                "tone": info["tone"],
                "met_target": met,
            }
        )

    return {
        "month_key": month_key,
        "label": format_month_label(month_key),
        "is_current": month_key == current_month_key(),
        "goal_count": len(goals),
        "goals_completed": completed,
        "overall_pct": overall_pct,
        "earned": earned,
        "total_weight": total_weight,
        "overall_status": overall_info["label"],
        "overall_tone": overall_info["tone"],
        "goals": goal_rows,
    }


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
        rows.append(
            {
                "Month": r["label"] + (" · current" if r["is_current"] else ""),
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
    st.markdown(
        f'{_pace_pill(tone, record["overall_status"])} '
        f'Overall **{record["overall_pct"]:.0f}%** '
        f'({record["earned"]:.1f}/{record["total_weight"]:.1f} weighted) · '
        f'{record["goals_completed"]}/{record["goal_count"]} goals at 100%',
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
                "Progress": f"{g['progress']:.2f} / {g['target']:.2f}",
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
        "Past months use end-of-month status; the current month uses today's pace."
    )

    months = list_configured_months(user_id)
    if not months:
        st.warning("No historical data yet. Add goals in the **Config** tab.")
        return

    records = [_build_month_record(user_id, mk) for mk in months]

    scores = [r["overall_pct"] for r in records if r["goal_count"] > 0]
    best = max(records, key=lambda r: r["overall_pct"])
    total_goals = sum(r["goal_count"] for r in records)
    total_met = sum(r["goals_completed"] for r in records)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Months", len(records))
    m2.metric("Avg overall", f"{(sum(scores) / len(scores)):.0f}%" if scores else "—")
    m3.metric("Best month", best["label"] if scores else "—")
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
