#!/bin/bash
set -e
cd /app
bash scripts/bootstrap_model.sh
exec uvicorn bet_placer.api.server:app --host "${GAMBIT_HOST:-0.0.0.0}" --port "${GAMBIT_PORT:-10000}"
