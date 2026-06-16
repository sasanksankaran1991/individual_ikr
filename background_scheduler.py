"""In-app Telegram polling and scheduled daily reminders."""

from __future__ import annotations

from datetime import datetime

from auth import get_app_meta, set_app_meta
from data import init_db
from notifications import process_daily_reminders
from reminder_settings import get_reminder_settings
from telegram_inbound import process_all_inbound_updates


def _should_run_daily_reminders(now: datetime) -> bool:
    """True once per day during the configured hour window (local clock)."""
    settings = get_reminder_settings()
    if not settings["reminders_enabled"]:
        return False

    today = now.date().isoformat()
    if get_app_meta("scheduler_daily_reminder_date") == today:
        return False

    hour = settings["reminder_hour"]
    minute = settings["reminder_minute"]
    return now.hour == hour and now.minute >= minute


def run_background_tick() -> dict:
    """
    Poll Telegram for inbound messages; send daily reminders at 11:30 AM local time.

    Safe to call every minute while the Streamlit app is running.
    Reminders run at most once per calendar day (tracked in app_meta).
    """
    init_db()
    now = datetime.now()

    inbound_results, inbound_err = process_all_inbound_updates()

    reminder_results: list[dict] = []
    reminders_ran = False
    if _should_run_daily_reminders(now):
        reminder_results = process_daily_reminders()
        set_app_meta(SCHEDULER_DAILY_REMINDER_META_KEY, now.date().isoformat())
        reminders_ran = True

    return {
        "at": now.isoformat(timespec="seconds"),
        "inbound_count": len(inbound_results),
        "inbound_error": inbound_err,
        "reminders_ran": reminders_ran,
        "reminder_results": reminder_results,
    }
