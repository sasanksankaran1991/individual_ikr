#!/usr/bin/env bash
# Deploy Cloud Run service (Streamlit) + separate Cloud Run Jobs + Cloud Scheduler entries.
# Usage (from repo root): bash scripts/gcp/deploy.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/gcp/_lib.sh"

require_gcloud
load_config

IMG="$(image_uri)"
SA="$(runner_sa_email)"
SCHED_SA="$(scheduler_sa_email)"
ENV_VARS="$(common_env)"
REGION="$GCP_REGION"
PROJECT="$GCP_PROJECT_ID"

gcloud config set project "$PROJECT"

deploy_job() {
  local job_name="$1"
  local script_path="$2"

  log "Cloud Run Job: $job_name"
  local -a flags=(
    --image="$IMG"
    --region="$REGION"
    --service-account="$SA"
    --set-env-vars="$ENV_VARS"
    --command=/entrypoint-gcp.sh
    --args="python,$script_path"
    --max-retries=1
    --task-timeout=15m
    --memory=512Mi
    --cpu=1
    --quiet
  )
  if gcloud run jobs describe "$job_name" --region="$REGION" &>/dev/null; then
    gcloud run jobs update "$job_name" "${flags[@]}"
  else
    gcloud run jobs create "$job_name" "${flags[@]}"
  fi

  gcloud run jobs add-iam-policy-binding "$job_name" \
    --region="$REGION" \
    --member="serviceAccount:${SCHED_SA}" \
    --role="roles/run.invoker" \
    --quiet >/dev/null
}

schedule_job() {
  local sched_name="$1"
  local cron="$2"
  local job_name="$3"
  local uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/${job_name}:run"

  log "Cloud Scheduler: $sched_name ($cron $TZ)"
  if gcloud scheduler jobs describe "$sched_name" --location="$REGION" &>/dev/null; then
    gcloud scheduler jobs update http "$sched_name" \
      --location="$REGION" \
      --schedule="$cron" \
      --uri="$uri" \
      --http-method=POST \
      --oauth-service-account-email="$SCHED_SA" \
      --time-zone="$TZ" \
      --quiet
  else
    gcloud scheduler jobs create http "$sched_name" \
      --location="$REGION" \
      --schedule="$cron" \
      --uri="$uri" \
      --http-method=POST \
      --oauth-service-account-email="$SCHED_SA" \
      --time-zone="$TZ" \
      --quiet
  fi
}

pause_scheduler() {
  local sched_name="$1"
  if gcloud scheduler jobs describe "$sched_name" --location="$REGION" &>/dev/null; then
    gcloud scheduler jobs pause "$sched_name" --location="$REGION" --quiet || true
  fi
}

log "Cloud Run service: ikr-streamlit"
AUTH_FLAG="--no-allow-unauthenticated"
if [[ "${STREAMLIT_PUBLIC:-0}" == "1" ]]; then
  AUTH_FLAG="--allow-unauthenticated"
fi

gcloud run deploy ikr-streamlit \
  --image="$IMG" \
  --region="$REGION" \
  --service-account="$SA" \
  --set-env-vars="${ENV_VARS},GCS_SYNC_INTERVAL_SEC=300" \
  --port=18501 \
  --memory=512Mi \
  --cpu=1 \
  --min-instances="${STREAMLIT_MIN_INSTANCES:-0}" \
  --timeout=3600 \
  $AUTH_FLAG \
  --quiet

STREAMLIT_URL="$(gcloud run services describe ikr-streamlit --region="$REGION" --format='value(status.url)')"
log "Streamlit URL: $STREAMLIT_URL"

# Cloud Run Jobs (one script each)
deploy_job ikr-telegram-poll scripts/run_telegram_poll.py
deploy_job ikr-morning-reminder scripts/run_morning_reminder.py
deploy_job ikr-evening-nudge scripts/run_evening_nudge.py
deploy_job ikr-mid-month scripts/run_mid_month.py
deploy_job ikr-end-month scripts/run_end_month.py

# Default Cloud Scheduler crons (Asia/Kolkata via TZ in config.env).
# Admin Save updates these via cloud_scheduler_sync — no redeploy needed for time changes.
schedule_job ikr-telegram-poll-schedule "*/15 * * * *" ikr-telegram-poll
schedule_job ikr-morning-reminder-schedule "30 11 * * *" ikr-morning-reminder
schedule_job ikr-evening-nudge-schedule "0 18 * * *" ikr-evening-nudge
pause_scheduler ikr-evening-nudge-schedule
schedule_job ikr-mid-month-schedule "30 11 15 * *" ikr-mid-month
schedule_job ikr-end-month-schedule "30 11 28-31 * *" ikr-end-month

# Retire legacy combined scheduler if present
if gcloud scheduler jobs describe ikr-scheduler-schedule --location="$REGION" &>/dev/null; then
  log "Pausing legacy ikr-scheduler-schedule (replaced by split jobs)"
  gcloud scheduler jobs pause ikr-scheduler-schedule --location="$REGION" --quiet || true
fi

echo ""
log "Deployment complete."
echo "  Streamlit:  $STREAMLIT_URL"
echo "  Telegram:   every 15 min (ikr-telegram-poll-schedule)"
echo "  Morning:    11:30 $TZ default — change in Admin → Save (updates Cloud Scheduler)"
echo "  Streamlit:  pulls ikr.db from GCS every 5 min; pushes only on UI saves"
echo ""
echo "After deploy: open Admin → Settings → Save once to sync schedules from your DB."
echo ""
echo "Manual job run:"
echo "  gcloud run jobs execute ikr-telegram-poll --region=$REGION --wait"
