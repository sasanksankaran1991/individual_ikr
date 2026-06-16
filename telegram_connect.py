"""One-click Telegram connect via t.me deep links."""

from __future__ import annotations

import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from auth import _connect, get_user_telegram_settings, init_users_table
from notifiers.telegram_core import fetch_bot_info, resolve_bot_token

CONNECT_PREFIX = "connect_"
_TOKEN_TTL_MINUTES = 30
_START_RE = re.compile(r"^/start(?:@\w+)?\s+(\S+)", re.IGNORECASE)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _purge_expired_tokens(conn: sqlite3.Connection) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=_TOKEN_TTL_MINUTES)).isoformat(
        timespec="seconds"
    )
    conn.execute("DELETE FROM telegram_connect_tokens WHERE created_at < ?", (cutoff,))


def create_connect_link(user_id: str) -> tuple[str | None, str | None]:
    """
    Return (telegram_url, error).
    Reuses an existing valid token for this user when possible.
    """
    init_users_table()
    bot = fetch_bot_info()
    bot_username = (bot or {}).get("username")
    if not bot_username:
        return None, "Bot token missing or invalid. Check telegram_bot_token.txt."

    if not resolve_bot_token():
        return None, "Bot token is not configured."

    with _connect() as conn:
        _purge_expired_tokens(conn)
        row = conn.execute(
            "SELECT token FROM telegram_connect_tokens WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row:
            token = str(row["token"])
        else:
            token = secrets.token_hex(16)
            conn.execute(
                """
                INSERT INTO telegram_connect_tokens (token, user_id, created_at)
                VALUES (?, ?, ?)
                """,
                (token, user_id, _now_iso()),
            )
        conn.commit()

    url = f"https://t.me/{bot_username}?start={CONNECT_PREFIX}{token}"
    return url, None


def _parse_start_payload(text: str) -> str | None:
    if not text:
        return None
    m = _START_RE.match(text.strip())
    if not m:
        return None
    payload = m.group(1).strip()
    if not payload.startswith(CONNECT_PREFIX):
        return None
    return payload[len(CONNECT_PREFIX) :]


def poll_auto_connect(user_id: str) -> tuple[str, str]:
    """
    Poll Telegram for /start connect_<token>.

    Returns (status, message) where status is:
      - "connected" — chat id saved
      - "waiting"   — still waiting for Start in Telegram
      - "error"     — hard failure (show message to user)
    """
    from telegram_inbound import process_all_inbound_updates

    results, err = process_all_inbound_updates()
    if err:
        return "error", err

    settings = get_user_telegram_settings(user_id)
    if settings.get("telegram_enabled") and settings.get("telegram_chat_id"):
        init_users_table()
        with _connect() as conn:
            pending = conn.execute(
                "SELECT 1 FROM telegram_connect_tokens WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if not pending:
            cid = settings["telegram_chat_id"]
            return "connected", f"Telegram connected (chat id {cid}). Notifications are enabled."

    for row in results:
        if row.get("type") == "connect":
            settings = get_user_telegram_settings(user_id)
            if str(settings.get("telegram_chat_id") or ""):
                return "connected", "Telegram connected. Notifications are enabled."

    return "waiting", ""


def try_auto_connect(user_id: str) -> tuple[bool, str]:
    """Backward-compatible wrapper."""
    status, message = poll_auto_connect(user_id)
    if status == "connected":
        return True, message
    if status == "error":
        return False, message
    return False, "Waiting for Start in Telegram."


def process_all_pending_connects() -> int:
    """Process pending connect tokens. Returns count linked."""
    from telegram_inbound import process_all_inbound_updates

    results, _err = process_all_inbound_updates()
    return sum(1 for r in results if r.get("type") == "connect")
