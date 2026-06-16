#!/usr/bin/env bash
# Run Telegram poll loop (Mac/Linux). Keep terminal open or use systemd/launchd.
cd "$(dirname "$0")/.."
if [ -f .venv/bin/python ]; then
  exec .venv/bin/python scripts/poll_loop.py
else
  exec python3 scripts/poll_loop.py
fi
