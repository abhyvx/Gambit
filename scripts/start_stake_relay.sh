#!/bin/bash
# Push Stake odds from your laptop to cloud. Secret is preconfigured - set GAMBIT_CLOUD_URL only.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
[ -f .env ] && set -a && source .env && set +a

export STAKE_USE_BROWSER=true
export STAKE_RELAY_SECRET="${STAKE_RELAY_SECRET:-gambit-relay-v1-abhyvx}"

if [ -z "${GAMBIT_CLOUD_URL:-}" ]; then
  echo "Add GAMBIT_CLOUD_URL=https://YOUR-SERVICE.onrender.com to .env"
  exit 1
fi

source .venv/bin/activate 2>/dev/null || true
PYTHONPATH=src python3 scripts/stake_relay.py
