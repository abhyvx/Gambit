#!/bin/bash
# Legacy installer — scheduled LaunchAgent is retired (it kept popping Chrome).
# This script uninstalls any old agent and points you at on-demand sync.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "Scheduled Stake LaunchAgent is disabled (caused repeated Chrome popups)."
"$ROOT/scripts/uninstall_stake_relay_agent.sh"
echo
echo "Use on-demand instead:"
echo "  1. ./scripts/start_stake_relay.sh   # leave this terminal open (idle, no Chrome)"
echo "  2. Admin → Sync Stake odds now     # scrapes only when you click"
echo "  3. If Cloudflare appears, finish it in the Stake window, leave that tab/window alone"
echo
echo "Optional: Portfolio → paste Stake API token (no laptop Chrome)."
exit 0
