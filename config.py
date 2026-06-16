"""Paths and helpers for monthly IKR goals and progress."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import date, datetime
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
IKRR_DB_PATH = PACKAGE_DIR / "ikr.db"


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


# In-app background scheduler (local machine time)
TELEGRAM_POLL_INTERVAL_SECONDS = 60
DAILY_REMINDER_HOUR = 11
DAILY_REMINDER_MINUTE = 30
SCHEDULER_DAILY_REMINDER_META_KEY = "scheduler_daily_reminder_date"


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
