#!/usr/bin/env python3
"""Morning daily reminders + progress-lock warnings."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from background_scheduler import scheduler_now  # noqa: E402
from data import init_db  # noqa: E402
from notifications import (  # noqa: E402
    process_daily_reminders,
    process_progress_lock_reminders,
)
from reminder_settings import get_reminder_settings  # noqa: E402
from scripts._job_common import print_result, push_db_to_gcs  # noqa: E402


def main() -> int:
    init_db()
    settings = get_reminder_settings()
    if not settings["reminders_enabled"]:
        print_result({"job": "morning-reminder", "skipped": True, "reason": "reminders_disabled"})
        return 0

    now = scheduler_now()
    results = process_daily_reminders()
    results.extend(process_progress_lock_reminders())

    push_db_to_gcs()
    print_result(
        {
            "job": "morning-reminder",
            "at": now.isoformat(timespec="seconds"),
            "reminder_results": results,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
