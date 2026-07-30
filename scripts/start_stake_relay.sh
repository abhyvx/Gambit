#!/bin/bash
# One-shot Stake → Render push. Does NOT leave a terminal loop running.
# For scheduled updates without a 24/7 process: ./scripts/install_stake_relay_agent.sh
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
[ -f .env ] && set -a && source .env && set +a

export STAKE_USE_BROWSER=true
export STAKE_BROWSER_HEADLESS="${STAKE_BROWSER_HEADLESS:-false}"
if [ -z "${STAKE_RELAY_SECRET:-}" ]; then
  echo "Set STAKE_RELAY_SECRET before starting the Stake relay." >&2
  exit 1
fi
export GAMBIT_CLOUD_URL="${GAMBIT_CLOUD_URL:-https://gambit-yqng.onrender.com}"
export STAKE_UPLOAD_RELEASE="${STAKE_UPLOAD_RELEASE:-1}"
export STAKE_SKIP_ESPN="${STAKE_SKIP_ESPN:-1}"
GAMBIT_CLOUD_URL="$(echo "$GAMBIT_CLOUD_URL" | tr -d '[:space:]')"
export GAMBIT_CLOUD_URL

if [ -z "$GAMBIT_CLOUD_URL" ] || echo "$GAMBIT_CLOUD_URL" | grep -q YOUR-SERVICE; then
  echo "Set GAMBIT_CLOUD_URL in .env to your Render URL"
  exit 1
fi

source .venv/bin/activate 2>/dev/null || true
echo "One-shot Stake push → $GAMBIT_CLOUD_URL"
echo "Chrome may open once for Cloudflare — finish the check, then this script exits."
echo "For every-10-min updates without a terminal: ./scripts/install_stake_relay_agent.sh"
PYTHONPATH=src python3 scripts/push_stake_cache.py
echo "Done. No background process left running."
