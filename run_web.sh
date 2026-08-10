#!/usr/bin/env bash
# Launcher for the Bale "Read Later" web dashboard (Flask).
#
# Run directly:
#   ./run_web.sh
#   ./run_web.sh --port 9000
# Or as a systemd service (see readlater-web.service):
#   sudo systemctl start readlater-web
set -euo pipefail
cd "$(dirname "$0")"

VENV_PY=.venv/bin/python
if [ ! -x "$VENV_PY" ]; then
    echo "Virtualenv not found. Set it up first:" >&2
    echo "  uv venv" >&2
    echo "  uv pip install -r requirements.txt" >&2
    exit 1
fi

# Secrets (BALE_TOKEN, ADMIN_USER_ID, WEB_SECRET) are read from ./.env by the app.
exec "$VENV_PY" webapp.py "$@"