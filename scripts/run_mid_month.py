#!/usr/bin/env python3
"""Mid-month report on the 15th."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from background_scheduler import scheduler_now  # noqa: E402
from config import MID_MONTH_REMINDER_DAY  # noqa: E402
from data import init_db  # noqa: E402
from notifications import process_mid_month_reports  # noqa: E402
from reminder_settings import get_reminder_settings  # noqa: E402
from scripts._job_common import print_result, push_db_to_gcs  # noqa: E402


def main() -> int:
    init_db()
    settings = get_reminder_settings()
    if not settings["mid_month_enabled"]:
        print_result({"job": "mid-month", "skipped": True, "reason": "mid_month_disabled"})
        return 0

    now = scheduler_now()
    if now.day != MID_MONTH_REMINDER_DAY:
        print_result(
            {
                "job": "mid-month",
                "skipped": True,
                "reason": f"not day {MID_MONTH_REMINDER_DAY}",
                "today": now.day,
            }
        )
        return 0

    results = process_mid_month_reports()
    push_db_to_gcs()
    print_result(
        {
            "job": "mid-month",
            "at": now.isoformat(timespec="seconds"),
            "reminder_results": results,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
