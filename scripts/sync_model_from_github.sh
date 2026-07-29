#!/bin/bash
# Pull latest craft training artifact from GitHub Actions into ~/.bet_placer
set -euo pipefail
REPO="${GAMBIT_REPO:-abhyvx/gambit}"
DEST="${BET_PLACER_HOME:-$HOME/.bet_placer}"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$DEST"
echo "Downloading bet-placer-model-state from $REPO…"
gh run download -R "$REPO" --name bet-placer-model-state -D "$TMP"
for f in craft.db model_params.json craft_nn.joblib; do
  if [ -f "$TMP/$f" ]; then
    cp "$TMP/$f" "$DEST/$f"
    echo "  → $DEST/$f"
  fi
done
echo "Done. Restart API if running."
