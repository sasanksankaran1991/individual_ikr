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
from config import current_month_key, format_month_label, goal_completion_pct, weighted_score
from data import fetch_month_goals, fetch_month_progress, init_db, save_month_progress
from notifications import (
    build_progress_summary,
    record_progress_saved,
    send_telegram_message,
    send_telegram_with_timeline,
)
from telegram_connect import _parse_start_payload

# Goal number + delta, e.g. "1 +3" or "2 -4"
_UPDATE_DELTA_RE = re.compile(r"^(\d+)\s*([+-])\s*(\d+(?:\.\d+)?)$")
# Goal number + absolute value, e.g. "1 5"
_UPDATE_SET_RE = re.compile(r"^(\d+)\s+(\d+(?:\.\d+)?)$")
_UPDATE_NAME_RE = re.compile(r"^(.+?)\s*[:=]\s*(\d+(?:\.\d+)?)$")

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


def telegram_help_text() -> str:
    return (
        "IKR bot commands:\n"
        "• /goals or /status — show this month's goals\n"
        "• 1 5 — set goal 1 to 5\n"
        "• 1 +3 — add 3 to goal 1\n"
        "• 1 -2 — subtract 2 from goal 1\n"
        "• /goals — show chart & status (only when you ask)\n"
        "• Read: 3 — set by goal name\n"
        "• /help — this message"
    )


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
    earned, total_weight = weighted_score(goals, progress)
    overall_pct = (earned / total_weight * 100.0) if total_weight > 0 else 0.0

    lines = [
        f"📋 {format_month_label(month_key)}",
        f"Overall: {overall_pct:.0f}% ({earned:.1f}/{total_weight:.1f})",
        "",
    ]
    for i, g in enumerate(goals, start=1):
        prog = progress.get(g["id"], 0.0)
        pct = goal_completion_pct(prog, g["target"])
        lines.append(f"{i}. {g['name']}: {prog:.2f}/{g['target']:.2f} ({pct:.0f}%)")
    lines.append("")
    lines.append("Update: 1 5  (set) · 1 +3  (add) · 1 -2  (subtract)")
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
    progress = fetch_month_progress(user_id, month_key)
    progress[goal["id"]] = max(float(value), 0.0)
    save_month_progress(user_id, month_key, progress, source="telegram")
    record_progress_saved(user_id)

    pct = goal_completion_pct(progress[goal["id"]], goal["target"])
    return (
        f"✅ Updated {goal['name']} → {progress[goal['id']]:.2f} "
        f"/ {goal['target']:.2f} ({pct:.0f}%)"
    )


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
            "Send /goals to see goals.\n"
            "Update: 1 5  (set) · 1 +3  (add) · 1 -2  (subtract)",
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
        "Send /goals to see goals. Examples: 1 5  ·  1 +3  ·  1 -2. /help for more.",
        keyboard,
        False,
    )


def handle_callback_query(user_id: str, data: str) -> tuple[str | None, dict | None, bool]:
    if data == "refresh":
        return _goals_status_reply(user_id, current_month_key())
    return "Send /goals or 1 5 to update. /help for commands.", build_simple_reply_keyboard(), False


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
        "✅ Connected to Individual IKR.\n"
        "Send /goals to see goals.\n"
        "Update: 1 5  (set) · 1 +3  (add) · 1 -2  (subtract)",
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
        return send_telegram_message(chat_id_s, reply, reply_markup=markup)

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
