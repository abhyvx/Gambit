#!/bin/bash
# Cloud entrypoint: bind Render's PORT immediately, then bootstrap in the background.
# "No open ports detected" happens when bootstrap/downloads block before uvicorn listens.
set -u
cd /app

PORT="${PORT:-${GAMBIT_PORT:-10000}}"
export PORT
export GAMBIT_HOST=0.0.0.0
export GAMBIT_PORT="$PORT"
export PYTHONUNBUFFERED=1

echo "gambit: listening on 0.0.0.0:${PORT}"

# Model/release pull must never delay the open port.
(
  set +e
  echo "gambit: background bootstrap starting…"
  bash scripts/bootstrap_model.sh
  echo "gambit: background bootstrap finished (exit $?)"
) &

exec uvicorn bet_placer.api.server:app \
  --host 0.0.0.0 \
  --port "$PORT" \
  --timeout-keep-alive 5 \
  --log-level info
