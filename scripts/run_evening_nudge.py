#!/usr/bin/env python3
"""Evening nudge if progress not updated today."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from background_scheduler import scheduler_now  # noqa: E402
from data import init_db  # noqa: E402
from notifications import process_evening_nudges  # noqa: E402
from reminder_settings import get_reminder_settings  # noqa: E402
from scripts._job_common import print_result, push_db_to_gcs  # noqa: E402


def main() -> int:
    init_db()
    settings = get_reminder_settings()
    if not settings["evening_nudge_enabled"]:
        print_result({"job": "evening-nudge", "skipped": True, "reason": "evening_disabled"})
        return 0

    now = scheduler_now()
    results = process_evening_nudges()

    push_db_to_gcs()
    print_result(
        {
            "job": "evening-nudge",
            "at": now.isoformat(timespec="seconds"),
            "reminder_results": results,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
