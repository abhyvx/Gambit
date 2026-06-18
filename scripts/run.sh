#!/bin/bash
# Start Bet Placer API + frontend dev server

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Backend
source .venv/bin/activate
pip install -e . -q
echo "Starting API on http://127.0.0.1:8000"
python -c "from bet_placer.api.server import run_server; run_server()" &
API_PID=$!

# Frontend
cd frontend
if [ ! -d node_modules ]; then
  echo "Installing frontend dependencies..."
  npm install
fi
echo "Starting frontend on http://127.0.0.1:5173"
npm run dev &
WEB_PID=$!

trap "kill $API_PID $WEB_PID 2>/dev/null" EXIT

echo ""
echo "  Dashboard: http://127.0.0.1:5173"
echo "  API docs:  http://127.0.0.1:8000/docs"
echo ""
wait
