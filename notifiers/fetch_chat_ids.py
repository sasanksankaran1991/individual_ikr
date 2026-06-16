#!/usr/bin/env python3
"""Print Telegram chat ids from recent messages to your bot."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from notifiers.telegram_core import fetch_bot_info, fetch_recent_chat_ids


def main() -> int:
    bot = fetch_bot_info()
    if bot:
        username = bot.get("username")
        if username:
            print(f"Bot: @{username}")
            print(f"1. Open Telegram and send any message to @{username} (e.g. hi)")
            print("2. Run this script again.\n")

    entries, err = fetch_recent_chat_ids()
    if err:
        print(f"Error: {err}", file=sys.stderr)
        return 1

    if not entries:
        print("No messages found yet.")
        print("Send a message to your bot first, then run this script again.")
        return 1

    print("Chat ids found:")
    for e in entries:
        print(f"  {e['chat_id']}  ({e['label']}, {e['chat_type']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
