"""Scheduler status for admin dashboard."""

from __future__ import annotations

from datetime import datetime

from auth import get_app_meta, list_telegram_notification_users, list_users, set_app_meta
from auth import get_app_meta
from cloud_scheduler_sync import (
    DEFAULT_CLOUD_TZ,
    META_SYNC_AT,
    META_SYNC_DETAIL,
    META_SYNC_ERROR,
    TELEGRAM_POLL_CRON,
    describe_cloud_schedulers,
)
from config import SCHEDULER_DAILY_REMINDER_META_KEY
from notifiers.telegram_core import fetch_bot_info, resolve_bot_token
from reminder_settings import get_reminder_settings
from scheduler_state_store import read_last_poll_at

META_BOT_USERNAME = "telegram_bot_username"


def _cached_bot_username() -> str:
    """Avoid blocking the UI on every render; refresh at most once per hour."""
    cached = (get_app_meta(META_BOT_USERNAME) or "").strip()
    if cached:
        return cached
    if not resolve_bot_token():
        return ""
    bot = fetch_bot_info()
    username = (bot or {}).get("username", "")
    if username:
        set_app_meta(META_BOT_USERNAME, username)
    return username or ""


def get_scheduler_status() -> dict:
    settings = get_reminder_settings()
    token_ok = bool(resolve_bot_token())
    tg_users = list_telegram_notification_users()
    last_poll_dt = read_last_poll_at()
    last_poll = last_poll_dt.isoformat(timespec="seconds") if last_poll_dt else "Never"
    last_daily = get_app_meta(SCHEDULER_DAILY_REMINDER_META_KEY) or "Never"

    tz = settings.get("timezone") or DEFAULT_CLOUD_TZ
    rh, rm = settings["reminder_hour"], settings["reminder_minute"]
    eh, em = settings["evening_nudge_hour"], settings["evening_nudge_minute"]

    return {
        "telegram_configured": token_ok,
        "bot_username": _cached_bot_username() if token_ok else "",
        "last_poll_at": last_poll,
        "last_daily_reminder_date": last_daily,
        "telegram_poll_cron": TELEGRAM_POLL_CRON,
        "morning_reminder_at": f"{rh:02d}:{rm:02d} {tz}",
        "evening_nudge_at": f"{eh:02d}:{em:02d} {tz}",
        "poll_interval_seconds": settings["poll_interval_seconds"],
        "reminders_enabled": settings["reminders_enabled"],
        "evening_nudge_enabled": settings["evening_nudge_enabled"],
        "mid_month_enabled": settings["mid_month_enabled"],
        "end_month_enabled": settings["end_month_enabled"],
        "timezone": tz,
        "telegram_user_count": len(tg_users),
        "total_users": len(list_users()),
        "last_telegram_error": get_app_meta("telegram_last_error") or "",
        "cloud_scheduler_sync_at": get_app_meta(META_SYNC_AT) or "Never",
        "cloud_scheduler_sync_error": get_app_meta(META_SYNC_ERROR) or "",
        "cloud_scheduler_sync_detail": get_app_meta(META_SYNC_DETAIL) or "",
        "cloud_schedulers": describe_cloud_schedulers(),
        "checked_at": datetime.now().isoformat(timespec="seconds"),
    }
