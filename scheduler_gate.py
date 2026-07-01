"""Gate Cloud Run scheduler wakes against admin-configured interval in ikr.db."""

from __future__ import annotations

from datetime import datetime, timedelta

from auth import get_app_meta
from background_scheduler import scheduler_now
from config import SCHEDULER_LAST_POLL_META_KEY
from reminder_settings import get_cloud_tick_interval_minutes


def cloud_tick_due() -> tuple[bool, str]:
    """
    Return (should_run, reason).

    Cloud Scheduler wakes every ~30 minutes; the admin picks 30 min / 1 h / 3 h / 6 h
    in Settings. Skip cheaply when the chosen interval has not elapsed since last poll.
    """
    interval_min = get_cloud_tick_interval_minutes()
    last_raw = (get_app_meta(SCHEDULER_LAST_POLL_META_KEY) or "").strip()
    if not last_raw:
        return True, "first poll"

    try:
        last_at = datetime.fromisoformat(last_raw)
    except ValueError:
        return True, "invalid last poll timestamp"

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
