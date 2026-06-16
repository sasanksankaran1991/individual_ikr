"""Admin-configurable reminder and Telegram poll settings (stored in app_meta)."""

from __future__ import annotations

from auth import get_app_meta, set_app_meta
from config import (
    DAILY_REMINDER_HOUR,
    DAILY_REMINDER_MINUTE,
    TELEGRAM_POLL_INTERVAL_SECONDS,
)

META_REMINDER_HOUR = "settings_reminder_hour"
META_REMINDER_MINUTE = "settings_reminder_minute"
META_POLL_INTERVAL = "settings_telegram_poll_interval_seconds"
META_REMINDERS_ENABLED = "settings_reminders_enabled"

MIN_POLL_INTERVAL = 30
MAX_POLL_INTERVAL = 600


def get_reminder_settings() -> dict:
    """Return current scheduler settings (DB overrides with config.py defaults)."""
    hour_raw = get_app_meta(META_REMINDER_HOUR)
    minute_raw = get_app_meta(META_REMINDER_MINUTE)
    interval_raw = get_app_meta(META_POLL_INTERVAL)
    enabled_raw = get_app_meta(META_REMINDERS_ENABLED)

    return {
        "reminder_hour": int(hour_raw) if hour_raw and hour_raw.isdigit() else DAILY_REMINDER_HOUR,
        "reminder_minute": (
            int(minute_raw) if minute_raw and minute_raw.isdigit() else DAILY_REMINDER_MINUTE
        ),
        "poll_interval_seconds": (
            int(interval_raw)
            if interval_raw and interval_raw.isdigit()
            else TELEGRAM_POLL_INTERVAL_SECONDS
        ),
        "reminders_enabled": enabled_raw != "0",
    }


def save_reminder_settings(
    *,
    reminder_hour: int,
    reminder_minute: int,
    poll_interval_seconds: int,
    reminders_enabled: bool,
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

    set_app_meta(META_REMINDER_HOUR, str(reminder_hour))
    set_app_meta(META_REMINDER_MINUTE, str(reminder_minute))
    set_app_meta(META_POLL_INTERVAL, str(poll_interval_seconds))
    set_app_meta(META_REMINDERS_ENABLED, "1" if reminders_enabled else "0")
    return True, "Reminder settings saved."
