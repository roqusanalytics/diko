#!/bin/bash
# Diko auto-start script for macOS Launch Agent
# Starts backend (FastAPI) and frontend (Vite) servers

DIKO_DIR="$HOME/Claude darbbinis/diko"
LOG_DIR="$HOME/.diko/logs"
mkdir -p "$LOG_DIR"

echo "$(date) — Starting Diko..." >> "$LOG_DIR/startup.log"

# Kill any existing instances
lsof -ti:8000 | xargs kill 2>/dev/null
lsof -ti:5173 | xargs kill 2>/dev/null
sleep 1

# Start backend
cd "$DIKO_DIR/backend"
$HOME/.local/bin/uv run uvicorn main:app --host 0.0.0.0 --port 8000 \
  >> "$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
echo "$(date) — Backend started (PID $BACKEND_PID)" >> "$LOG_DIR/startup.log"

# Start frontend
cd "$DIKO_DIR/frontend"
$HOME/.bun/bin/bun run dev -- --host 0.0.0.0 \
  >> "$LOG_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!
echo "$(date) — Frontend started (PID $FRONTEND_PID)" >> "$LOG_DIR/startup.log"

# Save PIDs for stop script
echo "$BACKEND_PID" > "$LOG_DIR/backend.pid"
echo "$FRONTEND_PID" > "$LOG_DIR/frontend.pid"

echo "$(date) — Diko running at http://localhost:5173" >> "$LOG_DIR/startup.log"

# Wait for both
wait
