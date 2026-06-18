"""Config tab: define monthly goals with target and weightage."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from config import (
    DAILY_MODE_AVOID,
    DAILY_MODE_DO,
    GOAL_TYPE_ACCUMULATE,
    GOAL_TYPE_DAILY,
    GOAL_TYPE_REDUCE,
    config_edit_deadline,
    config_edit_status,
    format_month_label,
    is_config_editable,
    month_key,
    new_goal_id,
)
from data import (
    draft_rows_for_month,
    list_configured_months,
    month_summary,
    save_month_goals,
)
from goal_scoring import daily_mode_label, goal_type_label
from reminder_settings import allow_unequal_weightage
from session_auth import current_user_id

_GOAL_TYPE_OPTIONS = [
    (GOAL_TYPE_ACCUMULATE, goal_type_label(GOAL_TYPE_ACCUMULATE)),
    (GOAL_TYPE_REDUCE, goal_type_label(GOAL_TYPE_REDUCE)),
    (GOAL_TYPE_DAILY, goal_type_label(GOAL_TYPE_DAILY)),
]
_DAILY_MODE_OPTIONS = [
    (DAILY_MODE_DO, daily_mode_label(DAILY_MODE_DO)),
    (DAILY_MODE_AVOID, daily_mode_label(DAILY_MODE_AVOID)),
]


def _month_picker(key_prefix: str) -> str:
    today = pd.Timestamp.today()
    c1, c2 = st.columns(2)
    with c1:
        year = st.number_input(
            "Year",
            min_value=2020,
            max_value=2100,
            value=int(today.year),
            step=1,
            key=f"{key_prefix}_year",
        )
    with c2:
        month = st.selectbox(
            "Month",
            options=list(range(1, 13)),
            format_func=lambda m: pd.Timestamp(year=2000, month=m, day=1).strftime("%B"),
            index=int(today.month) - 1,
            key=f"{key_prefix}_month",
        )
    selected = month_key(int(year), int(month))
    st.caption(f"Selected: **{format_month_label(selected)}** (`{selected}`)")
    return selected


def _rows_key(user_id: str, month: str) -> str:
    return f"config_rows_{user_id}_{month}"


def _widget_prefix(user_id: str, month: str) -> str:
    return f"cfg_{user_id}_{month}"


def _clear_widget_keys(user_id: str, month: str) -> None:
    prefix = _widget_prefix(user_id, month) + "_"
    for key in list(st.session_state.keys()):
        if isinstance(key, str) and key.startswith(prefix):
            del st.session_state[key]


def _load_rows(user_id: str, month: str, *, copy_from: str | None = None) -> list[dict]:
    if copy_from:
        rows = draft_rows_for_month(user_id, copy_from)
        for row in rows:
            row["id"] = new_goal_id()
    else:
        rows = draft_rows_for_month(user_id, month)
    return rows


def _reset_rows(user_id: str, month: str, *, copy_from: str | None = None) -> None:
    _clear_widget_keys(user_id, month)
    st.session_state.config_active_user = user_id
    st.session_state.config_active_month = month
    st.session_state[_rows_key(user_id, month)] = _load_rows(
        user_id, month, copy_from=copy_from
    )


def _ensure_row_widgets(user_id: str, month: str, row: dict) -> None:
    gid = row["id"]
    prefix = _widget_prefix(user_id, month)
    defaults: dict[str, object] = {
        "goal": "",
        "target": 1.0,
        "weightage": 0.0,
        "category": "",
        "notes": "",
        "goal_type": GOAL_TYPE_ACCUMULATE,
        "baseline": 0.0,
        "unit": "",
        "daily_mode": DAILY_MODE_DO,
    }
    # Widget key suffixes (weightage is stored under "weight" in session_state).
    key_fields = {
        "goal": "goal",
        "target": "target",
        "weightage": "weight",
        "category": "cat",
        "notes": "notes",
        "goal_type": "goal_type",
        "baseline": "baseline",
        "unit": "unit",
        "daily_mode": "daily_mode",
    }
    for field, key_suffix in key_fields.items():
        key = f"{prefix}_{key_suffix}_{gid}"
        if key not in st.session_state:
            st.session_state[key] = row.get(field, defaults[field])


def _collect_rows(user_id: str, month: str, rows: list[dict]) -> list[dict]:
    prefix = _widget_prefix(user_id, month)
    out: list[dict] = []
    for row in rows:
        gid = row["id"]
        out.append(
            {
                "id": gid,
                "goal": str(st.session_state.get(f"{prefix}_goal_{gid}", "")).strip(),
                "target": float(st.session_state.get(f"{prefix}_target_{gid}", 0.0)),
                "weightage": float(st.session_state.get(f"{prefix}_weight_{gid}", 0.0)),
                "category": str(st.session_state.get(f"{prefix}_cat_{gid}", "")).strip(),
                "notes": str(st.session_state.get(f"{prefix}_notes_{gid}", "")).strip(),
                "goal_type": str(st.session_state.get(f"{prefix}_goal_type_{gid}", GOAL_TYPE_ACCUMULATE)),
                "baseline": float(st.session_state.get(f"{prefix}_baseline_{gid}", 0.0)),
                "unit": str(st.session_state.get(f"{prefix}_unit_{gid}", "")).strip(),
                "daily_mode": str(st.session_state.get(f"{prefix}_daily_mode_{gid}", DAILY_MODE_DO)),
            }
        )
    return out


def _target_help(goal_type: str, daily_mode: str) -> str:
    if goal_type == GOAL_TYPE_REDUCE:
        return "End target (e.g. 75 kg after losing 5 kg from baseline)."
    if goal_type == GOAL_TYPE_DAILY:
        if daily_mode == DAILY_MODE_DO:
            return "Optional personal target; score uses checked days / elapsed days."
        return "Stay unchecked every day — score uses on-track days / elapsed days."
    return "Monthly target to reach."


def _total_weightage(user_id: str, month: str, rows: list[dict]) -> float:
    collected = _collect_rows(user_id, month, rows)
    return sum(r["weightage"] for r in collected)


def _config_expander_state_key(user_id: str, month: str, goal_id: str) -> str:
    return f"cfg_exp_open_{user_id}_{month}_{goal_id}"


def _mark_config_expander_open(exp_key: str) -> None:
    st.session_state[exp_key] = True


def _render_single_goal_row(
    user_id: str,
    selected_month: str,
    row: dict,
    *,
    editable: bool = True,
) -> str | None:
    """One goal's editable fields; fragment rerun keeps the parent expander open."""
    gid = row["id"]
    prefix = _widget_prefix(user_id, selected_month)
    exp_key = _config_expander_state_key(user_id, selected_month, gid)
    keep_open = _mark_config_expander_open

    _ensure_row_widgets(user_id, selected_month, row)

    type_labels = [label for _, label in _GOAL_TYPE_OPTIONS]
    type_values = [val for val, _ in _GOAL_TYPE_OPTIONS]
    mode_labels = [label for _, label in _DAILY_MODE_OPTIONS]
    mode_values = [val for val, _ in _DAILY_MODE_OPTIONS]

    st.text_input(
        "Goal name",
        key=f"{prefix}_goal_{gid}",
        on_change=keep_open,
        args=(exp_key,),
        disabled=not editable,
    )

    type_idx = type_values.index(
        st.session_state.get(f"{prefix}_goal_type_{gid}", GOAL_TYPE_ACCUMULATE)
    ) if st.session_state.get(f"{prefix}_goal_type_{gid}", GOAL_TYPE_ACCUMULATE) in type_values else 0
    selected_type_label = st.selectbox(
        "Goal type",
        options=type_labels,
        index=type_idx,
        key=f"{prefix}_goal_type_sel_{gid}",
        on_change=keep_open,
        args=(exp_key,),
        disabled=not editable,
    )
    st.session_state[f"{prefix}_goal_type_{gid}"] = type_values[type_labels.index(selected_type_label)]
    goal_type = st.session_state[f"{prefix}_goal_type_{gid}"]

    st.text_input(
        "Unit (optional)",
        key=f"{prefix}_unit_{gid}",
        placeholder="hrs, kg, days…",
        on_change=keep_open,
        args=(exp_key,),
        disabled=not editable,
    )

    if goal_type == GOAL_TYPE_REDUCE:
        st.number_input(
            "Baseline (start of month)",
            min_value=0.0,
            step=0.1,
            format="%.1f",
            key=f"{prefix}_baseline_{gid}",
            help="Starting level, e.g. 80 kg.",
            on_change=keep_open,
            args=(exp_key,),
            disabled=not editable,
        )

    if goal_type == GOAL_TYPE_DAILY:
        mode_idx = mode_values.index(
            st.session_state.get(f"{prefix}_daily_mode_{gid}", DAILY_MODE_DO)
        ) if st.session_state.get(f"{prefix}_daily_mode_{gid}", DAILY_MODE_DO) in mode_values else 0
        selected_mode_label = st.selectbox(
            "Daily mode",
            options=mode_labels,
            index=mode_idx,
            key=f"{prefix}_daily_mode_sel_{gid}",
            on_change=keep_open,
            args=(exp_key,),
            disabled=not editable,
        )
        st.session_state[f"{prefix}_daily_mode_{gid}"] = mode_values[
            mode_labels.index(selected_mode_label)
        ]
        daily_mode = st.session_state[f"{prefix}_daily_mode_{gid}"]
        if daily_mode == DAILY_MODE_AVOID:
            st.session_state[f"{prefix}_target_{gid}"] = 0.0
    else:
        daily_mode = DAILY_MODE_DO

    tw1, tw2 = st.columns(2)
    with tw1:
        if goal_type == GOAL_TYPE_DAILY and daily_mode == DAILY_MODE_AVOID:
            st.caption("**Target:** unchecked every day (0 slips)")
        else:
            st.number_input(
                "Target",
                min_value=0.0,
                step=1.0,
                format="%.2f",
                key=f"{prefix}_target_{gid}",
                help=_target_help(goal_type, daily_mode),
                on_change=keep_open,
                args=(exp_key,),
                disabled=not editable,
            )
    with tw2:
        st.number_input(
            "Weightage",
            min_value=0.0,
            step=5.0,
            format="%.1f",
            key=f"{prefix}_weight_{gid}",
            on_change=keep_open,
            args=(exp_key,),
            disabled=not editable,
        )
    st.text_input(
        "Category (optional)",
        key=f"{prefix}_cat_{gid}",
        on_change=keep_open,
        args=(exp_key,),
        disabled=not editable,
    )
    st.text_input(
        "Notes (optional)",
        key=f"{prefix}_notes_{gid}",
        on_change=keep_open,
        args=(exp_key,),
        disabled=not editable,
    )
    if editable and st.button(
        "Remove goal",
        key=f"{prefix}_del_{gid}",
        use_container_width=True,
    ):
        return gid
    return None


def _render_goal_rows(
    user_id: str,
    selected_month: str,
    rows: list[dict],
    rows_key: str,
    *,
    editable: bool = True,
) -> str | None:
    """Editable goal list + live total weightage. Returns goal id to delete, if any."""
    delete_id: str | None = None
    prefix = _widget_prefix(user_id, selected_month)

    for i, row in enumerate(rows):
        gid = row["id"]
        _ensure_row_widgets(user_id, selected_month, row)
        goal_name = str(st.session_state.get(f"{prefix}_goal_{gid}", "")).strip()
        weight_val = float(st.session_state.get(f"{prefix}_weight_{gid}", row.get("weightage", 0.0)))
        header = goal_name if goal_name else f"Goal {i + 1} (unnamed)"
        expander_label = f"{header}  ·  {weight_val:.1f}% weightage"
        exp_key = _config_expander_state_key(user_id, selected_month, gid)

        with st.expander(
            expander_label,
            expanded=st.session_state.get(exp_key, False),
        ):
            maybe_del = _render_single_goal_row(
                user_id, selected_month, row, editable=editable
            )
            if maybe_del:
                delete_id = maybe_del

    total_weight = _total_weightage(user_id, selected_month, rows)
    st.metric("Total weightage", f"{total_weight:.1f}")
    if abs(total_weight - 100.0) >= 0.01 and rows:
        st.caption("Should sum to **100** for a balanced score.")

    return delete_id


def render_config_tab() -> None:
    user_id = current_user_id()

    st.markdown("### Goal config")
    st.caption(
        "Set monthly goals. Types: **Accumulate** (build up), **Reduce** (e.g. weight), "
        "**Daily log** (walk / no-smoking with yes/no)."
    )

    configured = list_configured_months(user_id)
    copy_from: str | None = None
    if configured:
        copy_from_choice = st.selectbox(
            "Copy goals from an existing month (optional)",
            options=["— none —"] + configured,
            format_func=lambda k: "— none —" if k == "— none —" else format_month_label(k),
            key=f"config_copy_from_{user_id}",
        )
        if copy_from_choice != "— none —":
            copy_from = copy_from_choice

    selected_month = _month_picker(f"config_{user_id}")
    rows_key = _rows_key(user_id, selected_month)
    config_editable = is_config_editable(selected_month)
    _, config_lock_msg = config_edit_status(selected_month)

    if config_editable:
        deadline = config_edit_deadline(selected_month)
        if deadline:
            st.caption(
                f"Goals for {format_month_label(selected_month)} can be edited "
                f"through **{deadline.strftime('%d %b %Y')}**."
            )
    else:
        st.warning(config_lock_msg)

    active_user = st.session_state.get("config_active_user")
    active_month = st.session_state.get("config_active_month")
    if active_user != user_id or active_month != selected_month:
        _reset_rows(user_id, selected_month)

    if rows_key not in st.session_state:
        st.session_state[rows_key] = _load_rows(user_id, selected_month)

    if copy_from and config_editable and st.button(
        f"Apply copy from {format_month_label(copy_from)}",
        key=f"config_apply_copy_btn_{user_id}",
    ):
        _reset_rows(user_id, selected_month, copy_from=copy_from)
        st.rerun()

    rows: list[dict] = st.session_state[rows_key]

    b1, b2 = st.columns(2)
    with b1:
        if config_editable and st.button(
            "➕ Add goal", key=f"config_add_row_btn_{user_id}", use_container_width=True
        ):
            rows.append(
                {
                    "id": new_goal_id(),
                    "goal": "",
                    "target": 1.0,
                    "weightage": 0.0,
                    "category": "",
                    "notes": "",
                    "goal_type": GOAL_TYPE_ACCUMULATE,
                    "baseline": 0.0,
                    "unit": "",
                    "daily_mode": DAILY_MODE_DO,
                }
            )
            st.session_state[rows_key] = rows
            st.rerun()
    with b2:
        if st.button("Reload", key=f"config_reload_btn_{user_id}", use_container_width=True):
            _reset_rows(user_id, selected_month)
            st.rerun()

    if not rows:
        st.info("No goals yet. Tap **Add goal** to start.")
        return

    delete_id = _render_goal_rows(
        user_id, selected_month, rows, rows_key, editable=config_editable
    )
    prefix = _widget_prefix(user_id, selected_month)

    if delete_id:
        st.session_state[rows_key] = [r for r in rows if r["id"] != delete_id]
        for suffix in (
            "goal", "target", "weight", "cat", "notes", "goal_type", "goal_type_sel",
            "baseline", "unit", "daily_mode", "daily_mode_sel",
        ):
            key = f"{prefix}_{suffix}_{delete_id}"
            if key in st.session_state:
                del st.session_state[key]
        st.rerun()

    collected = _collect_rows(user_id, selected_month, st.session_state[rows_key])
    named = [r for r in collected if r["goal"]]
    total_weight = _total_weightage(user_id, selected_month, st.session_state[rows_key])
    weight_ok = abs(total_weight - 100.0) < 0.01
    if named and not weight_ok and config_editable:
        st.warning("Weightages should sum to **100** for a balanced score.")
        if st.button(
            "Normalize weightages to 100%",
            key=f"config_normalize_{user_id}",
            use_container_width=True,
        ):
            scale = 100.0 / total_weight if total_weight > 0 else 0.0
            updated_rows = st.session_state[rows_key]
            for row in updated_rows:
                gid = row["id"]
                wkey = f"{prefix}_weight_{gid}"
                current = float(st.session_state.get(wkey, row.get("weightage", 0.0)))
                row["weightage"] = round(current * scale, 1)
                if wkey in st.session_state:
                    del st.session_state[wkey]
            st.session_state[rows_key] = updated_rows
            st.rerun()

    if config_editable and st.button(
        "Save goals for this month",
        type="primary",
        key=f"config_save_btn_{user_id}",
        use_container_width=True,
    ):
        out_goals: list[dict] = []
        seen_names: set[str] = set()
        dupes: list[str] = []

        for row in collected:
            name = row["goal"]
            if not name:
                continue
            name_lower = name.lower()
            if name_lower in seen_names:
                dupes.append(name)
                continue
            seen_names.add(name_lower)
            gt = row.get("goal_type", GOAL_TYPE_ACCUMULATE)
            dm = row.get("daily_mode", DAILY_MODE_DO)
            if gt == GOAL_TYPE_REDUCE and float(row.get("baseline", 0)) <= float(row["target"]):
                st.error(f"Reduce goal '{name}': baseline must be greater than target.")
                return
            target_val = 0.0 if gt == GOAL_TYPE_DAILY and dm == DAILY_MODE_AVOID else max(float(row["target"]), 0.0)
            out_goals.append(
                {
                    "id": row["id"],
                    "name": name,
                    "target": target_val,
                    "weightage": max(float(row["weightage"]), 0.0),
                    "category": row.get("category", ""),
                    "notes": row.get("notes", ""),
                    "goal_type": gt,
                    "baseline": max(float(row.get("baseline") or 0.0), 0.0),
                    "unit": row.get("unit", ""),
                    "daily_mode": row.get("daily_mode", DAILY_MODE_DO),
                }
            )

        if dupes:
            st.error("Duplicate goal names: " + ", ".join(sorted(set(dupes))))
            return
        if not out_goals:
            st.error("Add at least one goal with a non-empty name.")
            return

        if not weight_ok and not allow_unequal_weightage():
            st.error(
                "Total weightage must be 100. Tap **Normalize weightages to 100%**, "
                "or ask admin to allow unequal weights in Settings."
            )
            return

        ok, save_msg = save_month_goals(user_id, selected_month, out_goals)
        if not ok:
            st.error(save_msg)
            return
        _reset_rows(user_id, selected_month)
        st.success(f"Saved goals for {format_month_label(selected_month)}.")
        st.rerun()

    summaries = month_summary(user_id)
    if summaries:
        st.divider()
        st.markdown("**Configured months**")
        for m, n, total_w in summaries:
            st.caption(
                f"- {format_month_label(m)}: {n} goal(s), weightage {total_w:.1f}"
            )
