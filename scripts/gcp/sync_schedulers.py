#!/usr/bin/env python3
"""CLI: sync Cloud Scheduler crons from ikr.db settings (after deploy or manual fix)."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from cloud_scheduler_sync import sync_cloud_schedulers  # noqa: E402
from data import init_db  # noqa: E402
from reminder_settings import get_reminder_settings  # noqa: E402


def main() -> int:
    init_db()
    ok, msg = sync_cloud_schedulers(get_reminder_settings())
    print(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
