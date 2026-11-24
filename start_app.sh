#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
echo "========================================================"
echo " Launching CAD Serviceability Assessment System..."
echo "========================================================"

# Prewarm persistent analysis cache
echo "[0/3] Prewarming cache with sample models..."
python -m backend.app.scripts.prewarm || true

# 1. Start FastAPI Backend
echo "[1/3] Starting Backend API (http://127.0.0.1:8000)..."
(cd "$DIR/backend" && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000) &
BACKEND_PID=$!

# 2. Start Vite Frontend
echo "[2/3] Starting Frontend Dev Server (http://127.0.0.1:5173)..."
(cd "$DIR/frontend" && npm run dev) &
FRONTEND_PID=$!

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT

echo "[3/3] Application running at http://localhost:5173"
echo "Press Ctrl+C to terminate all services."
wait
