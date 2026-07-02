"""Read/write small GCS blobs (scheduler state, Telegram dedup) outside ikr.db."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def gcs_bucket() -> str | None:
    b = os.environ.get("GCS_DATA_BUCKET", "").strip()
    return b or None


def read_blob(blob_name: str) -> str | None:
    bucket_name = gcs_bucket()
    if not bucket_name:
        return None
    try:
        from google.cloud import storage  # type: ignore[import-untyped]

        client = storage.Client()
        blob = client.bucket(bucket_name).blob(blob_name)
        if not blob.exists():
            return None
        return blob.download_as_text()
    except Exception as exc:
        print(f"GCS read failed ({blob_name}): {exc}", file=sys.stderr)
        return None


def write_blob(blob_name: str, content: str, *, content_type: str = "text/plain") -> None:
    bucket_name = gcs_bucket()
    if not bucket_name:
        return
    try:
        from google.cloud import storage  # type: ignore[import-untyped]

        client = storage.Client()
        blob = client.bucket(bucket_name).blob(blob_name)
        blob.upload_from_string(content, content_type=content_type)
    except Exception as exc:
        print(f"GCS write failed ({blob_name}): {exc}", file=sys.stderr)


def push_ikr_db_if_configured() -> None:
    if not gcs_bucket():
        return
    try:
        from scripts.gcp.gcs_data_sync import push

        push()
    except Exception as exc:
        print(f"GCS ikr.db push failed: {exc}", file=sys.stderr)


def pull_ikr_db_if_configured() -> None:
    """Refresh local ikr.db from GCS (Streamlit — pick up Telegram/scheduler writes)."""
    if not gcs_bucket():
        return
    try:
        from scripts.gcp.gcs_data_sync import pull

        pull()
    except Exception as exc:
        print(f"GCS ikr.db pull failed: {exc}", file=sys.stderr)


def persist_ikr_db_to_cloud() -> None:
    """Push ikr.db after a deliberate write (UI save or scheduler tick)."""
    push_ikr_db_if_configured()
