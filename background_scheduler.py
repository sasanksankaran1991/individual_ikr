"""In-app Telegram polling and scheduled reminders."""

from __future__ import annotations

from datetime import datetime

from auth import get_app_meta, set_app_meta
from config import (
    MID_MONTH_REMINDER_DAY,
    PROGRESS_LOCK_WARNING_DAYS,
    SCHEDULER_DAILY_REMINDER_META_KEY,
    SCHEDULER_LAST_POLL_META_KEY,
    is_last_day_of_month,
    previous_month_key,
    progress_lock_days_remaining,
)
from data import init_db
from notifications import (
    process_daily_reminders,
    process_end_month_reports,
    process_evening_nudges,
    process_mid_month_reports,
    process_progress_lock_reminders,
)
from reminder_settings import get_reminder_settings
from telegram_inbound import process_all_inbound_updates


def scheduler_now() -> datetime:
    settings = get_reminder_settings()
    tz_name = (settings.get("timezone") or "").strip()
    if tz_name:
        try:
            from zoneinfo import ZoneInfo

            return datetime.now(ZoneInfo(tz_name))
        except Exception:
            pass
    return datetime.now()


def _is_scheduled_time_reached(now: datetime, hour: int, minute: int) -> bool:
    """True once today's scheduled local time has passed (works with sparse Cloud Scheduler ticks)."""
    from datetime import time as dt_time

    due = datetime.combine(now.date(), dt_time(hour, minute))
    if now.tzinfo is not None:
        due = due.replace(tzinfo=now.tzinfo)
    return now >= due


def _should_run_daily_reminders(now: datetime) -> bool:
    settings = get_reminder_settings()
    if not settings["reminders_enabled"]:
        return False
    today = now.date().isoformat()
    if get_app_meta(SCHEDULER_DAILY_REMINDER_META_KEY) == today:
        return False
    return _is_scheduled_time_reached(
        now, settings["reminder_hour"], settings["reminder_minute"]
    )


def _should_run_evening_nudge(now: datetime) -> bool:
    settings = get_reminder_settings()
    if not settings["evening_nudge_enabled"]:
        return False
    today = now.date().isoformat()
    if get_app_meta("scheduler_evening_nudge_date") == today:
        return False
    return _is_scheduled_time_reached(
        now, settings["evening_nudge_hour"], settings["evening_nudge_minute"]
    )


def _should_run_mid_month(now: datetime) -> bool:
    settings = get_reminder_settings()
    if not settings["mid_month_enabled"]:
        return False
    if now.day != MID_MONTH_REMINDER_DAY:
        return False
    today = now.date().isoformat()
    if get_app_meta("scheduler_mid_month_date") == today:
        return False
    return _is_scheduled_time_reached(
        now, settings["reminder_hour"], settings["reminder_minute"]
    )


def _should_run_end_month(now: datetime) -> bool:
    settings = get_reminder_settings()
    if not settings["end_month_enabled"]:
        return False
    if not is_last_day_of_month(now.date()):
        return False
    today = now.date().isoformat()
    if get_app_meta("scheduler_end_month_date") == today:
        return False
    return _is_scheduled_time_reached(
        now, settings["reminder_hour"], settings["reminder_minute"]
    )


def _should_run_progress_lock_warning(now: datetime) -> bool:
    settings = get_reminder_settings()
    if not settings["reminders_enabled"]:
        return False
    closing_month = previous_month_key(now.date())
    if not closing_month:
        return False
    days_left = progress_lock_days_remaining(closing_month, now.date())
    if days_left is None or days_left > PROGRESS_LOCK_WARNING_DAYS:
        return False
    today = now.date().isoformat()
    meta_key = f"scheduler_progress_lock_{closing_month}_{today}"
    if get_app_meta(meta_key) == "1":
        return False
    return _is_scheduled_time_reached(
        now, settings["reminder_hour"], settings["reminder_minute"]
    )


def run_background_tick() -> dict:
    """Poll Telegram; run scheduled reminders when due."""
    init_db()
    now = scheduler_now()
    set_app_meta(SCHEDULER_LAST_POLL_META_KEY, now.isoformat(timespec="seconds"))

    inbound_results, inbound_err = process_all_inbound_updates()
    if inbound_err:
        set_app_meta("telegram_last_error", inbound_err)
    else:
        set_app_meta("telegram_last_error", "")

    reminder_results: list[dict] = []
    # Skip scheduled reminders in the same tick as user commands (avoids extra messages).
    user_just_messaged = any(r.get("type") == "command" for r in inbound_results)
    if user_just_messaged:
        return {
            "at": now.isoformat(timespec="seconds"),
            "inbound_count": len(inbound_results),
            "inbound_error": inbound_err,
            "reminder_results": reminder_results,
        }

    if _should_run_daily_reminders(now):
        reminder_results.extend(process_daily_reminders())
        set_app_meta(SCHEDULER_DAILY_REMINDER_META_KEY, now.date().isoformat())
    if _should_run_progress_lock_warning(now):
        closing_month = previous_month_key(now.date())
        reminder_results.extend(process_progress_lock_reminders())
        if closing_month:
            set_app_meta(
                f"scheduler_progress_lock_{closing_month}_{now.date().isoformat()}",
                "1",
            )
    if _should_run_evening_nudge(now):
        reminder_results.extend(process_evening_nudges())
        set_app_meta("scheduler_evening_nudge_date", now.date().isoformat())
    if _should_run_mid_month(now):
        reminder_results.extend(process_mid_month_reports())
        set_app_meta("scheduler_mid_month_date", now.date().isoformat())
    if _should_run_end_month(now):
        reminder_results.extend(process_end_month_reports())
        set_app_meta("scheduler_end_month_date", now.date().isoformat())

    return {
        "at": now.isoformat(timespec="seconds"),
        "inbound_count": len(inbound_results),
        "inbound_error": inbound_err,
        "reminder_results": reminder_results,
    }
