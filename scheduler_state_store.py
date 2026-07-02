"""Scheduler interval + last poll in GCS (survives Streamlit overwriting ikr.db)."""

from __future__ import annotations

from datetime import datetime

from auth import get_app_meta, set_app_meta
from config import CLOUD_TICK_INTERVAL_OPTIONS, SCHEDULER_LAST_POLL_META_KEY
from gcs_sidecar import read_blob, write_blob

META_CLOUD_TICK_INTERVAL = "settings_cloud_tick_interval_minutes"

GCS_INTERVAL_BLOB = "settings_cloud_tick_interval_minutes.txt"
GCS_LAST_POLL_BLOB = "scheduler_last_poll_at.txt"


def read_cloud_tick_interval_minutes() -> int | None:
    raw = read_blob(GCS_INTERVAL_BLOB)
    if raw and raw.strip().isdigit():
        minutes = int(raw.strip())
        if minutes in CLOUD_TICK_INTERVAL_OPTIONS:
            return minutes
    raw = (get_app_meta(META_CLOUD_TICK_INTERVAL) or "").strip()
    if raw.isdigit():
        minutes = int(raw)
        if minutes in CLOUD_TICK_INTERVAL_OPTIONS:
            return minutes
    return None


def write_cloud_tick_interval_minutes(minutes: int) -> None:
    if minutes not in CLOUD_TICK_INTERVAL_OPTIONS:
        return
    set_app_meta(META_CLOUD_TICK_INTERVAL, str(minutes))
    write_blob(GCS_INTERVAL_BLOB, str(minutes))


def read_last_poll_at() -> datetime | None:
    candidates: list[datetime] = []
    for raw in (read_blob(GCS_LAST_POLL_BLOB), get_app_meta(SCHEDULER_LAST_POLL_META_KEY)):
        text = (raw or "").strip()
        if not text:
            continue
        try:
            candidates.append(datetime.fromisoformat(text))
        except ValueError:
            continue
    if not candidates:
        return None
    return max(candidates)


def write_last_poll_at(when: datetime) -> None:
    iso = when.isoformat(timespec="seconds")
    set_app_meta(SCHEDULER_LAST_POLL_META_KEY, iso)
    write_blob(GCS_LAST_POLL_BLOB, iso)
