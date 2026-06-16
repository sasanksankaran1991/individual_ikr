"""User authentication and account management."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import datetime, timezone

from config import IKRR_DB_PATH, ensure_db_file, new_user_id

_USERS_DDL = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    telegram_chat_id TEXT,
    telegram_enabled INTEGER NOT NULL DEFAULT 0,
    last_progress_update_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
"""

_REMINDER_LOG_DDL = """
CREATE TABLE IF NOT EXISTS reminder_log (
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    sent_date TEXT NOT NULL,
    PRIMARY KEY (user_id, kind, sent_date),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
"""

_CONNECT_TOKENS_DDL = """
CREATE TABLE IF NOT EXISTS telegram_connect_tokens (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
"""

_APP_META_DDL = """
CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

ADMIN_USERNAME = "admin"
ADMIN_DEFAULT_PASSWORD = "admin"
_PBKDF2_ITERATIONS = 260_000


def _connect() -> sqlite3.Connection:
    ensure_db_file()
    conn = sqlite3.connect(IKRR_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(r[1]) for r in rows}


def _migrate_users_notification_columns(conn: sqlite3.Connection) -> None:
    cols = _table_columns(conn, "users")
    if not cols:
        return
    if "telegram_chat_id" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN telegram_chat_id TEXT")
    if "telegram_enabled" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN telegram_enabled INTEGER NOT NULL DEFAULT 0")
    if "last_progress_update_at" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN last_progress_update_at TEXT")


def init_users_table() -> None:
    with _connect() as conn:
        conn.executescript(
            _USERS_DDL + _REMINDER_LOG_DDL + _CONNECT_TOKENS_DDL + _APP_META_DDL
        )
        _migrate_users_notification_columns(conn)
        conn.commit()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        _PBKDF2_ITERATIONS,
    )
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt, digest_hex = stored_hash.split("$", 1)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        _PBKDF2_ITERATIONS,
    )
    return secrets.compare_digest(digest.hex(), digest_hex)


def ensure_admin_user() -> str:
    """Create default admin if missing. Returns admin user id."""
    init_users_table()
    with _connect() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE username = ? COLLATE NOCASE",
            (ADMIN_USERNAME,),
        ).fetchone()
        if row:
            return str(row["id"])

        admin_id = new_user_id()
        conn.execute(
            """
            INSERT INTO users (id, username, password_hash, is_admin, created_at)
            VALUES (?, ?, ?, 1, ?)
            """,
            (
                admin_id,
                ADMIN_USERNAME,
                hash_password(ADMIN_DEFAULT_PASSWORD),
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
        return admin_id


def authenticate(username: str, password: str) -> dict | None:
    username = username.strip()
    if not username or not password:
        return None
    from data import init_db

    init_db()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, username, password_hash, is_admin
            FROM users
            WHERE username = ? COLLATE NOCASE
            """,
            (username,),
        ).fetchone()
    if not row or not verify_password(password, str(row["password_hash"])):
        return None
    return {
        "id": str(row["id"]),
        "username": str(row["username"]),
        "is_admin": bool(row["is_admin"]),
    }


def list_users() -> list[dict]:
    init_users_table()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, username, is_admin, created_at
            FROM users
            ORDER BY is_admin DESC, username COLLATE NOCASE
            """
        ).fetchall()
    return [
        {
            "id": str(r["id"]),
            "username": str(r["username"]),
            "is_admin": bool(r["is_admin"]),
            "created_at": str(r["created_at"]),
        }
        for r in rows
    ]


def create_user(username: str, password: str, *, is_admin: bool = False) -> tuple[bool, str]:
    username = username.strip()
    if not username:
        return False, "Username is required."
    if len(username) < 2:
        return False, "Username must be at least 2 characters."
    err = _validate_new_password(password)
    if err:
        return False, err

    init_users_table()
    with _connect() as conn:
        exists = conn.execute(
            "SELECT 1 FROM users WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchone()
        if exists:
            return False, f"Username **{username}** already exists."

        conn.execute(
            """
            INSERT INTO users (id, username, password_hash, is_admin, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                new_user_id(),
                username,
                hash_password(password),
                1 if is_admin else 0,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
    return True, f"User **{username}** created."


def _validate_new_password(password: str) -> str | None:
    if not password:
        return "Password is required."
    if len(password) < 4:
        return "Password must be at least 4 characters."
    return None


def change_password(user_id: str, current_password: str, new_password: str) -> tuple[bool, str]:
    err = _validate_new_password(new_password)
    if err:
        return False, err
    if current_password == new_password:
        return False, "New password must be different from the current password."

    init_users_table()
    with _connect() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not row:
            return False, "User not found."
        if not verify_password(current_password, str(row["password_hash"])):
            return False, "Current password is incorrect."

        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(new_password), user_id),
        )
        conn.commit()
    return True, "Password updated successfully."


def delete_user(user_id: str, *, acting_admin_id: str) -> tuple[bool, str]:
    if user_id == acting_admin_id:
        return False, "You cannot delete your own account."

    init_users_table()
    with _connect() as conn:
        target = conn.execute(
            "SELECT id, username, is_admin FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not target:
            return False, "User not found."

        if bool(target["is_admin"]):
            admin_count = conn.execute(
                "SELECT COUNT(*) FROM users WHERE is_admin = 1"
            ).fetchone()[0]
            if admin_count <= 1:
                return False, "Cannot delete the only admin account."

        conn.execute(
            """
            DELETE FROM progress
            WHERE goal_id IN (SELECT id FROM goals WHERE user_id = ?)
            """,
            (user_id,),
        )
        conn.execute("DELETE FROM goals WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()

    username = str(target["username"])
    return True, f"User **{username}** and all their goals were deleted."


def admin_reset_password(user_id: str, new_password: str) -> tuple[bool, str]:
    """Admin-only: set a new password without knowing the old one."""
    err = _validate_new_password(new_password)
    if err:
        return False, err
    init_users_table()
    with _connect() as conn:
        row = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            return False, "User not found."
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(new_password), user_id),
        )
        conn.commit()
    return True, f"Password reset for **{row['username']}**."


def get_user_telegram_settings(user_id: str) -> dict:
    init_users_table()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, username, telegram_chat_id, telegram_enabled, last_progress_update_at
            FROM users WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
    if not row:
        return {}
    return {
        "id": str(row["id"]),
        "username": str(row["username"]),
        "telegram_chat_id": str(row["telegram_chat_id"] or ""),
        "telegram_enabled": bool(row["telegram_enabled"]),
        "last_progress_update_at": row["last_progress_update_at"],
    }


def update_user_telegram_settings(
    user_id: str,
    *,
    telegram_chat_id: str,
    telegram_enabled: bool,
) -> tuple[bool, str]:
    init_users_table()
    chat_id = telegram_chat_id.strip()
    if telegram_enabled and not chat_id:
        return False, "Enter your Telegram chat id before enabling notifications."

    with _connect() as conn:
        exists = conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone()
        if not exists:
            return False, "User not found."
        conn.execute(
            """
            UPDATE users
            SET telegram_chat_id = ?, telegram_enabled = ?
            WHERE id = ?
            """,
            (chat_id or None, 1 if telegram_enabled else 0, user_id),
        )
        conn.commit()
    return True, "Telegram settings saved."


def link_user_telegram(user_id: str, chat_id: str) -> None:
    """Save chat id, enable notifications, clear pending connect tokens."""
    init_users_table()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE users
            SET telegram_chat_id = ?, telegram_enabled = 1
            WHERE id = ?
            """,
            (str(chat_id).strip(), user_id),
        )
        conn.execute(
            "DELETE FROM telegram_connect_tokens WHERE user_id = ?",
            (user_id,),
        )
        conn.commit()


def disconnect_user_telegram(user_id: str) -> None:
    init_users_table()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE users
            SET telegram_chat_id = NULL, telegram_enabled = 0
            WHERE id = ?
            """,
            (user_id,),
        )
        conn.execute(
            "DELETE FROM telegram_connect_tokens WHERE user_id = ?",
            (user_id,),
        )
        conn.commit()


def touch_last_progress_update(user_id: str) -> None:
    init_users_table()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute(
            "UPDATE users SET last_progress_update_at = ? WHERE id = ?",
            (now, user_id),
        )
        conn.commit()


def get_user_by_telegram_chat_id(chat_id: str) -> dict | None:
    init_users_table()
    cid = str(chat_id).strip()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, username, telegram_chat_id, telegram_enabled, last_progress_update_at
            FROM users
            WHERE telegram_chat_id = ?
            """,
            (cid,),
        ).fetchone()
    if not row:
        return None
    return {
        "id": str(row["id"]),
        "username": str(row["username"]),
        "telegram_chat_id": str(row["telegram_chat_id"] or ""),
        "telegram_enabled": bool(row["telegram_enabled"]),
        "last_progress_update_at": row["last_progress_update_at"],
    }


def list_telegram_notification_users() -> list[dict]:
    init_users_table()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, username, telegram_chat_id, last_progress_update_at
            FROM users
            WHERE telegram_enabled = 1
              AND telegram_chat_id IS NOT NULL
              AND TRIM(telegram_chat_id) != ''
            ORDER BY username COLLATE NOCASE
            """
        ).fetchall()
    return [
        {
            "id": str(r["id"]),
            "username": str(r["username"]),
            "telegram_chat_id": str(r["telegram_chat_id"]),
            "last_progress_update_at": r["last_progress_update_at"],
        }
        for r in rows
    ]


def reminder_sent_today(user_id: str, kind: str, sent_date: str) -> bool:
    init_users_table()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM reminder_log
            WHERE user_id = ? AND kind = ? AND sent_date = ?
            """,
            (user_id, kind, sent_date),
        ).fetchone()
    return row is not None


def mark_reminder_sent(user_id: str, kind: str, sent_date: str) -> None:
    init_users_table()
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO reminder_log (user_id, kind, sent_date)
            VALUES (?, ?, ?)
            """,
            (user_id, kind, sent_date),
        )
        conn.commit()


def get_app_meta(key: str) -> str | None:
    init_users_table()
    with _connect() as conn:
        row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row else None


def set_app_meta(key: str, value: str) -> None:
    init_users_table()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO app_meta (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        conn.commit()


