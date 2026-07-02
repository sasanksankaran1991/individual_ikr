#!/usr/bin/env python3
"""Poll inbound Telegram messages (Cloud Scheduler every 15 min)."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from auth import set_app_meta  # noqa: E402
from background_scheduler import scheduler_now  # noqa: E402
from data import init_db  # noqa: E402
from scheduler_state_store import write_last_poll_at  # noqa: E402
from scripts._job_common import print_result, push_db_to_gcs  # noqa: E402
from telegram_inbound import process_all_inbound_updates  # noqa: E402


def main() -> int:
    init_db()
    now = scheduler_now()
    write_last_poll_at(now)

    results, err = process_all_inbound_updates()
    set_app_meta("telegram_last_error", err or "")

    push_db_to_gcs()
    print_result(
        {
            "job": "telegram-poll",
            "at": now.isoformat(timespec="seconds"),
            "inbound_count": len(results),
            "inbound_error": err,
            "results": results,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
