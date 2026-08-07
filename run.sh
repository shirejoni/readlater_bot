#!/usr/bin/env bash
# Launcher for the Bale "Read Later" bot.
#
# Run it directly:
#   ./run.sh
# Or as a systemd service (see readlater-bot.service):
#   sudo systemctl start readlater-bot
set -euo pipefail
cd "$(dirname "$0")"

# Use the project's virtualenv (created with `uv`).
VENV_PY=.venv/bin/python
if [ ! -x "$VENV_PY" ]; then
    echo "Virtualenv not found. Set it up first:" >&2
    echo "  uv venv" >&2
    echo "  uv pip install -r requirements.txt" >&2
    exit 1
fi

# Secrets (BALE_TOKEN, ADMIN_USER_ID) are read from ./.env by the app itself.
exec "$VENV_PY" bot.py
