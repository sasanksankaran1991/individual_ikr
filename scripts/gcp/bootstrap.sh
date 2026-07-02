#!/usr/bin/env bash
# One-time GCP setup for individual_ikr (new GCP project).
# Usage (from repo root): bash scripts/gcp/bootstrap.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/gcp/_lib.sh"

require_gcloud
load_config

log "Project: $GCP_PROJECT_ID  Region: $GCP_REGION  Secret prefix: ${GCP_SECRET_PREFIX}"

gcloud config set project "$GCP_PROJECT_ID"

log "Enabling APIs..."
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  cloudscheduler.googleapis.com \
  storage.googleapis.com \
  --project="$GCP_PROJECT_ID"

if ! gcloud artifacts repositories describe "$AR_REPO" \
  --location="$GCP_REGION" --project="$GCP_PROJECT_ID" &>/dev/null; then
  log "Creating Artifact Registry repo: $AR_REPO"
  gcloud artifacts repositories create "$AR_REPO" \
    --repository-format=docker \
    --location="$GCP_REGION" \
    --description="Individual IKR Docker images"
else
  log "Artifact Registry repo exists: $AR_REPO"
fi

if ! gcloud storage buckets describe "gs://${GCS_DATA_BUCKET}" &>/dev/null; then
  log "Creating GCS bucket: $GCS_DATA_BUCKET"
  gcloud storage buckets create "gs://${GCS_DATA_BUCKET}" \
    --project="$GCP_PROJECT_ID" \
    --location="$GCP_REGION" \
    --uniform-bucket-level-access
else
  log "GCS bucket exists: $GCS_DATA_BUCKET"
fi

RUNNER_EMAIL="${RUNNER_SA}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
SCHEDULER_EMAIL="${SCHEDULER_SA}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"

for sa in "$RUNNER_SA" "$SCHEDULER_SA"; do
  if ! gcloud iam service-accounts describe "${sa}@${GCP_PROJECT_ID}.iam.gserviceaccount.com" \
    --project="$GCP_PROJECT_ID" &>/dev/null; then
    log "Creating service account: $sa"
    gcloud iam service-accounts create "$sa" \
      --project="$GCP_PROJECT_ID" \
      --display-name="$sa"
  fi
done

log "Granting IAM to runner SA..."
for role in secretmanager.secretAccessor secretmanager.secretVersionAdder; do
  gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
    --member="serviceAccount:${RUNNER_EMAIL}" \
    --role="roles/${role}" \
    --condition=None \
    --quiet >/dev/null
done

gcloud storage buckets add-iam-policy-binding "gs://${GCS_DATA_BUCKET}" \
  --member="serviceAccount:${RUNNER_EMAIL}" \
  --role="roles/storage.objectAdmin" \
  --quiet >/dev/null

PROJECT_NUMBER="$(gcloud projects describe "$GCP_PROJECT_ID" --format='value(projectNumber)')"
CB_SA="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"
gcloud artifacts repositories add-iam-policy-binding "$AR_REPO" \
  --location="$GCP_REGION" \
  --member="serviceAccount:${CB_SA}" \
  --role="roles/artifactregistry.writer" \
  --quiet >/dev/null

gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
  --member="serviceAccount:${SCHEDULER_EMAIL}" \
  --role="roles/run.invoker" \
  --condition=None \
  --quiet >/dev/null

log "Granting Cloud Scheduler admin to runner SA (Admin Save syncs schedules)..."
gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
  --member="serviceAccount:${RUNNER_EMAIL}" \
  --role="roles/cloudscheduler.admin" \
  --condition=None \
  --quiet >/dev/null

log "Creating Secret Manager shell: ${GCP_SECRET_PREFIX}telegram-bot-token"
sid="${GCP_SECRET_PREFIX}telegram-bot-token"
if gcloud secrets describe "$sid" --project="$GCP_PROJECT_ID" &>/dev/null; then
  log "  secret exists: $sid"
else
  gcloud secrets create "$sid" \
    --project="$GCP_PROJECT_ID" \
    --replication-policy=automatic \
    --quiet
  log "  created: $sid"
fi

log "Bootstrap complete."
echo ""
echo "Next steps (from repo root):"
echo "  1. Upload secrets:  GOOGLE_CLOUD_PROJECT=$GCP_PROJECT_ID python scripts/push_secrets_to_gcp.py"
echo "  2. Upload data:     bash scripts/gcp/upload-data.sh"
echo "  3. Build image:     bash scripts/gcp/build.sh"
echo "  4. Deploy:          bash scripts/gcp/deploy.sh"
