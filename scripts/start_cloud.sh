#!/bin/bash
set -e
cd /app
bash scripts/bootstrap_model.sh
# Render injects PORT — must listen on it (not a fixed 10000)
PORT="${PORT:-${GAMBIT_PORT:-10000}}"
exec uvicorn bet_placer.api.server:app --host 0.0.0.0 --port "$PORT"
