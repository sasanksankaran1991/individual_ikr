"""Handle inbound Telegram messages: connect links and progress updates."""

from __future__ import annotations

import re
import sqlite3

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
from telegram_connect import CONNECT_PREFIX, _parse_start_payload

_UPDATE_INDEX_RE = re.compile(r"^(\d+)\s*[:=]?\s*(\d+(?:\.\d+)?)$")
_UPDATE_NAME_RE = re.compile(r"^(.+?)\s*[:=]\s*(\d+(?:\.\d+)?)$")


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


def fetch_and_ack_updates() -> tuple[list[dict], str | None]:
    from notifiers.telegram_core import fetch_updates

    init_users_table()
    with _connect() as conn:
        offset_raw = _get_meta(conn, "telegram_update_offset")
    offset = int(offset_raw) if offset_raw and offset_raw.isdigit() else None

    updates, err = fetch_updates(offset=offset)
    if err:
        return [], err

    if updates:
        last_id = max(int(u.get("update_id", 0)) for u in updates)
        with _connect() as conn:
            _set_meta(conn, "telegram_update_offset", str(last_id + 1))
            conn.commit()
    return updates, None


def telegram_help_text() -> str:
    return (
        "IKR bot commands:\n"
        "• /status or /goals — show current month goals\n"
        "• <number> <progress> — e.g. 1 3.5\n"
        "• <goal name>: <progress> — e.g. Read: 3\n"
        "• Tap goal buttons after /status for quick hints\n"
        "• /help — this message"
    )


def build_goal_keyboard(goals: list[dict]) -> dict:
    rows: list[list[dict]] = []
    row: list[dict] = []
    for i, g in enumerate(goals, start=1):
        label = f"{i}. {g['name'][:18]}"
        row.append({"text": label, "callback_data": f"pick:{i}"})
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return {"inline_keyboard": rows}


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
    lines.append("Update: send 1 3.5  or  Read: 3")
    return "\n".join(lines)


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


def handle_user_message(user_id: str, text: str) -> tuple[str | None, dict | None, bool]:
    """Return (reply, keyboard, attach_timeline_chart)."""
    init_db()
    text = (text or "").strip()
    if not text:
        return None, None, False

    month_key = current_month_key()
    lower = text.lower()

    if lower.startswith("/help") or lower == "/start":
        return telegram_help_text(), None, False

    if lower.startswith("/status") or lower.startswith("/progress") or lower.startswith("/goals"):
        goals = fetch_month_goals(user_id, month_key)
        markup = build_goal_keyboard(goals) if goals else None
        if goals:
            username = str(get_user_telegram_settings(user_id).get("username") or "")
            return (
                build_progress_summary(user_id, month_key, username=username),
                markup,
                True,
            )
        return build_numbered_status(user_id, month_key), markup, False

    goals = fetch_month_goals(user_id, month_key)
    if not goals:
        return f"No goals for {format_month_label(month_key)}. Add them in the app first.", None, False

    m = _UPDATE_INDEX_RE.match(text)
    if m:
        idx = int(m.group(1))
        value = float(m.group(2))
        if idx < 1 or idx > len(goals):
            return f"Goal number must be 1–{len(goals)}. Send /status to see the list.", None, False
        return _apply_goal_progress(user_id, goals[idx - 1], value, month_key), None, False

    m = _UPDATE_NAME_RE.match(text)
    if m:
        goal = _find_goal_by_name(goals, m.group(1))
        if not goal:
            return f"Goal not found: {m.group(1)!r}. Send /status for numbered list.", None, False
        return _apply_goal_progress(user_id, goal, float(m.group(2)), month_key), None, False

    return "Send /help for commands, or e.g. 1 3.5 to update goal 1.", None, False


def handle_callback_query(user_id: str, data: str) -> str:
    if data.startswith("pick:"):
        try:
            idx = int(data.split(":", 1)[1])
        except ValueError:
            return "Invalid button."
        month_key = current_month_key()
        goals = fetch_month_goals(user_id, month_key)
        if idx < 1 or idx > len(goals):
            return "Goal not found."
        g = goals[idx - 1]
        prog = fetch_month_progress(user_id, month_key).get(g["id"], 0.0)
        return (
            f"Goal {idx}: {g['name']}\n"
            f"Current: {prog:.2f} / {g['target']:.2f}\n"
            f"Send: {idx} <new value>  e.g. {idx} 5"
        )
    return "Send /help for commands."


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
        "Send /goals to see goals or /help for update commands.",
    )
    return True


def process_all_inbound_updates() -> tuple[list[dict], str | None]:
    from data import init_db
    from notifiers.telegram_core import answer_callback_query, resolve_bot_token

    init_db()
    updates, err = fetch_and_ack_updates()
    if err:
        return [], err

    token = resolve_bot_token()
    results: list[dict] = []

    for update in updates:
        cb = update.get("callback_query")
        if cb:
            chat_id = (cb.get("message") or {}).get("chat", {}).get("id")
            if chat_id is None:
                continue
            chat_id_s = str(chat_id)
            user = get_user_by_telegram_chat_id(chat_id_s)
            if not user or not user.get("telegram_enabled"):
                continue
            data = str(cb.get("data") or "")
            reply = handle_callback_query(str(user["id"]), data)
            if token:
                answer_callback_query(token, str(cb.get("id", "")), reply[:200])
            ok, detail = send_telegram_message(chat_id_s, reply)
            results.append(
                {
                    "type": "callback",
                    "user": user.get("username"),
                    "ok": ok,
                    "detail": detail if not ok else reply[:80],
                }
            )
            continue

        msg = update.get("message") or update.get("edited_message") or {}
        text = str(msg.get("text") or "")
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            continue

        chat_id_s = str(chat_id)

        if _handle_connect(update):
            results.append({"type": "connect", "chat_id": chat_id_s})
            continue

        if _parse_start_payload(text):
            continue

        user = get_user_by_telegram_chat_id(chat_id_s)
        if not user or not user.get("telegram_enabled"):
            continue

        reply, markup, attach_timeline = handle_user_message(str(user["id"]), text)
        if not reply:
            continue

        month_key = current_month_key()
        if attach_timeline:
            ok, detail = send_telegram_with_timeline(
                chat_id_s,
                reply,
                str(user["id"]),
                month_key,
                reply_markup=markup,
            )
        else:
            ok, detail = send_telegram_message(chat_id_s, reply, reply_markup=markup)
        results.append(
            {
                "type": "command",
                "user": user.get("username"),
                "chat_id": chat_id_s,
                "ok": ok,
                "detail": detail if not ok else reply[:80],
            }
        )

    return results, None
