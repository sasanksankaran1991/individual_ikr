#!/usr/bin/env bash
# Full first-time deploy. Usage (from repo root): bash scripts/gcp/setup-and-deploy.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

if [[ ! -f "$ROOT/scripts/gcp/config.env" ]]; then
  cp "$ROOT/scripts/gcp/config.env.example" "$ROOT/scripts/gcp/config.env"
  echo "Created scripts/gcp/config.env — edit GCP_PROJECT_ID and re-run." >&2
  exit 1
fi

bash "$ROOT/scripts/gcp/bootstrap.sh"
echo ""
echo "Upload secrets (creates ikr-* versions in Secret Manager):"
echo "  GOOGLE_CLOUD_PROJECT=\$(grep '^GCP_PROJECT_ID=' scripts/gcp/config.env | cut -d= -f2) python scripts/push_secrets_to_gcp.py"
echo ""
read -r -p "Press Enter after secrets are uploaded (or Ctrl+C to abort)..."

bash "$ROOT/scripts/gcp/upload-data.sh"
bash "$ROOT/scripts/gcp/build.sh"
bash "$ROOT/scripts/gcp/deploy.sh"
