#!/usr/bin/env bash
# Build and push Docker image via Cloud Build.
# Usage (from repo root): bash scripts/gcp/build.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/gcp/_lib.sh"

require_gcloud
load_config

gcloud config set project "$GCP_PROJECT_ID"

log "Submitting Cloud Build..."
gcloud builds submit "$ROOT" \
  --config="$ROOT/cloudbuild.yaml" \
  --project="$GCP_PROJECT_ID" \
  --substitutions="_REGION=${GCP_REGION},_AR_REPO=${AR_REPO},_IMAGE=${IKR_IMAGE}"

log "Image: $(image_uri)"
