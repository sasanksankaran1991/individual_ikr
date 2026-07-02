"""Log processed Telegram update_id values so replays never re-send replies."""

from __future__ import annotations

from datetime import datetime, timezone

from auth import _connect
from gcs_sidecar import read_blob, write_blob

GCS_PROCESSED_BLOB = "telegram_processed_update_ids.txt"
MAX_STORED_IDS = 5000

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS telegram_processed_updates (
    update_id INTEGER PRIMARY KEY,
    message_preview TEXT NOT NULL DEFAULT '',
    processed_at TEXT NOT NULL
)
"""


def _ensure_table(conn) -> None:
    conn.execute(_CREATE_SQL)


def _read_gcs_ids() -> set[int]:
    raw = read_blob(GCS_PROCESSED_BLOB)
    if not raw:
        return set()
    ids: set[int] = set()
    for line in raw.splitlines():
        line = line.strip()
        if line.isdigit():
            ids.add(int(line))
    return ids


def _write_gcs_ids(ids: set[int]) -> None:
    if not ids:
        return
    ordered = sorted(ids)[-MAX_STORED_IDS:]
    write_blob(GCS_PROCESSED_BLOB, "\n".join(str(i) for i in ordered) + "\n")


def is_update_processed(update_id: int) -> bool:
    uid = int(update_id)
    if uid in _read_gcs_ids():
        return True
    with _connect() as conn:
        _ensure_table(conn)
        row = conn.execute(
            "SELECT 1 FROM telegram_processed_updates WHERE update_id = ?",
            (uid,),
        ).fetchone()
    return row is not None


def mark_update_processed(update_id: int, message_preview: str = "") -> None:
    uid = int(update_id)
    preview = (message_preview or "")[:200]
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")

    with _connect() as conn:
        _ensure_table(conn)
        conn.execute(
            """
            INSERT INTO telegram_processed_updates (update_id, message_preview, processed_at)
            VALUES (?, ?, ?)
            ON CONFLICT(update_id) DO NOTHING
            """,
            (uid, preview, now),
        )
        conn.commit()

    gcs_ids = _read_gcs_ids()
    gcs_ids.add(uid)
    if len(gcs_ids) > MAX_STORED_IDS:
        gcs_ids = set(sorted(gcs_ids)[-MAX_STORED_IDS:])
    _write_gcs_ids(gcs_ids)


def prune_below_offset(min_update_id: int) -> None:
    """Drop ids older than the Telegram offset window (optional housekeeping)."""
    floor = max(0, int(min_update_id) - 200)
    with _connect() as conn:
        _ensure_table(conn)
        conn.execute(
            "DELETE FROM telegram_processed_updates WHERE update_id < ?",
            (floor,),
        )
        conn.commit()
    gcs_ids = {i for i in _read_gcs_ids() if i >= floor}
    _write_gcs_ids(gcs_ids)
