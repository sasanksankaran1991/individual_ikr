#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

require_gcloud() {
  if ! command -v gcloud >/dev/null 2>&1; then
    echo "Install Google Cloud SDK: https://cloud.google.com/sdk/docs/install" >&2
    exit 1
  fi
}

load_config() {
  CONFIG_FILE="${CONFIG_FILE:-$ROOT/scripts/gcp/config.env}"
  if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "Missing $CONFIG_FILE — copy scripts/gcp/config.env.example to scripts/gcp/config.env" >&2
    exit 1
  fi
  # shellcheck source=/dev/null
  source <(sed 's/\r$//' "$CONFIG_FILE")
  : "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID in config.env}"
  : "${GCP_REGION:?Set GCP_REGION in config.env}"
  : "${GCS_DATA_BUCKET:?Set GCS_DATA_BUCKET in config.env}"
  : "${AR_REPO:?Set AR_REPO in config.env}"
  IKR_IMAGE="${IKR_IMAGE:-individual-ikr}"
  RUNNER_SA="${RUNNER_SA:-ikr-runner}"
  SCHEDULER_SA="${SCHEDULER_SA:-ikr-scheduler}"
  TZ="${TZ:-Asia/Kolkata}"
  USE_SECRET_MANAGER="${USE_SECRET_MANAGER:-1}"
  GCP_SECRET_PREFIX="${GCP_SECRET_PREFIX:-ikr-}"
  IKR_SCHEDULER_CRON="${IKR_SCHEDULER_CRON:-0 */3 * * *}"
}

image_uri() {
  echo "${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/${AR_REPO}/${IKR_IMAGE}:latest"
}

runner_sa_email() {
  echo "${RUNNER_SA}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
}

scheduler_sa_email() {
  echo "${SCHEDULER_SA}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
}

common_env() {
  printf 'GOOGLE_CLOUD_PROJECT=%s,USE_SECRET_MANAGER=%s,GCS_DATA_BUCKET=%s,TZ=%s,GCP_SECRET_PREFIX=%s,IKR_USE_CLOUD_SCHEDULER=1' \
    "$GCP_PROJECT_ID" "$USE_SECRET_MANAGER" "$GCS_DATA_BUCKET" "$TZ" "$GCP_SECRET_PREFIX"
}

log() {
  echo "==> $*"
}
