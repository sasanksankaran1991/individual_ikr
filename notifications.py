"""Telegram notifications and reminder logic."""

from __future__ import annotations

from datetime import date, datetime, timezone

from auth import (
    get_user_telegram_settings,
    list_telegram_notification_users,
    mark_reminder_sent,
    reminder_sent_today,
    touch_last_progress_update,
)
from config import current_month_key, format_month_label, goal_completion_pct, weighted_score
from data import fetch_month_goals, fetch_month_progress, init_db
from notifiers.telegram_core import resolve_bot_token, telegram_send_text

KIND_MISSING_GOALS = "missing_goals"
KIND_STALE_PROGRESS = "stale_progress"


def _today_str() -> str:
    return date.today().isoformat()


def _progress_updated_today(last_at: str | None) -> bool:
    if not last_at:
        return False
    try:
        dt = datetime.fromisoformat(last_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().date() == date.today()
    except ValueError:
        return False


def build_progress_summary(user_id: str, month_key: str, *, username: str = "") -> str:
    goals = fetch_month_goals(user_id, month_key)
    if not goals:
        label = format_month_label(month_key)
        who = f"{username} — " if username else ""
        return (
            f"⏰ IKR reminder — {who}{label}\n\n"
            f"You have not set goals for {label} yet.\n"
            f"Open Individual IKR → Config tab to add your monthly goals."
        )

    progress = fetch_month_progress(user_id, month_key)
    earned, total_weight = weighted_score(goals, progress)
    overall_pct = (earned / total_weight * 100.0) if total_weight > 0 else 0.0
    label = format_month_label(month_key)
    who = f"{username} — " if username else ""

    lines = [
        f"📋 IKR progress — {who}{label}",
        f"Overall score: {overall_pct:.0f}% ({earned:.1f} / {total_weight:.1f})",
        "",
    ]
    for i, g in enumerate(goals, start=1):
        prog = progress.get(g["id"], 0.0)
        pct = goal_completion_pct(prog, g["target"])
        lines.append(
            f"{i}. {g['name']}: {prog:.2f} / {g['target']:.2f} ({pct:.0f}%) "
            f"[weight {g['weightage']:.0f}%]"
        )
    return "\n".join(lines)


def _telegram_update_hint() -> str:
    return (
        "\n\n✏️ Update here — no need to open the app:\n"
        "• Send: 1 3.5  (goal number + progress)\n"
        "• Or: Read: 3  (goal name + progress)\n"
        "• /status — refresh list\n"
        "• /help — commands"
    )


def build_stale_progress_reminder(user_id: str, month_key: str, *, username: str = "") -> str:
    summary = build_progress_summary(user_id, month_key, username=username)
    label = format_month_label(month_key)
    return (
        f"⏰ IKR daily reminder — {label}\n"
        f"Progress has not been updated today.\n\n"
        f"{summary}"
        f"{_telegram_update_hint()}"
    )


def send_telegram_message(chat_id: str, message: str) -> tuple[bool, str]:
    token = resolve_bot_token()
    if not token:
        return False, "Telegram bot token is not configured. Add `telegram_bot_token.txt` or set TELEGRAM_BOT_TOKEN."
    if not str(chat_id).strip():
        return False, "Telegram chat id is not set."
    try:
        telegram_send_text(token, chat_id, message)
    except Exception as exc:
        return False, f"Telegram send failed: {exc}"
    return True, "Message sent to Telegram."


def send_summary_to_user(user_id: str) -> tuple[bool, str]:
    settings = get_user_telegram_settings(user_id)
    if not settings.get("telegram_enabled"):
        return False, "Telegram notifications are disabled in Account settings."
    chat_id = str(settings.get("telegram_chat_id") or "").strip()
    if not chat_id:
        return False, "Telegram chat id is not set in Account settings."

    month_key = current_month_key()
    message = build_progress_summary(
        user_id,
        month_key,
        username=str(settings.get("username") or ""),
    )
    return send_telegram_message(chat_id, message)


def process_daily_reminders(*, dry_run: bool = False) -> list[dict]:
    """Send at most one reminder per kind per user per day. Run via cron."""
    init_db()
    month_key = current_month_key()
    today = _today_str()
    results: list[dict] = []

    for user in list_telegram_notification_users():
        user_id = user["id"]
        username = user["username"]
        chat_id = user["telegram_chat_id"]
        goals = fetch_month_goals(user_id, month_key)

        if not goals:
            kind = KIND_MISSING_GOALS
            if reminder_sent_today(user_id, kind, today):
                results.append({"user": username, "kind": kind, "status": "skipped"})
                continue
            message = build_progress_summary(user_id, month_key, username=username)
        else:
            if _progress_updated_today(user.get("last_progress_update_at")):
                results.append({"user": username, "kind": "none", "status": "up_to_date"})
                continue
            kind = KIND_STALE_PROGRESS
            if reminder_sent_today(user_id, kind, today):
                results.append({"user": username, "kind": kind, "status": "skipped"})
                continue
            message = build_stale_progress_reminder(user_id, month_key, username=username)

        if dry_run:
            results.append({"user": username, "kind": kind, "status": "dry_run", "message": message})
            continue

        ok, detail = send_telegram_message(chat_id, message)
        if ok:
            mark_reminder_sent(user_id, kind, today)
            results.append({"user": username, "kind": kind, "status": "sent"})
        else:
            results.append({"user": username, "kind": kind, "status": "error", "detail": detail})

    return results


def record_progress_saved(user_id: str) -> None:
    touch_last_progress_update(user_id)
