"""Handle inbound Telegram messages: connect links and progress updates."""

from __future__ import annotations

import re
import sqlite3

from auth import (
    _connect,
    get_user_by_telegram_chat_id,
    init_users_table,
    link_user_telegram,
)
from config import current_month_key, format_month_label, goal_completion_pct, weighted_score
from data import fetch_month_goals, fetch_month_progress, init_db, save_month_progress
from notifications import record_progress_saved, send_telegram_message
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
        "• /status — show current month goals\n"
        "• <number> <progress> — e.g. 1 3.5\n"
        "• <goal name>: <progress> — e.g. Read: 3\n"
        "• /help — this message"
    )


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
    save_month_progress(user_id, month_key, progress)
    record_progress_saved(user_id)

    pct = goal_completion_pct(progress[goal["id"]], goal["target"])
    return (
        f"✅ Updated **{goal['name']}** → {progress[goal['id']]:.2f} "
        f"/ {goal['target']:.2f} ({pct:.0f}%)"
    ).replace("**", "")


def handle_user_message(user_id: str, text: str) -> str | None:
    """Parse a Telegram message from a linked user. Return reply text or None."""
    init_db()
    text = (text or "").strip()
    if not text:
        return None

    month_key = current_month_key()
    lower = text.lower()

    if lower.startswith("/help") or lower == "/start":
        return telegram_help_text()

    if lower.startswith("/status") or lower.startswith("/progress"):
        return build_numbered_status(user_id, month_key)

    goals = fetch_month_goals(user_id, month_key)
    if not goals:
        return f"No goals for {format_month_label(month_key)}. Add them in the app first."

    m = _UPDATE_INDEX_RE.match(text)
    if m:
        idx = int(m.group(1))
        value = float(m.group(2))
        if idx < 1 or idx > len(goals):
            return f"Goal number must be 1–{len(goals)}. Send /status to see the list."
        return _apply_goal_progress(user_id, goals[idx - 1], value, month_key)

    m = _UPDATE_NAME_RE.match(text)
    if m:
        goal = _find_goal_by_name(goals, m.group(1))
        if not goal:
            return f"Goal not found: {m.group(1)!r}. Send /status for numbered list."
        return _apply_goal_progress(user_id, goal, float(m.group(2)), month_key)

    return "Send /help for commands, or e.g. 1 3.5 to update goal 1."


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
        "Send /status to see goals or /help for update commands.",
    )
    return True


def process_all_inbound_updates() -> tuple[list[dict], str | None]:
    """
    Process connect links and progress-update replies.
    Returns (result rows, error).
    """
    from data import init_db

    init_db()
    updates, err = fetch_and_ack_updates()
    if err:
        return [], err

    results: list[dict] = []
    for update in updates:
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

        reply = handle_user_message(str(user["id"]), text)
        if not reply:
            continue

        ok, detail = send_telegram_message(chat_id_s, reply)
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
