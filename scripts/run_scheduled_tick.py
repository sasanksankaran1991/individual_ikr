#!/usr/bin/env python3
"""
Single scheduler tick: Telegram poll + due reminders.

Used by Cloud Run Job / Cloud Scheduler (every 3 hours) — starts, runs once, exits.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from background_scheduler import run_background_tick  # noqa: E402


def main() -> int:
    result = run_background_tick()
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
