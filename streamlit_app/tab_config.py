"""Config tab: define monthly goals with target and weightage."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from config import format_month_label, month_key, new_goal_id
from data import (
    draft_rows_for_month,
    list_configured_months,
    month_summary,
    save_month_goals,
)
from reminder_settings import allow_unequal_weightage
from session_auth import current_user_id
from styles import card_container


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
    goal_key = f"{prefix}_goal_{gid}"
    target_key = f"{prefix}_target_{gid}"
    weight_key = f"{prefix}_weight_{gid}"
    cat_key = f"{prefix}_cat_{gid}"
    notes_key = f"{prefix}_notes_{gid}"
    if goal_key not in st.session_state:
        st.session_state[goal_key] = row.get("goal", "")
    if target_key not in st.session_state:
        st.session_state[target_key] = float(row.get("target", 1.0))
    if weight_key not in st.session_state:
        st.session_state[weight_key] = float(row.get("weightage", 0.0))
    if cat_key not in st.session_state:
        st.session_state[cat_key] = row.get("category", "")
    if notes_key not in st.session_state:
        st.session_state[notes_key] = row.get("notes", "")


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
            }
        )
    return out


def render_config_tab() -> None:
    user_id = current_user_id()

    st.markdown("### Goal config")
    st.caption("Set monthly goals with a target and weightage for your account.")

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

    active_user = st.session_state.get("config_active_user")
    active_month = st.session_state.get("config_active_month")
    if active_user != user_id or active_month != selected_month:
        _reset_rows(user_id, selected_month)

    if rows_key not in st.session_state:
        st.session_state[rows_key] = _load_rows(user_id, selected_month)

    if copy_from and st.button(
        f"Apply copy from {format_month_label(copy_from)}",
        key=f"config_apply_copy_btn_{user_id}",
    ):
        _reset_rows(user_id, selected_month, copy_from=copy_from)
        st.rerun()

    rows: list[dict] = st.session_state[rows_key]

    b1, b2 = st.columns(2)
    with b1:
        if st.button("➕ Add goal", key=f"config_add_row_btn_{user_id}", use_container_width=True):
            rows.append(
                {
                    "id": new_goal_id(),
                    "goal": "",
                    "target": 1.0,
                    "weightage": 0.0,
                    "category": "",
                    "notes": "",
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

    delete_id: str | None = None
    prefix = _widget_prefix(user_id, selected_month)

    for i, row in enumerate(rows):
        gid = row["id"]
        _ensure_row_widgets(user_id, selected_month, row)
        with card_container():
            st.caption(f"Goal {i + 1}")
            st.text_input(
                "Goal name",
                key=f"{prefix}_goal_{gid}",
            )
            tw1, tw2 = st.columns(2)
            with tw1:
                st.number_input(
                    "Target",
                    min_value=0.0,
                    step=1.0,
                    format="%.2f",
                    key=f"{prefix}_target_{gid}",
                )
            with tw2:
                st.number_input(
                    "Weightage",
                    min_value=0.0,
                    step=5.0,
                    format="%.1f",
                    key=f"{prefix}_weight_{gid}",
                )
            st.text_input("Category (optional)", key=f"{prefix}_cat_{gid}")
            st.text_input("Notes (optional)", key=f"{prefix}_notes_{gid}")
            if st.button(
                "Remove goal",
                key=f"{prefix}_del_{gid}",
                use_container_width=True,
            ):
                delete_id = gid

    if delete_id:
        st.session_state[rows_key] = [r for r in rows if r["id"] != delete_id]
        for suffix in ("goal", "target", "weight", "cat", "notes"):
            key = f"{prefix}_{suffix}_{delete_id}"
            if key in st.session_state:
                del st.session_state[key]
        st.rerun()

    collected = _collect_rows(user_id, selected_month, st.session_state[rows_key])
    named = [r for r in collected if r["goal"]]
    total_weight = sum(r["weightage"] for r in named)
    st.metric("Total weightage", f"{total_weight:.1f}")
    weight_ok = abs(total_weight - 100.0) < 0.01
    if named and not weight_ok:
        st.warning("Weightages should sum to **100** for a balanced score.")
        if st.button(
            "Normalize weightages to 100%",
            key=f"config_normalize_{user_id}",
            use_container_width=True,
        ):
            scale = 100.0 / total_weight if total_weight > 0 else 0.0
            for row in named:
                wkey = f"{prefix}_weight_{row['id']}"
                st.session_state[wkey] = round(float(st.session_state[wkey]) * scale, 1)
            st.rerun()

    if st.button(
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
            out_goals.append(
                {
                    "id": row["id"],
                    "name": name,
                    "target": max(float(row["target"]), 0.0),
                    "weightage": max(float(row["weightage"]), 0.0),
                    "category": row.get("category", ""),
                    "notes": row.get("notes", ""),
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

        save_month_goals(user_id, selected_month, out_goals)
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
