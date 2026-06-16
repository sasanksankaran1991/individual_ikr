#!/usr/bin/env python3
"""
Poll Telegram for progress updates and connect messages.

Run every 1–2 minutes via cron so users can reply to reminders:

  cd /path/to/individual_ikr
  python notifiers/poll_telegram.py

Also runs automatically at the start of send_reminders.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from telegram_inbound import process_all_inbound_updates
from data import init_db


def main() -> int:
    init_db()
    results, err = process_all_inbound_updates()
    if err:
        print(f"Error: {err}", file=sys.stderr)
        return 1

    if not results:
        print("No new Telegram messages.")
        return 0

    for row in results:
        if row.get("type") == "connect":
            print(f"Connected chat {row.get('chat_id')}")
        else:
            user = row.get("user", "?")
            ok = row.get("ok")
            detail = row.get("detail", "")
            print(f"{user}: {'ok' if ok else 'fail'} — {detail}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
