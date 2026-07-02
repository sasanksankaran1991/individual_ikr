"""Gate Cloud Run scheduler wakes against admin-configured interval in ikr.db."""

from __future__ import annotations

from datetime import datetime, timedelta

from background_scheduler import scheduler_now
from reminder_settings import get_cloud_tick_interval_minutes
from scheduler_state_store import read_last_poll_at


def cloud_tick_due() -> tuple[bool, str]:
    """
    Return (should_run, reason).

    Cloud Scheduler wakes every ~30 minutes; the admin picks 30 min / 1 h / 3 h / 6 h
    in Settings. Skip cheaply when the chosen interval has not elapsed since last poll.
    """
    interval_min = get_cloud_tick_interval_minutes()
    last_at = read_last_poll_at()
    if last_at is None:
        return True, "first poll"

    now = scheduler_now()
    if last_at.tzinfo is None and now.tzinfo is not None:
        last_at = last_at.replace(tzinfo=now.tzinfo)
    elif last_at.tzinfo is not None and now.tzinfo is None:
        now = now.replace(tzinfo=last_at.tzinfo)

    elapsed = now - last_at
    need = timedelta(minutes=interval_min)
    # Allow 1 minute slack for cron jitter.
    if elapsed + timedelta(minutes=1) >= need:
        return True, f"interval {interval_min} min elapsed"

    remaining = need - elapsed
    mins_left = max(0, int(remaining.total_seconds() // 60))
    return False, f"next tick in ~{mins_left} min (interval {interval_min} min)"
