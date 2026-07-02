"""Persist Telegram getUpdates offset in GCS (survives ikr.db overwrites from Streamlit sync)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

GCS_OFFSET_BLOB = "telegram_update_offset.txt"
META_KEY = "telegram_update_offset"


def _bucket() -> str | None:
    b = os.environ.get("GCS_DATA_BUCKET", "").strip()
    return b or None


def _read_gcs() -> int | None:
    bucket_name = _bucket()
    if not bucket_name:
        return None
    try:
        from google.cloud import storage  # type: ignore[import-untyped]

        client = storage.Client()
        blob = client.bucket(bucket_name).blob(GCS_OFFSET_BLOB)
        if not blob.exists():
            return None
        raw = blob.download_as_text().strip()
        return int(raw) if raw.isdigit() else None
    except Exception as exc:
        print(f"telegram offset GCS read failed: {exc}", file=sys.stderr)
        return None


def _write_gcs(offset: int) -> None:
    bucket_name = _bucket()
    if not bucket_name:
        return
    try:
        from google.cloud import storage  # type: ignore[import-untyped]

        client = storage.Client()
        blob = client.bucket(bucket_name).blob(GCS_OFFSET_BLOB)
        blob.upload_from_string(str(offset), content_type="text/plain")
    except Exception as exc:
        print(f"telegram offset GCS write failed: {exc}", file=sys.stderr)


def _read_sqlite() -> int | None:
    from auth import _connect

    with _connect() as conn:
        row = conn.execute(
            "SELECT value FROM app_meta WHERE key = ?", (META_KEY,)
        ).fetchone()
    if not row:
        return None
    raw = str(row["value"]).strip()
    return int(raw) if raw.isdigit() else None


def _write_sqlite(offset: int) -> None:
    from auth import _connect

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO app_meta (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (META_KEY, str(offset)),
        )
        conn.commit()


def read_telegram_update_offset() -> int | None:
    """Highest offset from GCS sidecar and local ikr.db."""
    values = [v for v in (_read_gcs(), _read_sqlite()) if v is not None]
    if not values:
        return None
    return max(values)


def write_telegram_update_offset(offset: int) -> None:
    """Persist to both ikr.db and GCS so Streamlit db sync cannot rewind the bot."""
    _write_sqlite(offset)
    _write_gcs(offset)
