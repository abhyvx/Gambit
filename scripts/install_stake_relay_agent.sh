#!/bin/bash
# Install a macOS LaunchAgent that pushes Stake → Render every 10 minutes.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.gambit.stake-relay"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PYTHON="$ROOT/.venv/bin/python3"
[ -x "$PYTHON" ] || PYTHON="$(command -v python3)"
[ -n "${STAKE_RELAY_SECRET:-}" ] || { echo "Set STAKE_RELAY_SECRET before installing the relay agent." >&2; exit 1; }
[ -n "${GAMBIT_CLOUD_URL:-}" ] || { echo "Set GAMBIT_CLOUD_URL before installing the relay agent." >&2; exit 1; }

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON</string>
    <string>$ROOT/scripts/push_stake_cache.py</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONPATH</key><string>$ROOT/src</string>
    <key>STAKE_USE_BROWSER</key><string>true</string>
    <key>STAKE_RELAY_SECRET</key><string>${STAKE_RELAY_SECRET}</string>
    <key>GAMBIT_CLOUD_URL</key><string>${GAMBIT_CLOUD_URL}</string>
    <key>STAKE_UPLOAD_RELEASE</key><string>1</string>
    <key>STAKE_BROWSER_HEADLESS</key><string>false</string>
    <key>STAKE_SKIP_ESPN</key><string>1</string>
    <key>PATH</key><string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
  </dict>
  <key>StartInterval</key><integer>600</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/gambit-stake-relay.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/gambit-stake-relay.err</string>
</dict>
</plist>
EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Installed $PLIST — runs every 10 min."
echo "First time: run ./scripts/start_stake_relay.sh once and finish Cloudflare in Chrome."
echo "Logs: ~/Library/Logs/gambit-stake-relay.log"
