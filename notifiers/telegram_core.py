"""
Lightweight Telegram Bot API helpers (requests only).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import requests

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import gcp_secrets  # noqa: E402


def read_telegram_bot_token_from_file() -> str:
    return gcp_secrets.resolve_plaintext(
        key="telegram_bot_token",
        env_var="TELEGRAM_BOT_TOKEN",
        file_path=_ROOT / "telegram_bot_token.txt",
    )


def resolve_bot_token() -> str:
    return read_telegram_bot_token_from_file()


def _telegram_requests_verify():
    v = os.environ.get("TELEGRAM_SSL_VERIFY", "1").strip().lower()
    if v in ("0", "false", "no", "off"):
        print(
            "Warning: TELEGRAM_SSL_VERIFY=0 — TLS verification disabled for Telegram API.",
            file=sys.stderr,
        )
        return False
    try:
        import certifi

        return certifi.where()
    except Exception:
        return True


def parse_telegram_chat_id(raw: str) -> str | int:
    s = str(raw).strip()
    if not s:
        return s
    if s.lstrip("-").isdigit():
        try:
            return int(s)
        except ValueError:
            pass
    return s


def _api_get(
    bot_token: str,
    method: str,
    *,
    params: dict | None = None,
    verify: bool | str | None = None,
    timeout: int = 12,
    retries: int = 3,
) -> dict:
    if verify is None:
        verify = _telegram_requests_verify()
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{bot_token}/{method}",
                params=params or {},
                timeout=timeout,
                verify=verify,
            )
            data = r.json()
            if not data.get("ok"):
                raise RuntimeError(data.get("description", data))
            return data
        except requests.exceptions.SSLError as err:
            last_exc = err
            verify = False
        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
        ) as err:
            last_exc = err
            if attempt + 1 < retries:
                time.sleep(0.75 * (attempt + 1))
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("Telegram API request failed")


def fetch_bot_info() -> dict | None:
    """Return bot username/name if token is configured."""
    token = resolve_bot_token()
    if not token:
        return None
    try:
        data = _api_get(token, "getMe")
        return data.get("result") or {}
    except Exception:
        return None


def fetch_recent_chat_ids() -> tuple[list[dict], str | None]:
    """
    Chat ids from recent messages sent TO the bot.
    Returns (entries, error_message).
    """
    token = resolve_bot_token()
    if not token:
        return [], "Bot token is not configured in telegram_bot_token.txt."

    try:
        data = _api_get(token, "getUpdates")
    except Exception as exc:
        return [], f"Could not reach Telegram: {exc}"

    seen: set[int | str] = set()
    entries: list[dict] = []
    for update in data.get("result") or []:
        msg = update.get("message") or update.get("edited_message") or {}
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None or chat_id in seen:
            continue
        seen.add(chat_id)
        sender = msg.get("from") or {}
        label_parts = [
            str(p)
            for p in (
                sender.get("first_name"),
                sender.get("last_name"),
                f"@{sender.get('username')}" if sender.get("username") else None,
            )
            if p
        ]
        entries.append(
            {
                "chat_id": str(chat_id),
                "chat_type": str(chat.get("type") or ""),
                "label": " ".join(label_parts) or str(chat.get("title") or "Unknown"),
            }
        )
    return entries, None


def ensure_polling_mode() -> str | None:
    """Remove webhook if set — getUpdates polling does not work with an active webhook."""
    token = resolve_bot_token()
    if not token:
        return None
    try:
        info = _api_get(token, "getWebhookInfo")
        url = str((info.get("result") or {}).get("url") or "").strip()
        if url:
            _api_get(token, "deleteWebhook", params={"drop_pending_updates": False})
    except Exception as exc:
        return str(exc)
    return None


def fetch_updates(*, offset: int | None = None) -> tuple[list[dict], str | None]:
    """Fetch bot updates. Pass offset to acknowledge earlier updates."""
    token = resolve_bot_token()
    if not token:
        return [], "Bot token is not configured."

    params: dict = {"timeout": 0}
    if offset is not None:
        params["offset"] = offset

    try:
        data = _api_get(token, "getUpdates", params=params)
        return data.get("result") or [], None
    except Exception as exc:
        return [], f"Could not reach Telegram: {exc}"


def telegram_send_text(
    bot_token: str,
    chat_id: str,
    text: str,
    *,
    parse_mode: str | None = None,
    reply_markup: dict | None = None,
) -> None:
    """sendMessage in 4096-char chunks (Telegram limit)."""
    verify: bool | str = _telegram_requests_verify()
    cid = parse_telegram_chat_id(chat_id)
    base = f"https://api.telegram.org/bot{bot_token}"
    max_len = 4096
    for i in range(0, len(text), max_len):
        chunk = text[i : i + max_len]
        while True:
            try:
                payload: dict = {"chat_id": cid, "text": chunk}
                if parse_mode:
                    payload["parse_mode"] = parse_mode
                if reply_markup and i == 0:
                    payload["reply_markup"] = reply_markup
                r = requests.post(
                    f"{base}/sendMessage",
                    json=payload,
                    timeout=25,
                    verify=verify,
                )
                j = r.json()
                if not j.get("ok"):
                    raise RuntimeError(
                        f"Telegram sendMessage: {j.get('description', j)}"
                    )
                break
            except (
                requests.exceptions.SSLError,
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
            ) as err:
                if verify is False:
                    raise
                es = str(err).lower()
                if "ssl" not in es and "certificate" not in es:
                    raise
                verify = False


def answer_callback_query(bot_token: str, callback_query_id: str, text: str = "") -> None:
    verify: bool | str = _telegram_requests_verify()
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text[:200]
    requests.post(
        f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery",
        json=payload,
        timeout=30,
        verify=verify,
    )


def telegram_send_photo(
    bot_token: str,
    chat_id: str,
    image_bytes: bytes,
    *,
    caption: str | None = None,
) -> None:
    """Send a PNG/JPEG image via sendPhoto (caption only — use sendMessage for keyboards)."""
    verify: bool | str = _telegram_requests_verify()
    cid = parse_telegram_chat_id(chat_id)
    base = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    data: dict = {"chat_id": cid}
    if caption:
        data["caption"] = caption[:1024]
    files = {"photo": ("timeline.png", image_bytes, "image/png")}
    while True:
        try:
            r = requests.post(base, data=data, files=files, timeout=25, verify=verify)
            j = r.json()
            if not j.get("ok"):
                raise RuntimeError(f"Telegram sendPhoto: {j.get('description', j)}")
            return
        except (
            requests.exceptions.SSLError,
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
        ) as err:
            if verify is False:
                raise
            es = str(err).lower()
            if "ssl" not in es and "certificate" not in es:
                raise
            verify = False
