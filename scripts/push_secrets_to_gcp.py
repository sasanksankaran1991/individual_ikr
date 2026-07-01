#!/usr/bin/env python3
"""Upload local telegram_bot_token.txt into Google Secret Manager (ikr- prefix)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import gcp_secrets  # noqa: E402

SECRET_SOURCES: list[tuple[str, list[str]]] = [
    ("telegram_bot_token", ["telegram_bot_token.txt"]),
]


def _read_source(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"empty file: {path}")
    for line in text.splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            return s
    raise ValueError(f"no value in {path}")


def _ensure_secret_manager_client() -> None:
    try:
        import google.cloud.secretmanager  # noqa: F401
    except ImportError:
        print(
            "Missing: google-cloud-secret-manager\n"
            "Install: pip install google-cloud-secret-manager",
            file=sys.stderr,
        )
        raise SystemExit(1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Push IKR secrets to Google Secret Manager")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip() and not os.environ.get(
        "GCP_PROJECT", ""
    ).strip():
        print("Set GOOGLE_CLOUD_PROJECT to your GCP project id.", file=sys.stderr)
        return 1

    print(f"Secret prefix: {gcp_secrets.secret_prefix()!r}")

    if not args.dry_run:
        _ensure_secret_manager_client()

    uploaded = 0
    failed = 0
    for key, rel_paths in SECRET_SOURCES:
        payload: str | None = None
        src: Path | None = None
        for rel in rel_paths:
            candidate = _ROOT / rel
            if candidate.is_file():
                try:
                    payload = _read_source(candidate)
                    src = candidate
                    break
                except ValueError:
                    continue
        if payload is None:
            continue

        sid = gcp_secrets.secret_id_for(key)
        if args.dry_run:
            print(f"would upload {key} → {sid} from {src}")
            uploaded += 1
            continue

        if gcp_secrets.put_secret_text(key, payload):
            print(f"uploaded {key} → {sid} from {src}")
            uploaded += 1
        else:
            failed += 1

    if uploaded == 0 and failed == 0:
        print("No local secret files found to upload.", file=sys.stderr)
        return 1
    if failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
