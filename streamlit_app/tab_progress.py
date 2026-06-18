"""Progress tab: update achievement against monthly goals."""

from __future__ import annotations

import calendar
from datetime import date

import streamlit as st

from config import (
    DAILY_MODE_AVOID,
    GOAL_TYPE_ACCUMULATE,
    GOAL_TYPE_DAILY,
    GOAL_TYPE_REDUCE,
    current_month_key,
    format_month_label,
    is_progress_editable,
    month_pace_fraction,
    pace_info,
    parse_month_key,
    progress_edit_deadline,
    progress_edit_status,
    weighted_score,
)
from data import (
    fetch_daily_log,
    fetch_month_goals,
    fetch_month_progress,
    fetch_progress_history,
    list_configured_months,
    save_daily_entry,
    save_month_progress,
)
from goal_scoring import (
    compute_streak,
    daily_mode_label,
    goal_completion_for_type,
    goal_progress_display,
    goal_target_hint,
    goal_type_label,
    goal_unit_caption,
    summarize_daily_log,
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


def _goal_expander_label(g: dict, g_info: dict) -> str:
    return f"{g['name']}  ·  {g_info['completion_pct']:.0f}%  ·  {g_info['label']}"


def _progress_input_key(user_id: str, month: str, goal_id: str) -> str:
    return f"progress_{user_id}_{month}_{goal_id}"


def _log_date_bounds(month_key: str) -> tuple[date, date]:
    today = date.today()
    parsed = parse_month_key(month_key)
    if not parsed:
        return today, today
    year, month = parsed
    start = date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    end = date(year, month, last_day)
    max_date = min(today, end)
    return start, max_date


def _ensure_progress_widgets(
    user_id: str, month: str, goals: list[dict], saved: dict[str, float]
) -> None:
    for g in goals:
        key = _progress_input_key(user_id, month, g["id"])
        if key not in st.session_state:
            if g["goal_type"] == GOAL_TYPE_REDUCE and saved.get(g["id"], 0.0) == 0.0:
                st.session_state[key] = float(g.get("baseline") or 0.0)
            else:
                st.session_state[key] = float(saved.get(g["id"], 0.0))


def _collect_updates(user_id: str, month: str, goals: list[dict]) -> dict[str, float]:
    return {
        g["id"]: float(
            st.session_state.get(_progress_input_key(user_id, month, g["id"]), 0.0)
        )
        for g in goals
        if g["goal_type"] != GOAL_TYPE_DAILY
    }


def _goal_completion(
    g: dict,
    progress: dict[str, float],
    daily_logs: dict[str, dict[str, str]],
    month_key: str,
) -> float:
    return goal_completion_for_type(
        g,
        progress.get(g["id"], 0.0),
        month_key=month_key,
        daily_entries=daily_logs.get(g["id"]),
    )


def _goal_expander_state_key(user_id: str, month: str, goal_id: str) -> str:
    return f"goal_exp_open_{user_id}_{month}_{goal_id}"


def _mark_goal_expander_open(exp_key: str) -> None:
    st.session_state[exp_key] = True


def _daily_chk_key(user_id: str, month_key: str, goal_id: str, iso: str) -> str:
    return f"daily_chk_{user_id}_{month_key}_{goal_id}_{iso}"


def _save_daily_toggle(
    user_id: str,
    month_key: str,
    goal_id: str,
    iso: str,
) -> None:
    ckey = _daily_chk_key(user_id, month_key, goal_id, iso)
    checked = bool(st.session_state.get(ckey, False))
    ok, msg = save_daily_entry(
        user_id,
        month_key,
        goal_id,
        iso,
        "yes" if checked else "no",
        source="app",
    )
    if not ok:
        st.session_state[ckey] = not checked
        st.error(msg)


def _render_daily_goal(
    user_id: str,
    month_key: str,
    g: dict,
    *,
    editable: bool = True,
) -> None:
    entries = fetch_daily_log(user_id, month_key, g["id"]).get(g["id"], {})
    parsed = parse_month_key(month_key)
    if not parsed:
        st.warning("Invalid month.")
        return
    year, month = parsed
    days_in_month = calendar.monthrange(year, month)[1]
    today = date.today()

    chk_prefix = f"daily_chk_{user_id}_{month_key}_{g['id']}_"
    if editable:
        for key in list(st.session_state.keys()):
            if isinstance(key, str) and key.startswith(chk_prefix):
                del st.session_state[key]

    cols = st.columns(7)
    for day in range(1, days_in_month + 1):
        log_date = date(year, month, day)
        iso = log_date.isoformat()
        label = f"{log_date.strftime('%a')} {day}"
        with cols[(day - 1) % 7]:
            if log_date > today:
                st.checkbox(
                    label,
                    value=False,
                    disabled=True,
                    key=f"daily_future_{user_id}_{g['id']}_{iso}",
                )
                continue

            db_checked = entries.get(iso, "no") == "yes"
            ckey = _daily_chk_key(user_id, month_key, g["id"], iso)
            if editable:
                st.session_state[ckey] = db_checked
                st.checkbox(
                    label,
                    key=ckey,
                    on_change=_save_daily_toggle,
                    kwargs={
                        "user_id": user_id,
                        "month_key": month_key,
                        "goal_id": g["id"],
                        "iso": iso,
                    },
                )
            else:
                st.checkbox(label, value=db_checked, disabled=True, key=ckey)


def _render_goal_body(
    user_id: str,
    month_key: str,
    g: dict,
    g_info: dict,
    *,
    editable: bool = True,
) -> None:
    """Interactive goal content; fragment rerun keeps the parent expander open."""
    exp_key = _goal_expander_state_key(user_id, month_key, g["id"])

    daily_logs = fetch_daily_log(user_id, month_key)
    saved_progress = fetch_month_progress(user_id, month_key)
    updates: dict[str, float] = {}
    if g["goal_type"] == GOAL_TYPE_DAILY:
        s = summarize_daily_log(
            g["daily_mode"],
            daily_logs.get(g["id"], {}),
            month_key=month_key,
        )
        updates[g["id"]] = float(s["good_days"])
    else:
        updates[g["id"]] = float(
            st.session_state.get(
                _progress_input_key(user_id, month_key, g["id"]),
                saved_progress.get(g["id"], 0.0),
            )
        )

    pct = _goal_completion(g, updates, daily_logs, month_key)
    g_info = pace_info(pct, month_key)
    contribution = (pct / 100.0) * g["weightage"]
    display = goal_progress_display(
        g, updates[g["id"]], month_key=month_key, daily_entries=daily_logs.get(g["id"])
    )

    type_badge = goal_type_label(g["goal_type"])
    if g["goal_type"] == GOAL_TYPE_DAILY:
        type_badge += f" · {daily_mode_label(g['daily_mode'])}"
    if g.get("category"):
        type_badge += f" · {g['category']}"
    st.caption(
        f"{type_badge} · {goal_target_hint(g)} · "
        f"Weight {g['weightage']:.0f}% · Score +{contribution:.1f}"
    )
    if g.get("notes"):
        st.caption(g["notes"])
    unit_line = goal_unit_caption(g)
    if unit_line and g["goal_type"] in (GOAL_TYPE_ACCUMULATE, GOAL_TYPE_REDUCE):
        st.caption(unit_line)
    st.markdown(
        _status_pill(g_info["pill_class"], g_info["label"]),
        unsafe_allow_html=True,
    )

    mc1, mc2, mc3 = st.columns(3)
    if g["goal_type"] == GOAL_TYPE_DAILY:
        entries = daily_logs.get(g["id"], {})
        summary = summarize_daily_log(
            g["daily_mode"], entries, month_key=month_key
        )
        mc1.metric(
            "On track",
            f"{summary['good_days']}/{summary['elapsed_days']} days",
        )
        mc2.metric("Done", f"{pct:.0f}%")
        mc3.metric("Expected", f"{g_info['expected_pct']:.0f}%")
        _, max_date = _log_date_bounds(month_key)
        streak = compute_streak(
            g["daily_mode"],
            entries,
            through=max_date,
            month_key=month_key,
        )
        streak_label = "done" if g["daily_mode"] != DAILY_MODE_AVOID else "clean"
        st.caption(
            f"Current streak: {streak} consecutive {streak_label} day(s) ending today"
        )
        _render_daily_goal(user_id, month_key, g, editable=editable)
    else:
        mc1.metric("Progress", display)
        mc2.metric("Done", f"{pct:.0f}%")
        mc3.metric("Expected", f"{g_info['expected_pct']:.0f}%")
        input_key = _progress_input_key(user_id, month_key, g["id"])
        if g["goal_type"] == GOAL_TYPE_REDUCE:
            st.number_input(
                "Current level",
                min_value=0.0,
                step=0.1,
                format="%.2f",
                key=input_key,
                on_change=_mark_goal_expander_open,
                args=(exp_key,),
                disabled=not editable,
            )
        else:
            st.number_input(
                "Update progress",
                min_value=0.0,
                step=0.5,
                format="%.2f",
                key=input_key,
                on_change=_mark_goal_expander_open,
                args=(exp_key,),
                disabled=not editable,
            )


def render_progress_tab() -> None:
    user_id = current_user_id()

    st.markdown(
        '<div id="ikr-progress-marker" aria-hidden="true" style="display:none"></div>',
        unsafe_allow_html=True,
    )
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

    progress_editable = is_progress_editable(selected_month)
    _, progress_lock_msg = progress_edit_status(selected_month)
    if progress_editable:
        deadline = progress_edit_deadline(selected_month)
        if deadline:
            st.caption(
                f"Progress for {format_month_label(selected_month)} can be updated "
                f"through **{deadline.strftime('%d %b %Y')}**."
            )
    else:
        st.warning(progress_lock_msg)

    saved_progress = fetch_month_progress(user_id, selected_month)
    daily_logs = fetch_daily_log(user_id, selected_month)
    numeric_goals = [g for g in goals if g["goal_type"] != GOAL_TYPE_DAILY]
    _ensure_progress_widgets(user_id, selected_month, numeric_goals, saved_progress)
    updates = _collect_updates(user_id, selected_month, goals)
    for g in goals:
        if g["goal_type"] == GOAL_TYPE_DAILY:
            s = summarize_daily_log(
                g["daily_mode"],
                daily_logs.get(g["id"], {}),
                month_key=selected_month,
            )
            updates[g["id"]] = float(s["good_days"])
        elif g["id"] not in updates:
            updates[g["id"]] = saved_progress.get(g["id"], 0.0)

    earned, total_weight = weighted_score(
        goals, updates, month_key=selected_month, daily_logs_by_goal=daily_logs
    )
    overall_pct = (earned / total_weight * 100.0) if total_weight > 0 else 0.0
    completed = sum(
        1
        for g in goals
        if _goal_completion(g, updates, daily_logs, selected_month) >= 100.0
    )
    overall_info = pace_info(overall_pct, selected_month)
    expected_pct = month_pace_fraction(selected_month) * 100.0

    goal_infos: list[tuple[dict, dict]] = []
    for g in goals:
        pct = _goal_completion(g, updates, daily_logs, selected_month)
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

    st.markdown("#### Goals")

    for g, g_info in goal_infos:
        exp_key = _goal_expander_state_key(user_id, selected_month, g["id"])
        with st.expander(
            _goal_expander_label(g, g_info),
            expanded=st.session_state.get(exp_key, False),
        ):
            _render_goal_body(
                user_id, selected_month, g, g_info, editable=progress_editable
            )

    numeric_to_save = _collect_updates(user_id, selected_month, numeric_goals)
    if progress_editable and numeric_to_save and st.button(
        "Save numeric progress",
        type="primary",
        use_container_width=True,
        key=f"progress_save_btn_{user_id}",
    ):
        merged = {**saved_progress, **numeric_to_save}
        ok, save_msg = save_month_progress(
            user_id,
            selected_month,
            merged,
            source="app",
        )
        if not ok:
            st.error(save_msg)
            return
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
            display = goal_progress_display(
                g, prog, month_key=selected_month, daily_entries=daily_logs.get(g["id"])
            )
            st.markdown(
                f"**{g['name']}** — {display} "
                f"({pct:.0f}%) · {g_info['label']} · +{contribution:.1f} pts"
            )
