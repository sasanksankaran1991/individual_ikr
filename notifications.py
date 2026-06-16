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
from config import (
    MID_MONTH_REMINDER_DAY,
    current_month_key,
    format_month_label,
    goal_completion_pct,
    is_last_day_of_month,
    month_pace_fraction,
    pace_info,
    weighted_score,
)
from data import fetch_month_goals, fetch_month_progress, init_db
from notifiers.telegram_core import resolve_bot_token, telegram_send_photo, telegram_send_text
from progress_timeline import render_timeline_png_bytes

KIND_MISSING_GOALS = "missing_goals"
KIND_STALE_PROGRESS = "stale_progress"
KIND_MID_MONTH = "mid_month"
KIND_END_MONTH = "end_month"
KIND_EVENING_NUDGE = "evening_nudge"


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


def _pace_emoji(tone: str) -> str:
    return {"ahead": "🟢", "behind": "🔴", "track": "🟡"}.get(tone, "⚪")


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
    overall = pace_info(overall_pct, month_key)
    label = format_month_label(month_key)
    who = f"{username} — " if username else ""
    pace_pct = month_pace_fraction(month_key) * 100.0

    lines = [
        f"📋 IKR progress — {who}{label}",
        f"{_pace_emoji(overall['tone'])} Overall: {overall['label']} "
        f"({overall_pct:.0f}% vs {pace_pct:.0f}% expected)",
        f"Weighted score: {earned:.1f} / {total_weight:.1f}",
        "",
    ]
    for i, g in enumerate(goals, start=1):
        prog = progress.get(g["id"], 0.0)
        pct = goal_completion_pct(prog, g["target"])
        gi = pace_info(pct, month_key)
        cat = f" [{g['category']}]" if g.get("category") else ""
        lines.append(
            f"{i}. {_pace_emoji(gi['tone'])} {g['name']}{cat}: "
            f"{prog:.2f}/{g['target']:.2f} ({pct:.0f}%) "
            f"[{gi['label']}]"
        )
    lines.append("\n📈 Timeline chart attached above.")
    return "\n".join(lines)


def _telegram_update_hint() -> str:
    return (
        "\n\n✏️ Update here — no need to open the app:\n"
        "• Send: 1 3.5  (goal number + progress)\n"
        "• Or: Read: 3  (goal name + progress)\n"
        "• /status or /goals — refresh list\n"
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


def build_mid_month_report(user_id: str, month_key: str, *, username: str = "") -> str:
    summary = build_progress_summary(user_id, month_key, username=username)
    label = format_month_label(month_key)
    return (
        f"📊 IKR mid-month check-in — {label}\n"
        f"Halfway through the month — here's where you stand:\n\n"
        f"{summary}"
        f"{_telegram_update_hint()}"
    )


def build_end_month_report(user_id: str, month_key: str, *, username: str = "") -> str:
    summary = build_progress_summary(user_id, month_key, username=username)
    label = format_month_label(month_key)
    return (
        f"🏁 IKR month-end summary — {label}\n"
        f"Final progress for the month:\n\n"
        f"{summary}"
    )


def send_telegram_message(
    chat_id: str,
    message: str,
    *,
    reply_markup: dict | None = None,
    user_id: str | None = None,
    month_key: str | None = None,
    attach_timeline: bool = False,
) -> tuple[bool, str]:
    token = resolve_bot_token()
    if not token:
        return False, "Telegram bot token is not configured."
    if not str(chat_id).strip():
        return False, "Telegram chat id is not set."
    try:
        if attach_timeline and user_id and month_key:
            goals = fetch_month_goals(user_id, month_key)
            if goals:
                progress = fetch_month_progress(user_id, month_key)
                png = render_timeline_png_bytes(user_id, month_key, goals, progress)
                if png:
                    caption_line = message.split("\n", 1)[0][:200]
                    telegram_send_photo(token, chat_id, png, caption=caption_line)
        telegram_send_text(token, chat_id, message, reply_markup=reply_markup)
    except Exception as exc:
        return False, f"Telegram send failed: {exc}"
    return True, "Message sent to Telegram."


def send_telegram_with_timeline(
    chat_id: str,
    message: str,
    user_id: str,
    month_key: str,
    *,
    reply_markup: dict | None = None,
) -> tuple[bool, str]:
    """Send progress text plus timeline chart image when goals exist."""
    goals = fetch_month_goals(user_id, month_key)
    return send_telegram_message(
        chat_id,
        message,
        reply_markup=reply_markup,
        user_id=user_id,
        month_key=month_key,
        attach_timeline=bool(goals),
    )


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
    return send_telegram_with_timeline(chat_id, message, user_id, month_key)


def broadcast_summaries_to_all_users() -> list[dict]:
    """Admin: send current month summary to every Telegram-connected user."""
    init_db()
    month_key = current_month_key()
    results: list[dict] = []
    for user in list_telegram_notification_users():
        message = build_progress_summary(
            user["id"],
            month_key,
            username=user["username"],
        )
        ok, detail = send_telegram_with_timeline(
            user["telegram_chat_id"], message, user["id"], month_key
        )
        results.append(
            {
                "user": user["username"],
                "status": "sent" if ok else "error",
                "detail": detail,
            }
        )
    return results


def _send_user_reminder(
    user: dict,
    month_key: str,
    kind: str,
    message: str,
    today: str,
    *,
    dry_run: bool,
) -> dict:
    username = user["username"]
    if reminder_sent_today(user["id"], kind, today):
        return {"user": username, "kind": kind, "status": "skipped"}
    if dry_run:
        return {"user": username, "kind": kind, "status": "dry_run", "message": message}
    ok, detail = send_telegram_with_timeline(
        user["telegram_chat_id"], message, user["id"], month_key
    )
    if ok:
        mark_reminder_sent(user["id"], kind, today)
        return {"user": username, "kind": kind, "status": "sent"}
    return {"user": username, "kind": kind, "status": "error", "detail": detail}


def process_daily_reminders(*, dry_run: bool = False) -> list[dict]:
    """Send at most one stale/missing reminder per user per day."""
    init_db()
    month_key = current_month_key()
    today = _today_str()
    results: list[dict] = []

    for user in list_telegram_notification_users():
        user_id = user["id"]
        username = user["username"]
        goals = fetch_month_goals(user_id, month_key)

        if not goals:
            message = build_progress_summary(user_id, month_key, username=username)
            results.append(
                _send_user_reminder(user, month_key, KIND_MISSING_GOALS, message, today, dry_run=dry_run)
            )
            continue

        if _progress_updated_today(user.get("last_progress_update_at")):
            results.append({"user": username, "kind": "none", "status": "up_to_date"})
            continue

        message = build_stale_progress_reminder(user_id, month_key, username=username)
        results.append(
            _send_user_reminder(
                user, month_key, KIND_STALE_PROGRESS, message, today, dry_run=dry_run
            )
        )

    return results


def process_evening_nudges(*, dry_run: bool = False) -> list[dict]:
    """Second nudge if progress still not updated today."""
    init_db()
    month_key = current_month_key()
    today = _today_str()
    results: list[dict] = []

    for user in list_telegram_notification_users():
        if _progress_updated_today(user.get("last_progress_update_at")):
            results.append({"user": user["username"], "kind": KIND_EVENING_NUDGE, "status": "up_to_date"})
            continue
        goals = fetch_month_goals(user["id"], month_key)
        if not goals:
            continue
        message = (
            f"🌆 Evening IKR nudge — {format_month_label(month_key)}\n"
            f"You haven't updated progress today. Quick update?\n"
            f"Send e.g. 1 3.5 or /status"
        )
        results.append(
            _send_user_reminder(
                user, month_key, KIND_EVENING_NUDGE, message, today, dry_run=dry_run
            )
        )
    return results


def process_mid_month_reports(*, dry_run: bool = False) -> list[dict]:
    init_db()
    month_key = current_month_key()
    today = _today_str()
    results: list[dict] = []
    for user in list_telegram_notification_users():
        goals = fetch_month_goals(user["id"], month_key)
        if not goals:
            continue
        message = build_mid_month_report(user["id"], month_key, username=user["username"])
        results.append(
            _send_user_reminder(user, month_key, KIND_MID_MONTH, message, today, dry_run=dry_run)
        )
    return results


def process_end_month_reports(*, dry_run: bool = False) -> list[dict]:
    init_db()
    month_key = current_month_key()
    today = _today_str()
    results: list[dict] = []
    for user in list_telegram_notification_users():
        goals = fetch_month_goals(user["id"], month_key)
        if not goals:
            continue
        message = build_end_month_report(user["id"], month_key, username=user["username"])
        results.append(
            _send_user_reminder(user, month_key, KIND_END_MONTH, message, today, dry_run=dry_run)
        )
    return results


def record_progress_saved(user_id: str) -> None:
    touch_last_progress_update(user_id)
