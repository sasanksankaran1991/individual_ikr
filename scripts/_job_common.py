"""Shared helpers for Cloud Run Job entrypoints."""

from __future__ import annotations

import json
import os
import sys


def push_db_to_gcs() -> None:
    if not os.environ.get("GCS_DATA_BUCKET", "").strip():
        return
    try:
        from scripts.gcp.gcs_data_sync import push

        push()
    except Exception as exc:
        print(f"GCS push failed: {exc}", file=sys.stderr)


def print_result(payload: dict) -> None:
    print(json.dumps(payload, indent=2, default=str))
