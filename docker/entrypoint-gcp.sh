#!/bin/sh
# Pull ikr.db from GCS before run; push back on exit (Cloud Run).
set -e

if [ -n "$GCS_DATA_BUCKET" ]; then
  echo "GCS sync: pulling from gs://${GCS_DATA_BUCKET}/ ..."
  if ! python /app/scripts/gcp/gcs_data_sync.py pull; then
    echo "GCS sync pull failed (check GCS_DATA_BUCKET and runner SA storage access)." >&2
  fi
  trap 'python /app/scripts/gcp/gcs_data_sync.py push || true' EXIT

  if [ -n "${GCS_SYNC_INTERVAL_SEC:-}" ] && [ "${1:-}" = "streamlit" ]; then
    (
      while true; do
        sleep "$GCS_SYNC_INTERVAL_SEC"
        python /app/scripts/gcp/gcs_data_sync.py push || true
      done
    ) &
  fi
fi

exec "$@"
