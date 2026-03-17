#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="$ROOT_DIR/.meridian-dev"
BACKEND_PID_FILE="$STATE_DIR/backend.pid"
POSTGRES_SERVICE="postgresql@16"

if [[ -f "$BACKEND_PID_FILE" ]]; then
  BACKEND_PID="$(cat "$BACKEND_PID_FILE")"

  if kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
    echo "Stopping backend (PID $BACKEND_PID)..."
    kill "$BACKEND_PID" >/dev/null 2>&1 || true
    wait "$BACKEND_PID" 2>/dev/null || true
  fi

  rm -f "$BACKEND_PID_FILE"
fi

echo "Stopping PostgreSQL service..."
brew services stop "$POSTGRES_SERVICE" >/dev/null

echo "Meridian local services stopped."
