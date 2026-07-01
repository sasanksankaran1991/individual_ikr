"""Handle inbound Telegram messages: connect links and progress updates."""

from __future__ import annotations

import re
import sqlite3
import threading

_inbound_poll_lock = threading.Lock()

from auth import (
    _connect,
    get_user_by_telegram_chat_id,
    get_user_telegram_settings,
    init_users_table,
    link_user_telegram,
)
from config import GOAL_TYPE_DAILY, current_month_key, format_month_label
from data import (
    fetch_daily_log,
    fetch_month_goals,
    fetch_month_progress,
    init_db,
    save_daily_entry,
    save_month_progress,
)
from goal_scoring import (
    goal_completion_for_type,
    goal_progress_display,
    weighted_score_typed,
)
from notifications import (
    build_progress_summary,
    record_progress_saved,
    send_telegram_message,
    send_telegram_with_timeline,
)
from telegram_connect import _parse_start_payload
from telegram_help import telegram_help_plain, telegram_help_text

# Goal number + delta, e.g. "1 +3" or "2 -4"
_UPDATE_DELTA_RE = re.compile(r"^(\d+)\s*([+-])\s*(\d+(?:\.\d+)?)$")
# Goal number + absolute value, e.g. "1 5"
_UPDATE_SET_RE = re.compile(r"^(\d+)\s+(\d+(?:\.\d+)?)$")
_UPDATE_NAME_RE = re.compile(r"^(.+?)\s*[:=]\s*(\d+(?:\.\d+)?)$")
_UPDATE_DAILY_RE = re.compile(r"^(\d+)\s+(yes|no|y|n)$", re.IGNORECASE)
_UPDATE_DAILY_DATE_RE = re.compile(
    r"^(\d+)\s+(\d{4}-\d{2}-\d{2})\s+(yes|no|y|n)$", re.IGNORECASE
)

_GOALS_BUTTON = "📊 Goals"
_HELP_BUTTON = "❓ Help"


def _get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row else None


def _set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO app_meta (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def fetch_pending_updates() -> tuple[list[dict], str | None]:
    """Fetch Telegram updates without acknowledging them."""
    from notifiers.telegram_core import ensure_polling_mode, fetch_updates

    init_users_table()
    try:
        ensure_polling_mode()
    except Exception:
        pass

    with _connect() as conn:
        offset_raw = _get_meta(conn, "telegram_update_offset")
    offset = int(offset_raw) if offset_raw and offset_raw.isdigit() else None

    updates, err = fetch_updates(offset=offset)
    if err:
        return [], err
    return updates, None


def acknowledge_update(update_id: int) -> None:
    with _connect() as conn:
        offset_raw = _get_meta(conn, "telegram_update_offset")
        current = int(offset_raw) if offset_raw and offset_raw.isdigit() else 0
        next_offset = max(current, int(update_id) + 1)
        _set_meta(conn, "telegram_update_offset", str(next_offset))
        conn.commit()


def acknowledge_updates(updates: list[dict]) -> None:
    if not updates:
        return
    last_id = max(int(u.get("update_id", 0)) for u in updates)
    acknowledge_update(last_id)


def fetch_and_ack_updates() -> tuple[list[dict], str | None]:
    updates, err = fetch_pending_updates()
    if err:
        return [], err
    acknowledge_updates(updates)
    return updates, None


def build_simple_reply_keyboard() -> dict:
    """Two shortcut buttons only — all updates use typed text like 1 5."""
    return {
        "keyboard": [[_GOALS_BUTTON, _HELP_BUTTON]],
        "resize_keyboard": True,
    }


def build_numbered_status(user_id: str, month_key: str | None = None) -> str:
    month_key = month_key or current_month_key()
    goals = fetch_month_goals(user_id, month_key)
    if not goals:
        return (
            f"No goals for {format_month_label(month_key)} yet.\n"
            f"Add them in the app → Config tab."
        )

    progress = fetch_month_progress(user_id, month_key)
    daily_logs = fetch_daily_log(user_id, month_key)
    earned, total_weight = weighted_score_typed(
        goals, progress, month_key=month_key, daily_logs_by_goal=daily_logs
    )
    overall_pct = (earned / total_weight * 100.0) if total_weight > 0 else 0.0

    lines = [
        f"📋 {format_month_label(month_key)}",
        f"Overall: {overall_pct:.0f}% ({earned:.1f}/{total_weight:.1f})",
        "",
    ]
    for i, g in enumerate(goals, start=1):
        prog = progress.get(g["id"], 0.0)
        pct = goal_completion_for_type(
            g,
            prog,
            month_key=month_key,
            daily_entries=daily_logs.get(g["id"]),
        )
        display = goal_progress_display(
            g, prog, month_key=month_key, daily_entries=daily_logs.get(g["id"])
        )
        lines.append(f"{i}. {g['name']}: {display} ({pct:.0f}%)")
    lines.append("")
    lines.append(telegram_help_plain())
    return "\n".join(lines)


def _goals_status_reply(user_id: str, month_key: str | None = None) -> tuple[str, dict | None, bool]:
    month_key = month_key or current_month_key()
    goals = fetch_month_goals(user_id, month_key)
    if not goals:
        return build_numbered_status(user_id, month_key), build_simple_reply_keyboard(), False
    username = str(get_user_telegram_settings(user_id).get("username") or "")
    return (
        build_progress_summary(user_id, month_key, username=username),
        None,
        True,
    )


def _find_goal_by_name(goals: list[dict], query: str) -> dict | None:
    q = query.strip().lower()
    if not q:
        return None
    for g in goals:
        if g["name"].lower() == q:
            return g
    matches = [g for g in goals if q in g["name"].lower()]
    if len(matches) == 1:
        return matches[0]
    return None


def _apply_goal_progress(user_id: str, goal: dict, value: float, month_key: str) -> str:
    if goal.get("goal_type") == GOAL_TYPE_DAILY:
        return "Daily goals use yes/no. Send e.g. 1 yes or 1 no."

    progress = fetch_month_progress(user_id, month_key)
    progress[goal["id"]] = max(float(value), 0.0)
    ok, msg = save_month_progress(user_id, month_key, progress, source="telegram")
    if not ok:
        return f"🔒 {msg}"
    record_progress_saved(user_id)

    daily_logs = fetch_daily_log(user_id, month_key)
    pct = goal_completion_for_type(
        goal,
        progress[goal["id"]],
        month_key=month_key,
        daily_entries=daily_logs.get(goal["id"]),
    )
    display = goal_progress_display(
        goal, progress[goal["id"]], month_key=month_key, daily_entries=daily_logs.get(goal["id"])
    )
    return f"✅ Updated {goal['name']} → {display} ({pct:.0f}%)"


def _normalize_daily_entry(raw: str) -> str:
    return "yes" if raw.lower() in ("yes", "y") else "no"


def _apply_daily_log(
    user_id: str,
    goals: list[dict],
    idx: int,
    entry: str,
    month_key: str,
    log_date: str,
) -> str:
    if idx < 1 or idx > len(goals):
        return f"Goal number must be 1–{len(goals)}. Send /goals to see the list."
    goal = goals[idx - 1]
    if goal.get("goal_type") != GOAL_TYPE_DAILY:
        return f"{goal['name']} is not a daily goal. Use a number, e.g. 1 5."

    ok, msg = save_daily_entry(
        user_id,
        month_key,
        goal["id"],
        log_date,
        _normalize_daily_entry(entry),
        source="telegram",
    )
    if not ok:
        return msg

    record_progress_saved(user_id)
    daily_logs = fetch_daily_log(user_id, month_key)
    prog = fetch_month_progress(user_id, month_key).get(goal["id"], 0.0)
    pct = goal_completion_for_type(
        goal, prog, month_key=month_key, daily_entries=daily_logs.get(goal["id"])
    )
    display = goal_progress_display(
        goal, prog, month_key=month_key, daily_entries=daily_logs.get(goal["id"])
    )
    return f"✅ {goal['name']} {log_date}: {_normalize_daily_entry(entry)} · {display} ({pct:.0f}%)"


def _apply_goal_delta(
    user_id: str, goals: list[dict], idx: int, delta: float, month_key: str
) -> str:
    goal = goals[idx - 1]
    current = fetch_month_progress(user_id, month_key).get(goal["id"], 0.0)
    return _apply_goal_progress(user_id, goal, current + delta, month_key)


def handle_user_message(user_id: str, text: str) -> tuple[str | None, dict | None, bool]:
    """Return (reply, reply_markup, attach_timeline_chart)."""
    init_db()
    text = (text or "").strip()
    if not text:
        return None, None, False

    month_key = current_month_key()
    lower = text.lower()
    keyboard = build_simple_reply_keyboard()

    if text == _HELP_BUTTON or lower.startswith("/help"):
        return telegram_help_text(), keyboard, False

    if lower.startswith("/start"):
        return (
            "👋 Individual IKR bot\n\n"
            "Tap ❓ Help for the command table, or send /goals.",
            keyboard,
            False,
        )

    if (
        text == _GOALS_BUTTON
        or lower.startswith("/status")
        or lower.startswith("/progress")
        or lower.startswith("/goals")
    ):
        return _goals_status_reply(user_id, month_key)

    goals = fetch_month_goals(user_id, month_key)
    if not goals:
        return (
            f"No goals for {format_month_label(month_key)}. Add them in the app first.",
            keyboard,
            False,
        )

    m = _UPDATE_DAILY_DATE_RE.match(text)
    if m:
        idx = int(m.group(1))
        log_date = m.group(2)
        entry = m.group(3)
        reply = _apply_daily_log(user_id, goals, idx, entry, month_key, log_date)
        return reply, None, False

    m = _UPDATE_DAILY_RE.match(text)
    if m:
        from datetime import date

        idx = int(m.group(1))
        entry = m.group(2)
        log_date = date.today().isoformat()
        reply = _apply_daily_log(user_id, goals, idx, entry, month_key, log_date)
        return reply, None, False

    m = _UPDATE_DELTA_RE.match(text)
    if m:
        idx = int(m.group(1))
        sign = m.group(2)
        amount = float(m.group(3))
        delta = amount if sign == "+" else -amount
        if idx < 1 or idx > len(goals):
            return f"Goal number must be 1–{len(goals)}. Send /goals to see the list.", keyboard, False
        reply = _apply_goal_delta(user_id, goals, idx, delta, month_key)
        return reply, None, False

    m = _UPDATE_SET_RE.match(text)
    if m:
        idx = int(m.group(1))
        value = float(m.group(2))
        if idx < 1 or idx > len(goals):
            return f"Goal number must be 1–{len(goals)}. Send /goals to see the list.", keyboard, False
        reply = _apply_goal_progress(user_id, goals[idx - 1], value, month_key)
        return reply, None, False

    m = _UPDATE_NAME_RE.match(text)
    if m:
        goal = _find_goal_by_name(goals, m.group(1))
        if not goal:
            return f"Goal not found: {m.group(1)!r}. Send /goals for numbered list.", keyboard, False
        reply = _apply_goal_progress(user_id, goal, float(m.group(2)), month_key)
        return reply, None, False

    return (
        "Send /goals to see your goals.\n\n" + telegram_help_plain(),
        keyboard,
        False,
    )


def handle_callback_query(user_id: str, data: str) -> tuple[str | None, dict | None, bool]:
    if data == "refresh":
        return _goals_status_reply(user_id, current_month_key())
    return "Send /goals or tap ❓ Help.\n\n" + telegram_help_plain(), build_simple_reply_keyboard(), False


def _handle_connect(update: dict) -> bool:
    msg = update.get("message") or update.get("edited_message") or {}
    token = _parse_start_payload(str(msg.get("text") or ""))
    if not token:
        return False

    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return False

    init_users_table()
    with _connect() as conn:
        row = conn.execute(
            "SELECT user_id FROM telegram_connect_tokens WHERE token = ?",
            (token,),
        ).fetchone()
        if not row:
            return False
        uid = str(row["user_id"])

    link_user_telegram(uid, str(chat_id))
    send_telegram_message(
        str(chat_id),
        "✅ Connected to Individual IKR.\n\n"
        "Send /goals or tap ❓ Help for the command table.",
        reply_markup=build_simple_reply_keyboard(),
    )
    return True


def process_all_inbound_updates() -> tuple[list[dict], str | None]:
    from data import init_db
    from notifiers.telegram_core import answer_callback_query, resolve_bot_token

    if not _inbound_poll_lock.acquire(blocking=False):
        return [], None

    try:
        return _process_inbound_updates_locked()
    finally:
        _inbound_poll_lock.release()


def _process_inbound_updates_locked() -> tuple[list[dict], str | None]:
    from data import init_db
    from notifiers.telegram_core import answer_callback_query, resolve_bot_token

    init_db()
    updates, err = fetch_pending_updates()
    if err:
        return [], err

    token = resolve_bot_token()
    results: list[dict] = []

    def _send_reply(
        chat_id_s: str,
        user: dict,
        reply: str,
        markup: dict | None,
        attach_timeline: bool,
    ) -> tuple[bool, str]:
        month_key = current_month_key()
        if attach_timeline:
            return send_telegram_with_timeline(
                chat_id_s,
                reply,
                str(user["id"]),
                month_key,
                reply_markup=None,
            )
        return send_telegram_message(
            chat_id_s, reply, reply_markup=markup, parse_mode=_parse_mode_for(reply)
        )

    def _parse_mode_for(reply: str) -> str | None:
        return "HTML" if "<pre>" in reply else None

    for update in updates:
        update_id = int(update.get("update_id", 0))
        try:
            cb = update.get("callback_query")
            if cb:
                chat_id = (cb.get("message") or {}).get("chat", {}).get("id")
                if chat_id is None:
                    acknowledge_update(update_id)
                    continue
                chat_id_s = str(chat_id)
                user = get_user_by_telegram_chat_id(chat_id_s)
                if not user or not user.get("telegram_enabled"):
                    acknowledge_update(update_id)
                    continue
                data = str(cb.get("data") or "")
                reply, markup, attach_timeline = handle_callback_query(str(user["id"]), data)
                if not reply:
                    acknowledge_update(update_id)
                    continue
                if token:
                    answer_callback_query(token, str(cb.get("id", "")), reply.split("\n", 1)[0][:200])
                ok, detail = _send_reply(chat_id_s, user, reply, markup, attach_timeline)
                results.append({"type": "callback", "user": user.get("username"), "ok": ok, "detail": detail})
                if not ok:
                    break
                acknowledge_update(update_id)
                continue

            msg = update.get("message") or update.get("edited_message") or {}
            text = str(msg.get("text") or "")
            chat = msg.get("chat") or {}
            chat_id = chat.get("id")
            if chat_id is None:
                acknowledge_update(update_id)
                continue

            chat_id_s = str(chat_id)

            if _handle_connect(update):
                results.append({"type": "connect", "chat_id": chat_id_s})
                acknowledge_update(update_id)
                continue

            if _parse_start_payload(text):
                acknowledge_update(update_id)
                continue

            user = get_user_by_telegram_chat_id(chat_id_s)
            if not user or not user.get("telegram_enabled"):
                acknowledge_update(update_id)
                continue

            reply, markup, attach_timeline = handle_user_message(str(user["id"]), text)
            if not reply:
                acknowledge_update(update_id)
                continue

            ok, detail = _send_reply(chat_id_s, user, reply, markup, attach_timeline)
            results.append(
                {
                    "type": "command",
                    "user": user.get("username"),
                    "chat_id": chat_id_s,
                    "ok": ok,
                    "detail": detail if not ok else reply[:80],
                }
            )
            if not ok:
                break
            acknowledge_update(update_id)
        except Exception as exc:
            results.append({"type": "error", "update_id": update_id, "ok": False, "detail": str(exc)})
            break

    return results, None
