#!/bin/bash
# Pull latest trained model from GitHub Releases (published by craft-train workflow).
set -euo pipefail
DEST="${BET_PLACER_HOME:-$HOME/.bet_placer}"
REPO="${GAMBIT_REPO:-abhyvx/Gambit}"
TAG="${GAMBIT_MODEL_TAG:-model-latest}"
mkdir -p "$DEST"

if [ -f "$DEST/craft.db" ] && [ -f "$DEST/model_params.json" ]; then
  echo "model: using cached state in $DEST"
  exit 0
fi

echo "model: downloading $TAG from $REPO…"
API="https://api.github.com/repos/${REPO}/releases/tags/${TAG}"
JSON=$(curl -fsSL "$API" 2>/dev/null || true)
if [ -z "$JSON" ] || echo "$JSON" | grep -q '"message"'; then
  echo "model: no release yet — app runs; train via GitHub Actions"
  exit 0
fi

for name in craft.db model_params.json craft_nn.joblib; do
  URL=$(echo "$JSON" | python3 -c "
import json,sys
d=json.load(sys.stdin)
for a in d.get('assets',[]):
    if a.get('name')=='$name':
        print(a['browser_download_url']); break
" 2>/dev/null || true)
  if [ -n "$URL" ]; then
    curl -fsSL "$URL" -o "$DEST/$name"
    echo "  → $DEST/$name"
  fi
done
