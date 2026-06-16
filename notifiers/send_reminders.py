#!/usr/bin/env python3
"""
Daily IKR Telegram reminders.

Run once per day via cron / launchd, e.g. 9:00 AM:

  cd /path/to/individual_ikr
  python notifiers/send_reminders.py

Options:
  --dry-run   Print messages without sending
  --user NAME Process one username only

Requires:
  telegram_bot_token.txt (or TELEGRAM_BOT_TOKEN) — shared bot
  Each user: Account tab → Telegram chat id + enable notifications
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from notifications import process_daily_reminders
from data import init_db
from telegram_inbound import process_all_inbound_updates


def main() -> int:
    parser = argparse.ArgumentParser(description="Send IKR Telegram reminders.")
    parser.add_argument("--dry-run", action="store_true", help="Do not send; print actions.")
    parser.add_argument("--user", help="Only process this username.")
    args = parser.parse_args()

    init_db()
    inbound, in_err = process_all_inbound_updates()
    if in_err:
        print(f"Inbound Telegram error: {in_err}", file=sys.stderr)
    elif inbound:
        print(f"Processed {len(inbound)} inbound Telegram message(s).")

    results = process_daily_reminders(dry_run=args.dry_run)
    if args.user:
        uname = args.user.strip().lower()
        results = [r for r in results if r.get("user", "").lower() == uname]
        if not results:
            print(f"No reminder action for user {args.user!r}.", file=sys.stderr)

    for row in results:
        status = row.get("status", "")
        kind = row.get("kind", "")
        user = row.get("user", "")
        line = f"{user}: {kind} → {status}"
        if row.get("detail"):
            line += f" ({row['detail']})"
        print(line)
        if args.dry_run and row.get("message"):
            print("---")
            print(row["message"])
            print("---")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
