#!/bin/bash
# Keep Stake odds flowing to Render from THIS laptop (Cloudflare works here).
# First run: a Chrome window may open — finish the "Just a moment…" check, then leave this running.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
[ -f .env ] && set -a && source .env && set +a

export STAKE_USE_BROWSER=true
export STAKE_RELAY_SECRET="${STAKE_RELAY_SECRET:-gambit-relay-v1-abhyvx}"
export GAMBIT_CLOUD_URL="${GAMBIT_CLOUD_URL:-https://gambit-yqng.onrender.com}"
# After a good push, seed GitHub release so Render bootstrap survives redeploys
export STAKE_UPLOAD_RELEASE="${STAKE_UPLOAD_RELEASE:-1}"
# strip accidental spaces
GAMBIT_CLOUD_URL="$(echo "$GAMBIT_CLOUD_URL" | tr -d '[:space:]')"
export GAMBIT_CLOUD_URL

if [ -z "$GAMBIT_CLOUD_URL" ] || echo "$GAMBIT_CLOUD_URL" | grep -q YOUR-SERVICE; then
  echo "Set GAMBIT_CLOUD_URL in .env to your Render URL"
  exit 1
fi

source .venv/bin/activate 2>/dev/null || true
echo "Pushing Stake → $GAMBIT_CLOUD_URL (every ${STAKE_RELAY_INTERVAL:-300}s)"
echo "If Chrome opens: complete Cloudflare once, do not close the profile window."
PYTHONPATH=src python3 scripts/push_stake_cache.py || true
PYTHONPATH=src python3 scripts/stake_relay.py
