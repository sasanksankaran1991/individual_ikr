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
TELEGRAM_POLL_INTERVAL_SECONDS = 120
STREAMLIT_MIN_POLL_INTERVAL_SECONDS = 30
DAILY_REMINDER_HOUR = 11
DAILY_REMINDER_MINUTE = 30
EVENING_NUDGE_HOUR = 18
EVENING_NUDGE_MINUTE = 0
MID_MONTH_REMINDER_DAY = 15
DEFAULT_TIMEZONE = "Asia/Kolkata"
DEFAULT_SESSION_TIMEOUT_MINUTES = 7200  # 5 days
AUTH_SESSION_DAYS = 5
AUTH_SESSION_COOKIE = "ikr_auth"
DEFAULT_CLOUD_TICK_INTERVAL_MINUTES = 180
# Deploy one-time: bash scripts/gcp/bootstrap.sh  (grants runner SA cloudscheduler.admin)
# After code changes: build + deploy.sh, then Admin → Save settings once (syncs schedulers).
CLOUD_SCHEDULER_WAKE_MINUTES = 30
CLOUD_TICK_INTERVAL_OPTIONS: dict[int, str] = {
    30: "30 minutes",
    60: "1 hour",
    180: "3 hours",
    360: "6 hours",
}
SCHEDULER_DAILY_REMINDER_META_KEY = "scheduler_daily_reminder_date"
SCHEDULER_LAST_POLL_META_KEY = "scheduler_last_poll_at"

# Goal types
GOAL_TYPE_ACCUMULATE = "accumulate"
GOAL_TYPE_REDUCE = "reduce"
GOAL_TYPE_DAILY = "daily"
DAILY_MODE_DO = "do"
DAILY_MODE_AVOID = "avoid"


def new_goal_id() -> str:
    return str(uuid.uuid4())


def new_user_id() -> str:
    return str(uuid.uuid4())


def goal_completion_pct(progress: float, target: float) -> float:
    if target <= 0:
        return 100.0 if progress > 0 else 0.0
    return min(100.0, (progress / target) * 100.0)


def weighted_score(
    goals: list[dict],
    progress_by_id: dict[str, float],
    *,
    month_key: str | None = None,
    daily_logs_by_goal: dict[str, dict[str, str]] | None = None,
    on_date=None,
) -> tuple[float, float]:
    """Return (earned_weighted_score, total_weightage)."""
    if month_key is not None:
        from goal_scoring import weighted_score_typed

        return weighted_score_typed(
            goals,
            progress_by_id,
            month_key=month_key,
            daily_logs_by_goal=daily_logs_by_goal,
            on_date=on_date,
        )
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


# Grace period in the *following* month for editing a closed month.
CONFIG_EDIT_GRACE_DAY = 15   # goals editable through this day (e.g. May → through 15 Jun)
PROGRESS_EDIT_GRACE_DAY = 10  # progress editable through this day (e.g. May → through 10 Jun)
PROGRESS_LOCK_WARNING_DAYS = 2  # remind when this many days remain before progress lock


def previous_month_key(on_date: date | None = None) -> str | None:
    on_date = on_date or date.today()
    if on_date.month == 1:
        return month_key(on_date.year - 1, 12)
    return month_key(on_date.year, on_date.month - 1)


def progress_lock_days_remaining(month_key: str, on_date: date | None = None) -> int | None:
    """Days until progress lock (0 = last editable day). None if already locked."""
    on_date = on_date or date.today()
    deadline = progress_edit_deadline(month_key)
    if not deadline or on_date > deadline:
        return None
    return (deadline - on_date).days


def _month_after(month_key: str) -> tuple[int, int] | None:
    parsed = parse_month_key(month_key)
    if not parsed:
        return None
    year, month = parsed
    if month == 12:
        return year + 1, 1
    return year, month + 1


def config_edit_deadline(month_key: str) -> date | None:
    """Last calendar day (inclusive) goals for `month_key` may be created or changed."""
    from reminder_settings import get_config_edit_grace_day

    nxt = _month_after(month_key)
    if not nxt:
        return None
    year, month = nxt
    return date(year, month, get_config_edit_grace_day())


def progress_edit_deadline(month_key: str) -> date | None:
    """Last calendar day (inclusive) progress for `month_key` may be updated."""
    from reminder_settings import get_progress_edit_grace_day

    nxt = _month_after(month_key)
    if not nxt:
        return None
    year, month = nxt
    return date(year, month, get_progress_edit_grace_day())


def is_config_editable(month_key: str, on_date: date | None = None) -> bool:
    on_date = on_date or date.today()
    deadline = config_edit_deadline(month_key)
    if deadline is None:
        return True
    return on_date <= deadline


def is_progress_editable(month_key: str, on_date: date | None = None) -> bool:
    on_date = on_date or date.today()
    deadline = progress_edit_deadline(month_key)
    if deadline is None:
        return True
    return on_date <= deadline


def config_edit_status(month_key: str, on_date: date | None = None) -> tuple[bool, str]:
    if is_config_editable(month_key, on_date):
        return True, ""
    deadline = config_edit_deadline(month_key)
    label = format_month_label(month_key)
    if deadline:
        return False, (
            f"Goals for {label} are locked after "
            f"{deadline.strftime('%d %b %Y')}. View only."
        )
    return False, f"Goals for {label} are locked."


def progress_edit_status(month_key: str, on_date: date | None = None) -> tuple[bool, str]:
    if is_progress_editable(month_key, on_date):
        return True, ""
    deadline = progress_edit_deadline(month_key)
    label = format_month_label(month_key)
    if deadline:
        return False, (
            f"Progress for {label} is locked after "
            f"{deadline.strftime('%d %b %Y')}. View only."
        )
    return False, f"Progress for {label} is locked."
