#!/usr/bin/env bash
# Deploy Cloud Run service (Streamlit) + scheduler Cloud Run Job (every 3 hours).
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
    --command=python
    --args="$script_path"
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

deploy_job ikr-scheduler scripts/run_scheduled_tick.py
schedule_job ikr-scheduler-schedule "$IKR_SCHEDULER_CRON" ikr-scheduler

echo ""
log "Deployment complete."
echo "  Streamlit:   $STREAMLIT_URL"
echo "  Scheduler:   every 3 hours ($IKR_SCHEDULER_CRON $TZ) → ikr-scheduler job"
echo ""
echo "Manual scheduler run:"
echo "  gcloud run jobs execute ikr-scheduler --region=$REGION --wait"
