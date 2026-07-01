#!/usr/bin/env python3
"""Pull/push ikr.db to/from GCS (Cloud Run persistence)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DATA_FILES = ("ikr.db",)


def _paths() -> list[tuple[Path, str]]:
    return [(_ROOT / name, name) for name in DATA_FILES]


def _bucket_name() -> str:
    b = os.environ.get("GCS_DATA_BUCKET", "").strip()
    if not b:
        raise SystemExit("GCS_DATA_BUCKET is not set")
    return b


def pull() -> int:
    from google.cloud import storage  # type: ignore[import-untyped]

    client = storage.Client()
    bucket = client.bucket(_bucket_name())
    for local, blob_name in _paths():
        blob = bucket.blob(blob_name)
        if not blob.exists():
            print(f"skip (missing in GCS): {blob_name}")
            continue
        local.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(str(local))
        print(f"pulled gs://{_bucket_name()}/{blob_name} → {local}")
    return 0


def push() -> int:
    from google.cloud import storage  # type: ignore[import-untyped]

    client = storage.Client()
    bucket = client.bucket(_bucket_name())
    for local, blob_name in _paths():
        if not local.is_file():
            print(f"skip (missing locally): {local}")
            continue
        blob = bucket.blob(blob_name)
        blob.upload_from_filename(str(local))
        print(f"pushed {local} → gs://{_bucket_name()}/{blob_name}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync IKR data with GCS")
    parser.add_argument("action", choices=["pull", "push"])
    args = parser.parse_args()
    if args.action == "pull":
        return pull()
    return push()


if __name__ == "__main__":
    raise SystemExit(main())
