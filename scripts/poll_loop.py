#!/usr/bin/env python3
"""Continuous Telegram poll loop (use when Streamlit is closed)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from background_scheduler import run_background_tick
from data import init_db
from reminder_settings import get_reminder_settings


def main() -> int:
    init_db()
    print("IKR poll loop started. Ctrl+C to stop.")
    while True:
        settings = get_reminder_settings()
        interval = max(30, int(settings["poll_interval_seconds"]))
        try:
            result = run_background_tick()
            if result.get("inbound_count"):
                print(f"Processed {result['inbound_count']} Telegram message(s)")
            if result.get("reminder_results"):
                print(f"Reminders: {len(result['reminder_results'])} action(s)")
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
        time.sleep(interval)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nStopped.")
        raise SystemExit(0)
