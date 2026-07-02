"""Sync Google Cloud Scheduler jobs from admin reminder settings."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

from auth import set_app_meta
from config import MID_MONTH_REMINDER_DAY

META_SYNC_AT = "scheduler_cloud_sync_at"
META_SYNC_ERROR = "scheduler_cloud_sync_error"
META_SYNC_DETAIL = "scheduler_cloud_sync_detail"

TELEGRAM_POLL_CRON = "*/15 * * * *"
DEFAULT_CLOUD_TZ = "Asia/Kolkata"
END_MONTH_CRON_DAYS = "28-31"


@dataclass(frozen=True)
class SchedulerSpec:
    scheduler_id: str
    run_job_id: str
    cron: str
    enabled: bool


def _project_id() -> str | None:
    return (os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT_ID") or "").strip() or None


def _region() -> str:
    return (os.environ.get("GCP_REGION") or "asia-southeast1").strip()


def _scheduler_sa_email() -> str | None:
    project = _project_id()
    if not project:
        return None
    sa = (os.environ.get("SCHEDULER_SA") or "ikr-scheduler").strip()
    return f"{sa}@{project}.iam.gserviceaccount.com"


def cloud_scheduler_sync_enabled() -> bool:
    return bool(_project_id() and os.environ.get("GCS_DATA_BUCKET", "").strip())


def _daily_cron(hour: int, minute: int) -> str:
    return f"{int(minute)} {int(hour)} * * *"


def _mid_month_cron(hour: int, minute: int) -> str:
    return f"{int(minute)} {int(hour)} {MID_MONTH_REMINDER_DAY} * *"


def _end_month_cron(hour: int, minute: int) -> str:
    return f"{int(minute)} {int(hour)} {END_MONTH_CRON_DAYS} * *"


def build_scheduler_specs(settings: dict) -> list[SchedulerSpec]:
    tz = (settings.get("timezone") or DEFAULT_CLOUD_TZ).strip() or DEFAULT_CLOUD_TZ
    _ = tz  # applied uniformly via sync call

    rh, rm = int(settings["reminder_hour"]), int(settings["reminder_minute"])
    eh, em = int(settings["evening_nudge_hour"]), int(settings["evening_nudge_minute"])

    return [
        SchedulerSpec(
            "ikr-telegram-poll-schedule",
            "ikr-telegram-poll",
            TELEGRAM_POLL_CRON,
            True,
        ),
        SchedulerSpec(
            "ikr-morning-reminder-schedule",
            "ikr-morning-reminder",
            _daily_cron(rh, rm),
            bool(settings["reminders_enabled"]),
        ),
        SchedulerSpec(
            "ikr-evening-nudge-schedule",
            "ikr-evening-nudge",
            _daily_cron(eh, em),
            bool(settings["evening_nudge_enabled"]),
        ),
        SchedulerSpec(
            "ikr-mid-month-schedule",
            "ikr-mid-month",
            _mid_month_cron(rh, rm),
            bool(settings["mid_month_enabled"]),
        ),
        SchedulerSpec(
            "ikr-end-month-schedule",
            "ikr-end-month",
            _end_month_cron(rh, rm),
            bool(settings["end_month_enabled"]),
        ),
    ]


def _job_run_uri(project: str, region: str, run_job_id: str) -> str:
    return (
        f"https://{region}-run.googleapis.com/apis/run.googleapis.com/v1/"
        f"namespaces/{project}/jobs/{run_job_id}:run"
    )


def _scheduler_client():
    from google.cloud import scheduler_v1  # type: ignore[import-untyped]

    return scheduler_v1.CloudSchedulerClient()


def _get_job(client, full_name: str):
    from google.api_core.exceptions import NotFound  # type: ignore[import-untyped]

    try:
        return client.get_job(name=full_name)
    except NotFound:
        return None


def _upsert_scheduler(
    client,
    *,
    project: str,
    region: str,
    spec: SchedulerSpec,
    time_zone: str,
    scheduler_sa: str,
) -> str:
    from google.cloud import scheduler_v1  # type: ignore[import-untyped]

    parent = f"projects/{project}/locations/{region}"
    full_name = f"{parent}/jobs/{spec.scheduler_id}"
    uri = _job_run_uri(project, region, spec.run_job_id)

    http_target = scheduler_v1.HttpTarget(
        uri=uri,
        http_method=scheduler_v1.HttpMethod.POST,
        oauth_token=scheduler_v1.OAuthToken(
            service_account_email=scheduler_sa,
            scope="https://www.googleapis.com/auth/cloud-platform",
        ),
    )

    existing = _get_job(client, full_name)
    if existing is None:
        job = scheduler_v1.Job(
            name=full_name,
            schedule=spec.cron,
            time_zone=time_zone,
            http_target=http_target,
        )
        client.create_job(parent=parent, job=job)
        action = "created"
    else:
        existing.schedule = spec.cron
        existing.time_zone = time_zone
        existing.http_target = http_target
        client.update_job(job=existing)
        action = "updated"

    if spec.enabled:
        client.resume_job(name=full_name)
        state = "ENABLED"
    else:
        client.pause_job(name=full_name)
        state = "PAUSED"

    return f"{spec.scheduler_id}: {action}, {state}, cron={spec.cron}"


def sync_cloud_schedulers(settings: dict | None = None) -> tuple[bool, str]:
    """Apply admin settings to Cloud Scheduler (cron + pause/resume)."""
    if not cloud_scheduler_sync_enabled():
        return True, "Cloud scheduler sync skipped (not on GCP)."

    project = _project_id()
    region = _region()
    scheduler_sa = _scheduler_sa_email()
    if not project or not scheduler_sa:
        return False, "Missing GOOGLE_CLOUD_PROJECT or scheduler service account."

    if settings is None:
        from reminder_settings import get_reminder_settings

        settings = get_reminder_settings()

    # Force Kolkata default when admin left timezone empty.
    time_zone = (settings.get("timezone") or DEFAULT_CLOUD_TZ).strip() or DEFAULT_CLOUD_TZ
    specs = build_scheduler_specs(settings)

    try:
        client = _scheduler_client()
        lines: list[str] = []
        for spec in specs:
            lines.append(
                _upsert_scheduler(
                    client,
                    project=project,
                    region=region,
                    spec=spec,
                    time_zone=time_zone,
                    scheduler_sa=scheduler_sa,
                )
            )
    except Exception as exc:
        msg = f"Cloud Scheduler sync failed: {exc}"
        print(msg, file=sys.stderr)
        set_app_meta(META_SYNC_ERROR, str(exc)[:500])
        return False, msg

    detail = "; ".join(lines)
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    set_app_meta(META_SYNC_AT, now)
    set_app_meta(META_SYNC_ERROR, "")
    set_app_meta(META_SYNC_DETAIL, detail[:2000])
    return True, f"Settings saved. Cloud schedules updated ({time_zone})."


def describe_cloud_schedulers() -> list[dict]:
    """Lightweight status for admin UI (best effort)."""
    if not cloud_scheduler_sync_enabled():
        return []

    project = _project_id()
    region = _region()
    if not project:
        return []

    try:
        client = _scheduler_client()
    except Exception:
        return []

    from google.cloud import scheduler_v1  # type: ignore[import-untyped]
    from google.api_core.exceptions import NotFound  # type: ignore[import-untyped]

    from reminder_settings import get_reminder_settings

    for spec in build_scheduler_specs(get_reminder_settings()):
        full_name = f"projects/{project}/locations/{region}/jobs/{spec.scheduler_id}"
        try:
            job = client.get_job(name=full_name)
            state = scheduler_v1.Job.State(job.state).name
        except NotFound:
            state = "MISSING"
        except Exception:
            state = "UNKNOWN"
        out.append(
            {
                "id": spec.scheduler_id,
                "run_job": spec.run_job_id,
                "cron": spec.cron,
                "enabled": spec.enabled,
                "state": state,
            }
        )
    return out
