#!/bin/bash
# Unload and remove the macOS LaunchAgent that kept opening Stake Chrome.
set -e
LABEL="com.gambit.stake-relay"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
UID_NUM="$(id -u)"

if [ -f "$PLIST" ]; then
  launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
  launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Removed $PLIST — Stake Chrome will no longer open on a timer."
else
  echo "No LaunchAgent at $PLIST (already gone)."
fi

# Stop a stray listener if the user left one running in the background.
pkill -f 'scripts/stake_relay.py' 2>/dev/null || true
pkill -f 'scripts/push_stake_cache.py' 2>/dev/null || true

if launchctl list 2>/dev/null | grep -q "$LABEL"; then
  echo "Still listed in launchctl — reboot or: launchctl bootout gui/$UID_NUM/$LABEL"
  exit 1
fi

echo "Uninstalled $LABEL. Chrome should no longer open on a timer."
echo "Logs (left in place): ~/Library/Logs/gambit-stake-relay.log"
echo "On-demand sync: ./scripts/start_stake_relay.sh"
echo "Then Admin → Sync Stake odds now (only scrapes when you click)."
