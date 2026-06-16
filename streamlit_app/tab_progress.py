"""Progress tab: update achievement against monthly goals."""

from __future__ import annotations

import streamlit as st

from config import (
    current_month_key,
    format_month_label,
    goal_completion_pct,
    month_pace_fraction,
    pace_info,
    weighted_score,
)
from data import (
    fetch_month_goals,
    fetch_month_progress,
    fetch_progress_history,
    list_configured_months,
    save_month_progress,
)
from progress_timeline import render_overall_timeline
from session_auth import current_user_id
from styles import card_container


def _status_pill(pill_class: str, label: str) -> str:
    return f'<span class="ikr-pill {pill_class}">{label}</span>'


def _pace_banner(info: dict, *, heading: str = "") -> str:
    sign = "+" if info["diff"] >= 0 else ""
    title = f"{heading} · " if heading else ""
    return (
        f'<div class="ikr-pace-banner {info["banner_class"]}">'
        f'{title}<strong>{info["label"]}</strong> '
        f"· {info['completion_pct']:.0f}% done "
        f"· expected {info['expected_pct']:.0f}% "
        f"· <span>{sign}{info['diff']:.0f}% vs pace</span>"
        f"</div>"
    )


def _goal_glance_row(name: str, info: dict) -> str:
    return (
        f'<div class="ikr-goal-glance ikr-goal-glance-{info["tone"]}">'
        f"<strong>{name}</strong> — {info['label']} "
        f"({info['completion_pct']:.0f}% / {info['expected_pct']:.0f}% expected)"
        f"</div>"
    )


def _progress_input_key(user_id: str, month: str, goal_id: str) -> str:
    return f"progress_{user_id}_{month}_{goal_id}"


def _ensure_progress_widgets(
    user_id: str, month: str, goals: list[dict], saved: dict[str, float]
) -> None:
    for g in goals:
        key = _progress_input_key(user_id, month, g["id"])
        if key not in st.session_state:
            st.session_state[key] = float(saved.get(g["id"], 0.0))


def _collect_updates(user_id: str, month: str, goals: list[dict]) -> dict[str, float]:
    return {
        g["id"]: float(
            st.session_state.get(_progress_input_key(user_id, month, g["id"]), 0.0)
        )
        for g in goals
    }


def render_progress_tab() -> None:
    user_id = current_user_id()

    st.markdown("### Progress")
    st.caption(
        "Green = ahead of month pace · Red = behind · Amber = on track "
        "(±5% of expected)."
    )

    configured = list_configured_months(user_id)
    if not configured:
        st.warning("No goals yet. Open the **Config** tab to add monthly goals.")
        return

    default_month = current_month_key() if current_month_key() in configured else configured[0]
    default_index = configured.index(default_month) if default_month in configured else 0

    selected_month = st.selectbox(
        "Month",
        options=configured,
        index=default_index,
        format_func=format_month_label,
        key=f"progress_month_{user_id}",
    )

    goals = fetch_month_goals(user_id, selected_month)
    if not goals:
        st.warning(f"No goals found for {format_month_label(selected_month)}.")
        return

    saved_progress = fetch_month_progress(user_id, selected_month)
    _ensure_progress_widgets(user_id, selected_month, goals, saved_progress)
    updates = _collect_updates(user_id, selected_month, goals)

    earned, total_weight = weighted_score(goals, updates)
    overall_pct = (earned / total_weight * 100.0) if total_weight > 0 else 0.0
    completed = sum(
        1 for g in goals if goal_completion_pct(updates[g["id"]], g["target"]) >= 100.0
    )
    overall_info = pace_info(overall_pct, selected_month)
    expected_pct = month_pace_fraction(selected_month) * 100.0

    goal_infos: list[tuple[dict, dict]] = []
    for g in goals:
        pct = goal_completion_pct(updates[g["id"]], g["target"])
        goal_infos.append((g, pace_info(pct, selected_month)))

    ahead_n = sum(1 for _, i in goal_infos if i["tone"] == "ahead")
    behind_n = sum(1 for _, i in goal_infos if i["tone"] == "behind")
    track_n = len(goal_infos) - ahead_n - behind_n

    with card_container():
        st.markdown(_pace_banner(overall_info, heading="Overall"), unsafe_allow_html=True)
        r1a, r1b = st.columns(2)
        r2a, r2b = st.columns(2)
        r1a.metric("Overall score", f"{overall_pct:.0f}%")
        r1b.metric("Weighted pts", f"{earned:.1f}/{total_weight:.1f}")
        r2a.metric("Complete", f"{completed}/{len(goals)}")
        r2b.metric("Month elapsed", f"{expected_pct:.0f}%")
        st.caption(
            f"Goals: {ahead_n} ahead · {track_n} on track · {behind_n} behind"
        )
        render_overall_timeline(user_id, selected_month, goals, updates)

    if len(goals) > 1:
        st.markdown("#### Goals at a glance")
        glance_html = "".join(_goal_glance_row(g["name"], info) for g, info in goal_infos)
        st.markdown(glance_html, unsafe_allow_html=True)

    st.markdown("#### Goals")

    for g, g_info in goal_infos:
        prog = updates[g["id"]]
        pct = g_info["completion_pct"]
        contribution = (pct / 100.0) * g["weightage"]
        remaining = max(g["target"] - prog, 0.0)

        with card_container():
            st.markdown(_pace_banner(g_info), unsafe_allow_html=True)
            title = g["name"]
            if g.get("category"):
                title += f" · {g['category']}"
            st.markdown(
                f'<p class="ikr-goal-title">{title}</p>'
                f'<p class="ikr-meta">Target {g["target"]:.2f} · '
                f'Weight {g["weightage"]:.0f}% · Score +{contribution:.1f}</p>',
                unsafe_allow_html=True,
            )
            if g.get("notes"):
                st.caption(g["notes"])
            st.markdown(
                _status_pill(g_info["pill_class"], g_info["label"]),
                unsafe_allow_html=True,
            )

            mc1, mc2, mc3 = st.columns(3)
            mc1.metric("Progress", f"{prog:.2f}")
            mc2.metric("Done", f"{pct:.0f}%")
            mc3.metric("Expected", f"{g_info['expected_pct']:.0f}%")
            st.caption(f"Remaining: {remaining:.2f} of {g['target']:.2f}")

            st.number_input(
                "Update progress",
                min_value=0.0,
                step=0.5,
                format="%.2f",
                key=_progress_input_key(user_id, selected_month, g["id"]),
                help=f"Target: {g['target']:.2f}",
            )

    st.divider()

    if st.button(
        "Save progress",
        type="primary",
        use_container_width=True,
        key=f"progress_save_btn_{user_id}",
    ):
        save_month_progress(
            user_id,
            selected_month,
            _collect_updates(user_id, selected_month, goals),
            source="app",
        )
        st.success(f"Progress saved for {format_month_label(selected_month)}.")
        st.rerun()

    history = fetch_progress_history(user_id, selected_month, limit=30)
    if history:
        with st.expander("Recent progress history", expanded=False):
            for h in history:
                st.caption(
                    f"**{h['goal_name']}** → {h['value']:.2f} "
                    f"via {h['source']} · {h['recorded_at'][:19]}"
                )

    with st.expander("Score breakdown", expanded=False):
        for g, g_info in goal_infos:
            prog = updates[g["id"]]
            pct = g_info["completion_pct"]
            contribution = (pct / 100.0) * g["weightage"]
            st.markdown(
                f"**{g['name']}** — {prog:.2f}/{g['target']:.2f} "
                f"({pct:.0f}%) · {g_info['label']} · +{contribution:.1f} pts"
            )
