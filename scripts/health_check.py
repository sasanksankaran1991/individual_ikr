#!/usr/bin/env python3
"""Health check: database, Telegram token, last scheduler poll."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config import IKRR_DB_PATH
from data import init_db
from notifiers.telegram_core import fetch_bot_info, resolve_bot_token
from scheduler_status import get_scheduler_status


def main() -> int:
    init_db()
    ok = True

    if not IKRR_DB_PATH.is_file():
        print("FAIL: ikr.db not found")
        ok = False
    else:
        print(f"OK: database at {IKRR_DB_PATH}")

    if resolve_bot_token():
        print("OK: Telegram token configured")
        bot = fetch_bot_info()
        if bot:
            print(f"OK: Bot @{bot.get('username', '?')}")
        else:
            print("WARN: Token set but getMe failed")
    else:
        print("WARN: Telegram token not configured")

    status = get_scheduler_status()
    print(f"Last poll: {status['last_poll_at']}")
    print(f"Telegram users: {status['telegram_user_count']}/{status['total_users']}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
