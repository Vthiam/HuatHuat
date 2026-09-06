#!/usr/bin/env bash
# One-command local dev: starts the backend and frontend together, and the
# frontend's dev server auto-opens the app in your browser (see
# frontend/vite.config.ts's server.open). Ctrl+C stops both.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT=8010

cleanup() {
  echo "Stopping backend and frontend..."
  kill "${BACKEND_PID:-}" "${FRONTEND_PID:-}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

(
  cd "$REPO_ROOT/backend"
  source venv/bin/activate
  exec uvicorn app.main:app --reload --port "$BACKEND_PORT"
) &
BACKEND_PID=$!

(
  cd "$REPO_ROOT/frontend"
  exec npm run dev
) &
FRONTEND_PID=$!

wait "$BACKEND_PID" "$FRONTEND_PID"
