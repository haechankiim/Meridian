#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="$ROOT_DIR/.meridian-dev"
BACKEND_PID_FILE="$STATE_DIR/backend.pid"
BACKEND_PORT=8000
FRONTEND_PORT=3000
POSTGRES_SERVICE="postgresql@16"

mkdir -p "$STATE_DIR"

cleanup() {
  if [[ -f "$BACKEND_PID_FILE" ]]; then
    local backend_pid
    backend_pid="$(cat "$BACKEND_PID_FILE")"

    if kill -0 "$backend_pid" >/dev/null 2>&1; then
      kill "$backend_pid" >/dev/null 2>&1 || true
      wait "$backend_pid" 2>/dev/null || true
    fi

    rm -f "$BACKEND_PID_FILE"
  fi
}

require_command() {
  local command_name="$1"

  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Missing required command: $command_name"
    exit 1
  fi
}

require_file() {
  local file_path="$1"
  local hint="$2"

  if [[ ! -e "$file_path" ]]; then
    echo "$hint"
    exit 1
  fi
}

port_in_use() {
  local port="$1"
  lsof -iTCP:"$port" -sTCP:LISTEN -t >/dev/null 2>&1
}

trap cleanup INT TERM EXIT

require_command brew
require_command lsof
require_command npm
require_file "$ROOT_DIR/backend/.venv311/bin/python" "Backend venv not found at backend/.venv311. Create it first."
require_file "$ROOT_DIR/frontend/package.json" "Frontend package.json not found."
require_file "$ROOT_DIR/frontend/node_modules" "Frontend dependencies are missing. Run 'cd frontend && npm install' first."

if port_in_use "$BACKEND_PORT"; then
  echo "Port $BACKEND_PORT is already in use. Stop the existing backend first."
  exit 1
fi

if port_in_use "$FRONTEND_PORT"; then
  echo "Port $FRONTEND_PORT is already in use. Stop the existing frontend first."
  exit 1
fi

echo "Starting PostgreSQL service..."
brew services start "$POSTGRES_SERVICE" >/dev/null

echo "Starting backend on http://127.0.0.1:$BACKEND_PORT ..."
(
  cd "$ROOT_DIR"
  exec "$ROOT_DIR/backend/.venv311/bin/python" -m uvicorn backend.app.main:app --reload --port "$BACKEND_PORT"
) &
BACKEND_PID=$!
echo "$BACKEND_PID" > "$BACKEND_PID_FILE"

sleep 2

if ! kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
  echo "Backend failed to start."
  exit 1
fi

echo "Starting frontend on http://127.0.0.1:$FRONTEND_PORT ..."
echo "Press Ctrl+C to stop frontend and backend. Use ./dev-down.sh to stop PostgreSQL too."
cd "$ROOT_DIR/frontend"
npm run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT"
