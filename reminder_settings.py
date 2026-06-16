"""Admin-configurable reminder, session, and scheduler settings (app_meta)."""

from __future__ import annotations

from auth import get_app_meta, set_app_meta
from config import (
    DAILY_REMINDER_HOUR,
    DAILY_REMINDER_MINUTE,
    DEFAULT_SESSION_TIMEOUT_MINUTES,
    DEFAULT_TIMEZONE,
    EVENING_NUDGE_HOUR,
    EVENING_NUDGE_MINUTE,
    TELEGRAM_POLL_INTERVAL_SECONDS,
)

META_REMINDER_HOUR = "settings_reminder_hour"
META_REMINDER_MINUTE = "settings_reminder_minute"
META_POLL_INTERVAL = "settings_telegram_poll_interval_seconds"
META_REMINDERS_ENABLED = "settings_reminders_enabled"
META_TIMEZONE = "settings_timezone"
META_EVENING_ENABLED = "settings_evening_nudge_enabled"
META_EVENING_HOUR = "settings_evening_nudge_hour"
META_EVENING_MINUTE = "settings_evening_nudge_minute"
META_MID_MONTH_ENABLED = "settings_mid_month_enabled"
META_END_MONTH_ENABLED = "settings_end_month_enabled"
META_SESSION_TIMEOUT = "settings_session_timeout_minutes"
META_ALLOW_UNEQUAL_WEIGHT = "settings_allow_unequal_weightage"

MIN_POLL_INTERVAL = 30
MAX_POLL_INTERVAL = 600

COMMON_TIMEZONES = [
    "",
    "UTC",
    "Asia/Kolkata",
    "Asia/Dubai",
    "Asia/Singapore",
    "Europe/London",
    "Europe/Berlin",
    "America/New_York",
    "America/Chicago",
    "America/Los_Angeles",
]


def _int_meta(key: str, default: int) -> int:
    raw = get_app_meta(key)
    return int(raw) if raw and raw.isdigit() else default


def _bool_meta(key: str, *, default: bool = True) -> bool:
    raw = get_app_meta(key)
    if raw is None:
        return default
    return raw != "0"


def get_reminder_settings() -> dict:
    return {
        "reminder_hour": _int_meta(META_REMINDER_HOUR, DAILY_REMINDER_HOUR),
        "reminder_minute": _int_meta(META_REMINDER_MINUTE, DAILY_REMINDER_MINUTE),
        "poll_interval_seconds": _int_meta(META_POLL_INTERVAL, TELEGRAM_POLL_INTERVAL_SECONDS),
        "reminders_enabled": _bool_meta(META_REMINDERS_ENABLED, default=True),
        "timezone": get_app_meta(META_TIMEZONE) or DEFAULT_TIMEZONE,
        "evening_nudge_enabled": _bool_meta(META_EVENING_ENABLED, default=False),
        "evening_nudge_hour": _int_meta(META_EVENING_HOUR, EVENING_NUDGE_HOUR),
        "evening_nudge_minute": _int_meta(META_EVENING_MINUTE, EVENING_NUDGE_MINUTE),
        "mid_month_enabled": _bool_meta(META_MID_MONTH_ENABLED, default=True),
        "end_month_enabled": _bool_meta(META_END_MONTH_ENABLED, default=True),
        "session_timeout_minutes": _int_meta(META_SESSION_TIMEOUT, DEFAULT_SESSION_TIMEOUT_MINUTES),
        "allow_unequal_weightage": _bool_meta(META_ALLOW_UNEQUAL_WEIGHT, default=False),
    }


def get_session_timeout_minutes() -> int:
    return max(5, get_reminder_settings()["session_timeout_minutes"])


def allow_unequal_weightage() -> bool:
    return get_reminder_settings()["allow_unequal_weightage"]


def save_reminder_settings(
    *,
    reminder_hour: int,
    reminder_minute: int,
    poll_interval_seconds: int,
    reminders_enabled: bool,
    timezone: str = "",
    evening_nudge_enabled: bool = False,
    evening_nudge_hour: int = EVENING_NUDGE_HOUR,
    evening_nudge_minute: int = EVENING_NUDGE_MINUTE,
    mid_month_enabled: bool = True,
    end_month_enabled: bool = True,
    session_timeout_minutes: int = DEFAULT_SESSION_TIMEOUT_MINUTES,
    allow_unequal_weightage: bool = False,
) -> tuple[bool, str]:
    if not 0 <= reminder_hour <= 23:
        return False, "Reminder hour must be between 0 and 23."
    if not 0 <= reminder_minute <= 59:
        return False, "Reminder minute must be between 0 and 59."
    if not MIN_POLL_INTERVAL <= poll_interval_seconds <= MAX_POLL_INTERVAL:
        return False, (
            f"Telegram poll interval must be between "
            f"{MIN_POLL_INTERVAL} and {MAX_POLL_INTERVAL} seconds."
        )
    if not 0 <= evening_nudge_hour <= 23:
        return False, "Evening nudge hour must be between 0 and 23."
    if not 0 <= evening_nudge_minute <= 59:
        return False, "Evening nudge minute must be between 0 and 59."
    if not 5 <= session_timeout_minutes <= 10080:
        return False, "Session timeout must be between 5 and 10080 minutes (7 days)."

    tz = timezone.strip()
    if tz:
        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(tz)
        except Exception:
            return False, f"Invalid timezone: {tz!r}"

    set_app_meta(META_REMINDER_HOUR, str(reminder_hour))
    set_app_meta(META_REMINDER_MINUTE, str(reminder_minute))
    set_app_meta(META_POLL_INTERVAL, str(poll_interval_seconds))
    set_app_meta(META_REMINDERS_ENABLED, "1" if reminders_enabled else "0")
    set_app_meta(META_TIMEZONE, tz)
    set_app_meta(META_EVENING_ENABLED, "1" if evening_nudge_enabled else "0")
    set_app_meta(META_EVENING_HOUR, str(evening_nudge_hour))
    set_app_meta(META_EVENING_MINUTE, str(evening_nudge_minute))
    set_app_meta(META_MID_MONTH_ENABLED, "1" if mid_month_enabled else "0")
    set_app_meta(META_END_MONTH_ENABLED, "1" if end_month_enabled else "0")
    set_app_meta(META_SESSION_TIMEOUT, str(session_timeout_minutes))
    set_app_meta(META_ALLOW_UNEQUAL_WEIGHT, "1" if allow_unequal_weightage else "0")
    return True, "Settings saved."
