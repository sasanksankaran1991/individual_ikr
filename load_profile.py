"""Measure load times for common IKR operations."""

from __future__ import annotations

import time
from dataclasses import dataclass

from config import current_month_key, is_progress_editable
from data import (
    fetch_daily_log,
    fetch_month_goals,
    fetch_month_progress,
    fetch_month_summary,
    init_db,
    list_configured_months,
)
from month_history import build_month_record, load_history_records


@dataclass
class TimingRow:
    label: str
    ms: float
    detail: str = ""


def _ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0


def benchmark_user_load(user_id: str) -> list[TimingRow]:
    """Run timed probes for the current user's typical data loads."""
    rows: list[TimingRow] = []

    t0 = time.perf_counter()
    init_db()
    rows.append(TimingRow("Database init", _ms(t0), "SQLite tables + migrations"))

    t0 = time.perf_counter()
    months = list_configured_months(user_id)
    rows.append(
        TimingRow(
            "List configured months",
            _ms(t0),
            f"{len(months)} month(s)",
        )
    )

    if not months:
        return rows

    editable = [m for m in months if is_progress_editable(m)]
    locked = [m for m in months if not is_progress_editable(m)]

    t0 = time.perf_counter()
    for mk in locked:
        fetch_month_summary(user_id, mk)
    rows.append(
        TimingRow(
            "History: read locked snapshots",
            _ms(t0),
            f"{len(locked)} month(s) from month_summary table",
        )
    )

    if editable:
        t0 = time.perf_counter()
        for mk in editable:
            build_month_record(user_id, mk)
        rows.append(
            TimingRow(
                "History: live-calc editable months",
                _ms(t0),
                f"{len(editable)} month(s) — goals + progress + daily_log + scoring",
            )
        )

    t0 = time.perf_counter()
    load_history_records(user_id)
    rows.append(
        TimingRow(
            "History tab (full load)",
            _ms(t0),
            "Snapshots for locked months + live calc for current/grace",
        )
    )

    current = current_month_key()
    if current in months:
        t0 = time.perf_counter()
        fetch_month_goals(user_id, current)
        fetch_month_progress(user_id, current)
        fetch_daily_log(user_id, current)
        rows.append(
            TimingRow(
                "Progress tab: fetch month data",
                _ms(t0),
                f"Goals, progress, daily_log for {current}",
            )
        )

        t0 = time.perf_counter()
        build_month_record(user_id, current)
        rows.append(
            TimingRow(
                "Progress tab: score current month",
                _ms(t0),
                "Weighted score + per-goal completion",
            )
        )

    try:
        from scheduler_status import get_scheduler_status

        t0 = time.perf_counter()
        get_scheduler_status()
        rows.append(TimingRow("Admin: scheduler status", _ms(t0), "Background poll state"))
    except Exception as exc:
        rows.append(TimingRow("Admin: scheduler status", 0.0, f"Skipped: {exc}"))

    return rows
