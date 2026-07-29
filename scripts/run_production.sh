#!/bin/bash
# Production: built frontend + API on one port. Craft trains on GitHub Actions only.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ -f .env ]; then set -a; source .env; set +a; fi

export CRAFT_DISABLE=1
export STAKE_USE_BROWSER="${STAKE_USE_BROWSER:-false}"
export STAKE_BROWSER_WARMUP_ON_STARTUP=false
export GAMBIT_FRONTEND_DIST="$ROOT/frontend/dist"
export GAMBIT_HOST="${GAMBIT_HOST:-0.0.0.0}"
export GAMBIT_PORT="${GAMBIT_PORT:-8080}"

source .venv/bin/activate
pip install -e . -q

echo "Building frontend…"
cd frontend
if [ ! -d node_modules ]; then npm ci; fi
npm run build
cd "$ROOT"

echo "Starting Gambit on http://${GAMBIT_HOST}:${GAMBIT_PORT}"
PYTHONPATH=src uvicorn bet_placer.api.server:app --host "$GAMBIT_HOST" --port "$GAMBIT_PORT"
