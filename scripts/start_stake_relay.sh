#!/bin/bash
# On-demand Stake → Render listener. Does NOT schedule LaunchAgent popups.
# Leave this terminal open while you use Admin; Chrome opens only on Sync click
# (or if Cloudflare needs a visible window).
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
[ -f .env ] && set -a && source .env && set +a

# Kill the old timer agent if still installed
if [ -f "$HOME/Library/LaunchAgents/com.gambit.stake-relay.plist" ]; then
  echo "Found old LaunchAgent — unloading so Chrome stops auto-opening…"
  "$ROOT/scripts/uninstall_stake_relay_agent.sh" || true
fi

export STAKE_USE_BROWSER=true
export STAKE_RELAY_MODE="${STAKE_RELAY_MODE:-on_demand}"
# Quiet by default; set STAKE_BROWSER_HEADLESS=false only if you want a visible window every sync
export STAKE_BROWSER_HEADLESS="${STAKE_BROWSER_HEADLESS:-true}"
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
echo "Starting on-demand Stake relay → $GAMBIT_CLOUD_URL"
echo "1) Leave this terminal open"
echo "2) Open Gambit Admin in your browser"
echo "3) Click Sync Stake odds now"
echo "4) If a Stake/Chrome window appears for Cloudflare, finish it and leave that window alone"
echo
PYTHONPATH=src python3 scripts/stake_relay.py
