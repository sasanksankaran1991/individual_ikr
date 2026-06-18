"""Goal-type-aware completion and scoring."""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from config import (
    GOAL_TYPE_ACCUMULATE,
    GOAL_TYPE_DAILY,
    GOAL_TYPE_REDUCE,
    DAILY_MODE_AVOID,
    DAILY_MODE_DO,
    goal_completion_pct,
    month_pace_fraction,
    parse_month_key,
)

DAILY_YES = "yes"
DAILY_NO = "no"


def goal_type_label(goal_type: str) -> str:
    return {
        GOAL_TYPE_ACCUMULATE: "Accumulate (build up)",
        GOAL_TYPE_REDUCE: "Reduce (level down)",
        GOAL_TYPE_DAILY: "Daily log (yes/no)",
    }.get(goal_type, goal_type)


def daily_mode_label(mode: str) -> str:
    return {
        DAILY_MODE_DO: "Do daily (1 = done)",
        DAILY_MODE_AVOID: "Avoid (0 = on track)",
    }.get(mode, mode)


def normalize_goal(raw: dict) -> dict:
    goal_type = str(raw.get("goal_type") or GOAL_TYPE_ACCUMULATE)
    if goal_type not in (GOAL_TYPE_ACCUMULATE, GOAL_TYPE_REDUCE, GOAL_TYPE_DAILY):
        goal_type = GOAL_TYPE_ACCUMULATE
    daily_mode = str(raw.get("daily_mode") or DAILY_MODE_DO)
    if daily_mode not in (DAILY_MODE_DO, DAILY_MODE_AVOID):
        daily_mode = DAILY_MODE_DO
    return {
        **raw,
        "goal_type": goal_type,
        "baseline": float(raw.get("baseline") or 0.0),
        "unit": str(raw.get("unit") or "").strip(),
        "daily_mode": daily_mode,
        "target": (
            0.0
            if goal_type == GOAL_TYPE_DAILY and daily_mode == DAILY_MODE_AVOID
            else float(raw.get("target") or 0.0)
        ),
    }


def _days_in_month(month_key: str) -> int:
    parsed = parse_month_key(month_key)
    if not parsed:
        return 30
    year, month = parsed
    return calendar.monthrange(year, month)[1]


def _month_date_bounds(month_key: str) -> tuple[date, date] | None:
    parsed = parse_month_key(month_key)
    if not parsed:
        return None
    year, month = parsed
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def valid_log_date(month_key: str, log_date: date, *, today: date | None = None) -> bool:
    """Log date must fall in month and not be in the future."""
    today = today or date.today()
    bounds = _month_date_bounds(month_key)
    if not bounds:
        return False
    start, end = bounds
    if log_date < start or log_date > end:
        return False
    return log_date <= today


def daily_entry_is_good(daily_mode: str, entry: str) -> bool:
    entry = entry.lower()
    if daily_mode == DAILY_MODE_DO:
        return entry == DAILY_YES
    return entry == DAILY_NO


def daily_entry_is_bad(daily_mode: str, entry: str) -> bool:
    return not daily_entry_is_good(daily_mode, entry)


def _do_month_stats(
    entries: dict[str, str],
    month_key: str,
    on_date: date | None = None,
) -> tuple[int, int, int]:
    """Return (hit_days, miss_days, elapsed_days). Checked (1) counts as achievement."""
    on_date = on_date or date.today()
    bounds = _month_date_bounds(month_key)
    if not bounds:
        return 0, 0, 0
    start, end = bounds
    last = min(on_date, end)
    hits = misses = elapsed = 0
    d = start
    while d <= last:
        elapsed += 1
        iso = d.isoformat()
        if entries.get(iso) == DAILY_YES:
            hits += 1
        else:
            misses += 1
        d += timedelta(days=1)
    return hits, misses, elapsed


def _avoid_month_stats(
    entries: dict[str, str],
    month_key: str,
    on_date: date | None = None,
) -> tuple[int, int, int]:
    """Return (clean_days, slip_days, elapsed_days). Unchecked counts as clean."""
    on_date = on_date or date.today()
    bounds = _month_date_bounds(month_key)
    if not bounds:
        return 0, 0, 0
    start, end = bounds
    last = min(on_date, end)
    clean = slips = elapsed = 0
    d = start
    while d <= last:
        elapsed += 1
        iso = d.isoformat()
        if entries.get(iso) == DAILY_YES:
            slips += 1
        else:
            clean += 1
        d += timedelta(days=1)
    return clean, slips, elapsed


def summarize_daily_log(
    daily_mode: str,
    entries: dict[str, str],
    *,
    month_key: str | None = None,
    on_date: date | None = None,
) -> dict:
    """Summarize yes/no entries keyed by YYYY-MM-DD."""
    if daily_mode == DAILY_MODE_AVOID and month_key:
        clean, slips, elapsed = _avoid_month_stats(entries, month_key, on_date)
        return {
            "logged_days": len(entries),
            "good_days": clean,
            "bad_days": slips,
            "slips": slips,
            "hits": clean,
            "elapsed_days": elapsed,
        }

    if daily_mode == DAILY_MODE_DO and month_key:
        hits, misses, elapsed = _do_month_stats(entries, month_key, on_date)
        return {
            "logged_days": len(entries),
            "good_days": hits,
            "bad_days": misses,
            "slips": 0,
            "hits": hits,
            "elapsed_days": elapsed,
        }

    good = bad = 0
    for entry in entries.values():
        if daily_entry_is_good(daily_mode, entry):
            good += 1
        else:
            bad += 1
    return {
        "logged_days": good + bad,
        "good_days": good,
        "bad_days": bad,
        "slips": bad if daily_mode == DAILY_MODE_AVOID else 0,
        "hits": good if daily_mode == DAILY_MODE_DO else 0,
        "elapsed_days": good + bad,
    }


def goal_completion_for_type(
    goal: dict,
    progress_value: float,
    *,
    month_key: str,
    daily_entries: dict[str, str] | None = None,
    on_date: date | None = None,
) -> float:
    """Return completion percentage 0–100 for a single goal."""
    goal = normalize_goal(goal)
    goal_type = goal["goal_type"]
    target = max(float(goal["target"]), 0.0)

    if goal_type == GOAL_TYPE_REDUCE:
        baseline = float(goal["baseline"])
        if baseline <= target:
            return 100.0 if progress_value <= target else 0.0
        total_change = baseline - target
        achieved = baseline - progress_value
        if achieved <= 0:
            return 0.0
        return min(100.0, max(0.0, (achieved / total_change) * 100.0))

    if goal_type == GOAL_TYPE_DAILY:
        entries = daily_entries or {}
        summary = summarize_daily_log(
            goal["daily_mode"], entries, month_key=month_key, on_date=on_date
        )
        elapsed = summary["elapsed_days"]
        if elapsed <= 0:
            return 100.0
        return min(100.0, (summary["good_days"] / elapsed) * 100.0)

    return goal_completion_pct(progress_value, target)


def goal_progress_display(
    goal: dict,
    progress_value: float,
    *,
    month_key: str,
    daily_entries: dict[str, str] | None = None,
) -> str:
    """Human-readable progress line for UI / Telegram."""
    goal = normalize_goal(goal)

    if goal["goal_type"] == GOAL_TYPE_REDUCE:
        return f"{progress_value:.1f}"

    if goal["goal_type"] == GOAL_TYPE_DAILY:
        entries = daily_entries or {}
        summary = summarize_daily_log(
            goal["daily_mode"], entries, month_key=month_key
        )
        on_track = summary["good_days"]
        elapsed = summary["elapsed_days"]
        if goal["daily_mode"] == DAILY_MODE_AVOID:
            return f"{on_track}/{elapsed} clean"
        return f"{on_track}/{elapsed} done"

    return f"{progress_value:.2f} / {goal['target']:.2f}"


def goal_unit_caption(goal: dict) -> str | None:
    """Optional unit line shown below progress inputs."""
    unit = str(normalize_goal(goal).get("unit") or "").strip()
    return f"Unit: {unit}" if unit else None


def goal_target_hint(goal: dict) -> str:
    goal = normalize_goal(goal)
    if goal["goal_type"] == GOAL_TYPE_REDUCE:
        return f"Baseline {goal['baseline']:.1f} → target {goal['target']:.1f}"
    if goal["goal_type"] == GOAL_TYPE_DAILY:
        if goal["daily_mode"] == DAILY_MODE_DO:
            return "Checked = 1 · scored as on-track days / elapsed"
        return "Unchecked = 0 · scored as on-track days / elapsed"
    return f"Target: {goal['target']:.2f}"


def compute_streak(
    daily_mode: str,
    entries: dict[str, str],
    *,
    through: date,
    month_key: str | None = None,
) -> int:
    """Consecutive good days ending on `through` (walk backward)."""
    month_start = through.replace(day=1)
    if month_key:
        bounds = _month_date_bounds(month_key)
        if bounds:
            month_start = bounds[0]

    streak = 0
    d = through
    while d >= month_start:
        key = d.isoformat()
        if daily_mode == DAILY_MODE_AVOID:
            if entries.get(key) == DAILY_YES:
                break
            streak += 1
        elif key in entries and daily_entry_is_good(daily_mode, entries[key]):
            streak += 1
        else:
            break
        d -= timedelta(days=1)
    return streak


def weighted_score_typed(
    goals: list[dict],
    progress_by_id: dict[str, float],
    *,
    month_key: str,
    daily_logs_by_goal: dict[str, dict[str, str]] | None = None,
    on_date: date | None = None,
) -> tuple[float, float]:
    """Return (earned_weighted_score, total_weightage) using goal types."""
    daily_logs_by_goal = daily_logs_by_goal or {}
    total_weight = sum(g["weightage"] for g in goals)
    if total_weight <= 0:
        return 0.0, 0.0
    earned = 0.0
    for g in goals:
        gid = g["id"]
        pct = goal_completion_for_type(
            g,
            progress_by_id.get(gid, 0.0),
            month_key=month_key,
            daily_entries=daily_logs_by_goal.get(gid),
            on_date=on_date,
        )
        earned += (pct / 100.0) * g["weightage"]
    return earned, total_weight
