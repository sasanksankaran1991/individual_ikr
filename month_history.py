"""Build month history records and load live vs finalized snapshots."""

from __future__ import annotations

import calendar
import json
from datetime import date

from config import (
    current_month_key,
    format_month_label,
    is_progress_editable,
    pace_info,
    parse_month_key,
    progress_edit_deadline,
    weighted_score,
)
from data import (
    fetch_daily_log,
    fetch_month_goals,
    fetch_month_progress,
    fetch_month_summary,
    list_configured_months,
    save_month_summary,
)
from goal_scoring import goal_completion_for_type, goal_progress_display


def _month_end_date(month_key: str) -> date | None:
    parsed = parse_month_key(month_key)
    if not parsed:
        return None
    year, month = parsed
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, last_day)


def score_as_of_date(month_key: str, *, for_finalize: bool = False) -> date:
    """Date used for pace/completion — lock deadline when finalizing locked months."""
    if for_finalize:
        deadline = progress_edit_deadline(month_key)
        if deadline:
            return deadline
        return _month_end_date(month_key) or date.today()
    if is_progress_editable(month_key):
        return date.today()
    deadline = progress_edit_deadline(month_key)
    if deadline:
        return deadline
    return _month_end_date(month_key) or date.today()


def build_month_record(
    user_id: str,
    month_key: str,
    *,
    for_finalize: bool = False,
) -> dict:
    goals = fetch_month_goals(user_id, month_key)
    progress = fetch_month_progress(user_id, month_key)
    daily_logs = fetch_daily_log(user_id, month_key)
    earned, total_weight = weighted_score(
        goals, progress, month_key=month_key, daily_logs_by_goal=daily_logs
    )
    overall_pct = (earned / total_weight * 100.0) if total_weight > 0 else 0.0
    on_date = score_as_of_date(month_key, for_finalize=for_finalize)
    overall_info = pace_info(overall_pct, month_key, on_date=on_date)

    goal_rows: list[dict] = []
    completed = 0
    for g in goals:
        prog = progress.get(g["id"], 0.0)
        pct = goal_completion_for_type(
            g,
            prog,
            month_key=month_key,
            daily_entries=daily_logs.get(g["id"]),
            on_date=on_date,
        )
        info = pace_info(pct, month_key, on_date=on_date)
        met = pct >= 100.0
        if met:
            completed += 1
        display = goal_progress_display(
            g, prog, month_key=month_key, daily_entries=daily_logs.get(g["id"])
        )
        goal_rows.append(
            {
                "name": g["name"],
                "category": g.get("category", ""),
                "target": g["target"],
                "progress": prog,
                "progress_display": display,
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
        "score_as_of_date": on_date.isoformat(),
        "is_finalized": False,
    }


def _snapshot_to_record(row: dict) -> dict:
    goals = json.loads(row["goals_json"])
    return {
        "month_key": row["month_key"],
        "label": format_month_label(row["month_key"]),
        "is_current": row["month_key"] == current_month_key(),
        "goal_count": int(row["goal_count"]),
        "goals_completed": int(row["goals_completed"]),
        "overall_pct": float(row["overall_pct"]),
        "earned": float(row["earned"]),
        "total_weight": float(row["total_weight"]),
        "overall_status": row["overall_status"],
        "overall_tone": row["overall_tone"],
        "goals": goals,
        "score_as_of_date": row["score_as_of_date"],
        "is_finalized": True,
        "finalized_at": row.get("finalized_at"),
    }


def finalize_month_summary(user_id: str, month_key: str) -> dict | None:
    """Compute and store final scores once the progress lock period has ended."""
    if is_progress_editable(month_key):
        return None
    record = build_month_record(user_id, month_key, for_finalize=True)
    save_month_summary(user_id, month_key, record)
    record["is_finalized"] = True
    return record


def load_month_record(user_id: str, month_key: str) -> dict:
    """Live calculation for editable months; stored snapshot when locked."""
    if is_progress_editable(month_key):
        record = build_month_record(user_id, month_key)
        record["is_finalized"] = False
        return record

    snapshot = fetch_month_summary(user_id, month_key)
    if snapshot:
        return _snapshot_to_record(snapshot)

    finalized = finalize_month_summary(user_id, month_key)
    if finalized:
        return finalized

    record = build_month_record(user_id, month_key, for_finalize=True)
    record["is_finalized"] = True
    return record


def load_history_records(user_id: str) -> list[dict]:
    months = list_configured_months(user_id)
    return [load_month_record(user_id, mk) for mk in months]


def finalize_due_months(user_id: str) -> int:
    """Backfill snapshots for all locked months missing a stored summary."""
    count = 0
    for month_key in list_configured_months(user_id):
        if is_progress_editable(month_key):
            continue
        if fetch_month_summary(user_id, month_key):
            continue
        if finalize_month_summary(user_id, month_key):
            count += 1
    return count
