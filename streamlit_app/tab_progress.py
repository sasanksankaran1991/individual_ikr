"""Progress tab: update achievement against monthly goals."""

from __future__ import annotations

import streamlit as st

from config import (
    current_month_key,
    format_month_label,
    goal_completion_pct,
    weighted_score,
)
from data import (
    fetch_month_goals,
    fetch_month_progress,
    list_configured_months,
    save_month_progress,
)
from session_auth import current_user_id
from styles import card_container


def _status_pill(pct: float) -> str:
    if pct >= 100.0:
        label, css = "Complete", "ikr-pill-done"
    elif pct > 0:
        label, css = "In progress", "ikr-pill-progress"
    else:
        label, css = "Not started", "ikr-pill-todo"
    return f'<span class="ikr-pill {css}">{label}</span>'


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
    st.caption("Track your goals for the month and update progress.")

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

    with card_container():
        r1a, r1b = st.columns(2)
        r2a, r2b = st.columns(2)
        r1a.metric("Overall score", f"{overall_pct:.0f}%")
        r1b.metric("Weighted pts", f"{earned:.1f}/{total_weight:.1f}")
        r2a.metric("Complete", f"{completed}/{len(goals)}")
        r2b.metric("Goals", str(len(goals)))
        st.progress(min(overall_pct / 100.0, 1.0))

    st.markdown("#### Goals")

    for g in goals:
        prog = updates[g["id"]]
        pct = goal_completion_pct(prog, g["target"])
        contribution = (pct / 100.0) * g["weightage"]
        remaining = max(g["target"] - prog, 0.0)

        with card_container():
            st.markdown(
                f'<p class="ikr-goal-title">{g["name"]}</p>'
                f'<p class="ikr-meta">Target {g["target"]:.2f} · '
                f'Weight {g["weightage"]:.0f}% · Score +{contribution:.1f}</p>',
                unsafe_allow_html=True,
            )
            st.markdown(_status_pill(pct), unsafe_allow_html=True)
            st.progress(min(pct / 100.0, 1.0))

            mc1, mc2 = st.columns(2)
            mc1.metric("Progress", f"{prog:.2f}")
            mc2.metric("Done", f"{pct:.0f}%")
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
            user_id, selected_month, _collect_updates(user_id, selected_month, goals)
        )
        st.success(f"Progress saved for {format_month_label(selected_month)}.")
        st.rerun()

    with st.expander("Score breakdown", expanded=False):
        for g in goals:
            prog = updates[g["id"]]
            pct = goal_completion_pct(prog, g["target"])
            contribution = (pct / 100.0) * g["weightage"]
            st.markdown(
                f"**{g['name']}** — {prog:.2f}/{g['target']:.2f} "
                f"({pct:.0f}%) · +{contribution:.1f} pts"
            )
