#!/usr/bin/env bash
# Upload local ikr.db to GCS (one-time before first deploy).
# Usage (from repo root): bash scripts/gcp/upload-data.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/gcp/_lib.sh"

require_gcloud
load_config

if [[ ! -f "$ROOT/ikr.db" ]]; then
  echo "Warning: $ROOT/ikr.db not found — run the app locally once or copy your DB" >&2
  exit 1
fi

gcloud storage cp "$ROOT/ikr.db" "gs://${GCS_DATA_BUCKET}/ikr.db"
log "Uploaded ikr.db to gs://${GCS_DATA_BUCKET}/"
