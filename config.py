"""Paths and helpers for monthly IKR goals and progress."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import date, datetime
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
IKRR_DB_PATH = PACKAGE_DIR / "ikr.db"

# Default Streamlit port (uncommon — avoids clash with 8501 / other apps)
APP_PORT = 18501


def ensure_db_file() -> None:
    """Create ikr.db and parent folder on first run; quarantine unreadable files."""
    IKRR_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not IKRR_DB_PATH.is_file():
        return
    try:
        conn = sqlite3.connect(IKRR_DB_PATH)
        try:
            conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = IKRR_DB_PATH.with_name(f"{IKRR_DB_PATH.stem}.corrupt_{stamp}.db")
        try:
            IKRR_DB_PATH.rename(backup)
        except OSError:
            IKRR_DB_PATH.unlink(missing_ok=True)


# Legacy JSON paths (imported once into SQLite if present).
GOALS_CONFIG_PATH = PACKAGE_DIR / "goals_config.json"
PROGRESS_PATH = PACKAGE_DIR / "progress.json"

MONTH_NAMES = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def month_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def parse_month_key(key: str) -> tuple[int, int] | None:
    try:
        year_s, month_s = key.split("-", 1)
        year, month = int(year_s), int(month_s)
        if 1 <= month <= 12:
            return year, month
    except (ValueError, AttributeError):
        pass
    return None


def format_month_label(key: str) -> str:
    parsed = parse_month_key(key)
    if not parsed:
        return key
    year, month = parsed
    return f"{MONTH_NAMES[month - 1]} {year}"


def current_month_key() -> str:
    today = date.today()
    return month_key(today.year, today.month)


# In-app background scheduler defaults (overridden in admin Settings)
TELEGRAM_POLL_INTERVAL_SECONDS = 60
DAILY_REMINDER_HOUR = 11
DAILY_REMINDER_MINUTE = 30
EVENING_NUDGE_HOUR = 18
EVENING_NUDGE_MINUTE = 0
MID_MONTH_REMINDER_DAY = 15
DEFAULT_TIMEZONE = ""
DEFAULT_SESSION_TIMEOUT_MINUTES = 480
SCHEDULER_DAILY_REMINDER_META_KEY = "scheduler_daily_reminder_date"
SCHEDULER_LAST_POLL_META_KEY = "scheduler_last_poll_at"


def new_goal_id() -> str:
    return str(uuid.uuid4())


def new_user_id() -> str:
    return str(uuid.uuid4())


def goal_completion_pct(progress: float, target: float) -> float:
    if target <= 0:
        return 100.0 if progress > 0 else 0.0
    return min(100.0, (progress / target) * 100.0)


def weighted_score(goals: list[dict], progress_by_id: dict[str, float]) -> tuple[float, float]:
    """Return (earned_weighted_score, total_weightage)."""
    total_weight = sum(g["weightage"] for g in goals)
    if total_weight <= 0:
        return 0.0, 0.0
    earned = 0.0
    for g in goals:
        pct = goal_completion_pct(progress_by_id.get(g["id"], 0.0), g["target"])
        earned += (pct / 100.0) * g["weightage"]
    return earned, total_weight


def month_pace_fraction(month_key: str, on_date: date | None = None) -> float:
    """Expected fraction of month elapsed (0–1) for pace tracking."""
    import calendar

    on_date = on_date or date.today()
    parsed = parse_month_key(month_key)
    if not parsed:
        return 1.0
    year, month = parsed
    days_in_month = calendar.monthrange(year, month)[1]
    month_start = date(year, month, 1)
    month_end = date(year, month, days_in_month)
    if on_date < month_start:
        return 0.0
    if on_date > month_end:
        return 1.0
    return min(1.0, on_date.day / days_in_month)


def pace_status(completion_pct: float, month_key: str, on_date: date | None = None) -> tuple[str, str]:
    """Return (label, css_class) — Ahead / On track / Behind."""
    expected_pct = month_pace_fraction(month_key, on_date) * 100.0
    diff = completion_pct - expected_pct
    if diff >= 5.0:
        return "Ahead", "ikr-pill-ahead"
    if diff <= -5.0:
        return "Behind", "ikr-pill-behind"
    return "On track", "ikr-pill-track"


def pace_info(
    completion_pct: float, month_key: str, on_date: date | None = None
) -> dict:
    """Ahead/behind details for UI highlights."""
    expected_pct = month_pace_fraction(month_key, on_date) * 100.0
    diff = completion_pct - expected_pct
    label, pill_class = pace_status(completion_pct, month_key, on_date)
    if diff >= 5.0:
        tone = "ahead"
    elif diff <= -5.0:
        tone = "behind"
    else:
        tone = "track"
    return {
        "label": label,
        "pill_class": pill_class,
        "banner_class": f"ikr-pace-banner-{tone}",
        "tone": tone,
        "completion_pct": completion_pct,
        "expected_pct": expected_pct,
        "diff": diff,
    }


def is_last_day_of_month(on_date: date | None = None) -> bool:
    import calendar

    on_date = on_date or date.today()
    return on_date.day == calendar.monthrange(on_date.year, on_date.month)[1]
