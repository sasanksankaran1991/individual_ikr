"""Handle inbound Telegram messages: connect links and progress updates."""

from __future__ import annotations

import re
import sqlite3

from auth import (
    _connect,
    get_app_meta,
    get_user_by_telegram_chat_id,
    get_user_telegram_settings,
    init_users_table,
    link_user_telegram,
    set_app_meta,
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

_UPDATE_SET_RE = re.compile(r"^(\d+)\s+(\d+(?:\.\d+)?)$")
_UPDATE_VALUE_RE = re.compile(r"^(\d+(?:\.\d+)?)$")
_UPDATE_NAME_RE = re.compile(r"^(.+?)\s*[:=]\s*(\d+(?:\.\d+)?)$")
_GOAL_PICK_RE = re.compile(r"^G(\d+)$")

_GOALS_BUTTON = "📊 Goals"
_HELP_BUTTON = "❓ Help"
_BACK_BUTTON = "← Back"
_QUICK_VALUES = ("1", "5", "15")


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
    from notifiers.telegram_core import fetch_updates

    init_users_table()
    with _connect() as conn:
        offset_raw = _get_meta(conn, "telegram_update_offset")
    offset = int(offset_raw) if offset_raw and offset_raw.isdigit() else None

    updates, err = fetch_updates(offset=offset)
    if err:
        return [], err
    return updates, None


def acknowledge_updates(updates: list[dict]) -> None:
    if not updates:
        return
    last_id = max(int(u.get("update_id", 0)) for u in updates)
    with _connect() as conn:
        _set_meta(conn, "telegram_update_offset", str(last_id + 1))
        conn.commit()


def fetch_and_ack_updates() -> tuple[list[dict], str | None]:
    """Backward-compatible helper: fetch and immediately acknowledge."""
    updates, err = fetch_pending_updates()
    if err:
        return [], err
    acknowledge_updates(updates)
    return updates, None


def _selected_goal_meta_key(user_id: str) -> str:
    return f"telegram_selected_goal:{user_id}"


def get_selected_goal_index(user_id: str) -> int | None:
    raw = get_app_meta(_selected_goal_meta_key(user_id))
    if raw and str(raw).isdigit():
        return int(raw)
    return None


def set_selected_goal_index(user_id: str, index: int | None) -> None:
    if index is None:
        set_app_meta(_selected_goal_meta_key(user_id), "")
    else:
        set_app_meta(_selected_goal_meta_key(user_id), str(index))


def _validated_selected_goal(user_id: str, goals: list[dict]) -> int | None:
    idx = get_selected_goal_index(user_id)
    if idx is None:
        return None
    if idx < 1 or idx > len(goals):
        set_selected_goal_index(user_id, None)
        return None
    return idx


def telegram_help_text() -> str:
    return (
        "IKR bot — quick progress updates:\n"
        "• Tap 📊 Goals to see this month's status\n"
        "• Tap G1, G2, … to select a goal\n"
        "• Type a value (e.g. 5 or 15) or tap 1, 5, 15\n"
        "• Or send: 1 5  (goal number + value)\n"
        "• Or: Read: 3  (goal name + value)\n"
        "• /help — this message"
    )


def build_progress_reply_keyboard(goals: list[dict], user_id: str | None = None) -> dict:
    """Persistent keyboard: pick goal, then enter value in the text field or tap 1/5/15."""
    rows: list[list[str]] = [[_GOALS_BUTTON, _HELP_BUTTON]]
    if not goals:
        return {
            "keyboard": rows,
            "resize_keyboard": True,
            "is_persistent": True,
        }

    selected_idx = _validated_selected_goal(user_id, goals) if user_id else None
    if selected_idx is not None:
        g = goals[selected_idx - 1]
        short = (g["name"][:14].strip() or f"Goal {selected_idx}")[:14]
        rows.append([_BACK_BUTTON, f"G{selected_idx}: {short}"])
        rows.append(list(_QUICK_VALUES))
        return {
            "keyboard": rows,
            "resize_keyboard": True,
            "is_persistent": True,
        }

    pick_row: list[str] = []
    for i, g in enumerate(goals, start=1):
        name = (g["name"][:10].strip() or str(i))[:10]
        pick_row.append(f"G{i} {name}")
        if len(pick_row) == 3:
            rows.append(pick_row)
            pick_row = []
    if pick_row:
        rows.append(pick_row)
    return {
        "keyboard": rows,
        "resize_keyboard": True,
        "is_persistent": True,
    }


def _goal_pick_index(text: str, goals: list[dict]) -> int | None:
    m = _GOAL_PICK_RE.match(text.strip())
    if m:
        return int(m.group(1))
    for i, g in enumerate(goals, start=1):
        name = (g["name"][:10].strip() or str(i))[:10]
        if text == f"G{i} {name}":
            return i
    return None


def _goal_selection_prompt(user_id: str, goals: list[dict], idx: int) -> str:
    g = goals[idx - 1]
    prog = fetch_month_progress(user_id, current_month_key()).get(g["id"], 0.0)
    return (
        f"📌 Goal {idx} — {g['name']}\n"
        f"Current: {prog:.2f} / {g['target']:.2f}\n\n"
        f"Type a value below or tap 1, 5, or 15."
    )


def build_goal_keyboard(goals: list[dict]) -> dict:
    """Inline goal pick + value shortcuts under a status message."""
    rows: list[list[dict]] = []
    row: list[dict] = []
    for i, g in enumerate(goals, start=1):
        name = (g["name"][:12].strip() or f"G{i}")[:12]
        row.append({"text": f"G{i} {name}", "callback_data": f"g:{i}"})
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([{"text": "📊 Refresh", "callback_data": "refresh"}])
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
    lines.append("Tap G1, G2, … then type a value (e.g. 5) or tap 1 / 5 / 15.")
    return "\n".join(lines)


def _goals_status_reply(user_id: str, month_key: str | None = None) -> tuple[str, dict, bool]:
    month_key = month_key or current_month_key()
    goals = fetch_month_goals(user_id, month_key)
    keyboard = build_progress_reply_keyboard(goals, user_id)
    if not goals:
        return build_numbered_status(user_id, month_key), keyboard, False
    username = str(get_user_telegram_settings(user_id).get("username") or "")
    return (
        build_progress_summary(user_id, month_key, username=username),
        keyboard,
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


def _apply_selected_goal_value(
    user_id: str, goals: list[dict], idx: int, value: float, month_key: str
) -> str:
    return _apply_goal_progress(user_id, goals[idx - 1], value, month_key)


def handle_user_message(user_id: str, text: str) -> tuple[str | None, dict | None, bool]:
    """Return (reply, reply_markup, attach_timeline_chart)."""
    init_db()
    text = (text or "").strip()
    if not text:
        return None, None, False

    month_key = current_month_key()
    lower = text.lower()

    if text == _HELP_BUTTON or lower.startswith("/help"):
        goals = fetch_month_goals(user_id, month_key)
        return telegram_help_text(), build_progress_reply_keyboard(goals, user_id), False

    if lower.startswith("/start"):
        goals = fetch_month_goals(user_id, month_key)
        intro = (
            "👋 Individual IKR bot\n\n"
            "1. Tap G1, G2, … to pick a goal\n"
            "2. Type a value or tap 1, 5, 15"
        )
        return intro, build_progress_reply_keyboard(goals, user_id), False

    if (
        text == _GOALS_BUTTON
        or lower.startswith("/status")
        or lower.startswith("/progress")
        or lower.startswith("/goals")
    ):
        return _goals_status_reply(user_id, month_key)

    goals = fetch_month_goals(user_id, month_key)
    keyboard = build_progress_reply_keyboard(goals, user_id)
    if not goals:
        return f"No goals for {format_month_label(month_key)}. Add them in the app first.", keyboard, False

    if text == _BACK_BUTTON:
        set_selected_goal_index(user_id, None)
        return "Goal cleared. Tap G1, G2, … to select again.", build_progress_reply_keyboard(goals, user_id), False

    pick_idx = _goal_pick_index(text, goals)
    if pick_idx is not None:
        if pick_idx < 1 or pick_idx > len(goals):
            return f"Goal number must be 1–{len(goals)}.", keyboard, False
        set_selected_goal_index(user_id, pick_idx)
        return (
            _goal_selection_prompt(user_id, goals, pick_idx),
            build_progress_reply_keyboard(goals, user_id),
            False,
        )

    selected_idx = _validated_selected_goal(user_id, goals)
    if selected_idx is not None:
        m = _UPDATE_VALUE_RE.match(text)
        if m:
            value = float(m.group(1))
            reply = _apply_selected_goal_value(user_id, goals, selected_idx, value, month_key)
            return reply, build_progress_reply_keyboard(goals, user_id), False

    m = _UPDATE_SET_RE.match(text)
    if m:
        idx = int(m.group(1))
        value = float(m.group(2))
        if idx < 1 or idx > len(goals):
            return f"Goal number must be 1–{len(goals)}. Tap 📊 Goals to see the list.", keyboard, False
        set_selected_goal_index(user_id, idx)
        reply = _apply_selected_goal_value(user_id, goals, idx, value, month_key)
        return reply, build_progress_reply_keyboard(goals, user_id), False

    m = _UPDATE_NAME_RE.match(text)
    if m:
        goal = _find_goal_by_name(goals, m.group(1))
        if not goal:
            return f"Goal not found: {m.group(1)!r}. Tap 📊 Goals for numbered list.", keyboard, False
        idx = next(i for i, g in enumerate(goals, start=1) if g["id"] == goal["id"])
        set_selected_goal_index(user_id, idx)
        reply = _apply_goal_progress(user_id, goal, float(m.group(2)), month_key)
        return reply, build_progress_reply_keyboard(goals, user_id), False

    if selected_idx is not None:
        return (
            f"Enter a number for goal {selected_idx}, or tap 1, 5, or 15.\n"
            f"Example: 5  (same as sending {selected_idx} 5)",
            keyboard,
            False,
        )

    return "Tap G1, G2, … to select a goal, then type a value. Send /help for more.", keyboard, False


def handle_callback_query(user_id: str, data: str) -> tuple[str | None, dict | None, bool]:
    month_key = current_month_key()
    goals = fetch_month_goals(user_id, month_key)
    keyboard = build_progress_reply_keyboard(goals, user_id)

    if data == "refresh":
        return _goals_status_reply(user_id, month_key)

    if data.startswith("g:"):
        try:
            idx = int(data.split(":", 1)[1])
        except ValueError:
            return "Invalid button.", keyboard, False
        if idx < 1 or idx > len(goals):
            return "Goal not found.", keyboard, False
        set_selected_goal_index(user_id, idx)
        return (
            _goal_selection_prompt(user_id, goals, idx),
            build_progress_reply_keyboard(goals, user_id),
            False,
        )

    if data.startswith("v:"):
        parts = data.split(":")
        if len(parts) != 3:
            return "Invalid button.", keyboard, False
        try:
            idx = int(parts[1])
            value = float(parts[2])
        except ValueError:
            return "Invalid button.", keyboard, False
        if idx < 1 or idx > len(goals):
            return "Goal not found.", keyboard, False
        set_selected_goal_index(user_id, idx)
        reply = _apply_selected_goal_value(user_id, goals, idx, value, month_key)
        return reply, build_progress_reply_keyboard(goals, user_id), False

    return "Tap 📊 Goals or send /help.", keyboard, False


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
    goals = fetch_month_goals(uid, current_month_key())
    send_telegram_message(
        str(chat_id),
        "✅ Connected to Individual IKR.\n"
        "Tap G1, G2, … to pick a goal, then type a value or tap 1, 5, 15.",
        reply_markup=build_progress_reply_keyboard(goals, uid),
    )
    return True


def process_all_inbound_updates() -> tuple[list[dict], str | None]:
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
                reply_markup=markup,
            )
        return send_telegram_message(chat_id_s, reply, reply_markup=markup)

    try:
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
                reply, markup, attach_timeline = handle_callback_query(str(user["id"]), data)
                if not reply:
                    continue
                if token:
                    toast = reply.split("\n", 1)[0][:200]
                    answer_callback_query(token, str(cb.get("id", "")), toast)
                ok, detail = _send_reply(chat_id_s, user, reply, markup, attach_timeline)
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
    finally:
        acknowledge_updates(updates)

    return results, None
