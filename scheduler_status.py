"""Scheduler status for admin dashboard."""

from __future__ import annotations

from datetime import datetime

from auth import get_app_meta, list_telegram_notification_users, list_users
from config import SCHEDULER_DAILY_REMINDER_META_KEY, SCHEDULER_LAST_POLL_META_KEY
from notifiers.telegram_core import fetch_bot_info, resolve_bot_token
from reminder_settings import get_reminder_settings


def get_scheduler_status() -> dict:
    settings = get_reminder_settings()
    token_ok = bool(resolve_bot_token())
    bot = fetch_bot_info() if token_ok else None
    tg_users = list_telegram_notification_users()
    last_poll = get_app_meta(SCHEDULER_LAST_POLL_META_KEY) or "Never"
    last_daily = get_app_meta(SCHEDULER_DAILY_REMINDER_META_KEY) or "Never"

    tz = settings.get("timezone") or "System local"
    rh, rm = settings["reminder_hour"], settings["reminder_minute"]
    next_reminder = f"Daily at {rh:02d}:{rm:02d} ({tz})"

    return {
        "telegram_configured": token_ok,
        "bot_username": (bot or {}).get("username", ""),
        "last_poll_at": last_poll,
        "last_daily_reminder_date": last_daily,
        "next_daily_reminder": next_reminder,
        "poll_interval_seconds": settings["poll_interval_seconds"],
        "reminders_enabled": settings["reminders_enabled"],
        "evening_nudge_enabled": settings["evening_nudge_enabled"],
        "mid_month_enabled": settings["mid_month_enabled"],
        "end_month_enabled": settings["end_month_enabled"],
        "timezone": tz,
        "telegram_user_count": len(tg_users),
        "total_users": len(list_users()),
        "checked_at": datetime.now().isoformat(timespec="seconds"),
    }
