#!/bin/bash
# Pull latest trained model from GitHub Releases (published by craft-train workflow).
set -euo pipefail
DEST="${BET_PLACER_HOME:-$HOME/.bet_placer}"
REPO="${GAMBIT_REPO:-abhyvx/Gambit}"
TAG="${GAMBIT_MODEL_TAG:-model-latest}"
mkdir -p "$DEST"
# Compat: any leftover Path.home()/.bet_placer callers still hit DEST
if [ -n "${HOME:-}" ] && [ "$DEST" != "$HOME/.bet_placer" ]; then
  ln -sfn "$DEST" "$HOME/.bet_placer" 2>/dev/null || true
fi

NEED_REFRESH=0
for name in craft.db model_params.json craft_nn.joblib; do
  [ -f "$DEST/$name" ] || NEED_REFRESH=1
done
# Always refresh betting snapshot when missing (monthly charts)
[ -f "$DEST/betting_evolution.db" ] || NEED_REFRESH=1
# Stake overlay from last push (survives redeploy)
[ -f "$DEST/stake_overlay_cache.json" ] || NEED_REFRESH=1
# Portfolio journal from last sync (cloud-compatible without live Chrome)
[ -f "$DEST/portfolio_state.json" ] || NEED_REFRESH=1
# Model desk cache + factor graph (charts / factor box)
[ -f "$DEST/model_insights_cache.json" ] || NEED_REFRESH=1
[ -f "$DEST/factor_store.json" ] || NEED_REFRESH=1

if [ "$NEED_REFRESH" = "0" ]; then
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

for name in craft.db model_params.json craft_nn.joblib betting_evolution.db stake_overlay_cache.json portfolio_state.json model_insights_cache.json factor_store.json; do
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
