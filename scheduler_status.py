"""Scheduler status for admin dashboard."""

from __future__ import annotations

from datetime import datetime

from auth import get_app_meta, list_telegram_notification_users, list_users, set_app_meta
from config import CLOUD_TICK_INTERVAL_OPTIONS, SCHEDULER_DAILY_REMINDER_META_KEY
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

    tz = settings.get("timezone") or "System local"
    rh, rm = settings["reminder_hour"], settings["reminder_minute"]
    next_reminder = f"Daily at {rh:02d}:{rm:02d} ({tz})"

    interval_min = settings["cloud_tick_interval_minutes"]
    return {
        "telegram_configured": token_ok,
        "bot_username": _cached_bot_username() if token_ok else "",
        "last_poll_at": last_poll,
        "last_daily_reminder_date": last_daily,
        "next_daily_reminder": next_reminder,
        "poll_interval_seconds": settings["poll_interval_seconds"],
        "cloud_tick_interval_minutes": interval_min,
        "cloud_tick_interval_label": CLOUD_TICK_INTERVAL_OPTIONS.get(
            interval_min, f"{interval_min} min"
        ),
        "reminders_enabled": settings["reminders_enabled"],
        "evening_nudge_enabled": settings["evening_nudge_enabled"],
        "mid_month_enabled": settings["mid_month_enabled"],
        "end_month_enabled": settings["end_month_enabled"],
        "timezone": tz,
        "telegram_user_count": len(tg_users),
        "total_users": len(list_users()),
        "last_telegram_error": get_app_meta("telegram_last_error") or "",
        "checked_at": datetime.now().isoformat(timespec="seconds"),
    }
