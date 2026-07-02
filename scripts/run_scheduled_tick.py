#!/usr/bin/env python3
"""
Single scheduler tick: Telegram poll + due reminders.

Cloud Scheduler wakes every ~30 minutes; admin interval (30 min–6 h) is stored in ikr.db.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from background_scheduler import run_background_tick  # noqa: E402
from data import init_db  # noqa: E402
from scheduler_gate import cloud_tick_due  # noqa: E402


def main() -> int:
    init_db()
    due, reason = cloud_tick_due()
    if not due:
        print(json.dumps({"skipped": True, "reason": reason}))
        return 0

    result = run_background_tick()
    result["gate"] = reason
    print(json.dumps(result, indent=2, default=str))
    if os.environ.get("GCS_DATA_BUCKET", "").strip():
        try:
            from scripts.gcp.gcs_data_sync import push as gcs_push

            gcs_push()
        except Exception as exc:
            print(f"GCS push after tick failed: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
