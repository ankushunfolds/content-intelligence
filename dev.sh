#!/usr/bin/env bash
# Start the API and the frontend together. Ctrl-C stops both.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

VENV="$ROOT/backend/.venv"
STAMP="$VENV/.deps-installed"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "created .env from .env.example"
fi

set -a; source .env; set +a

# --- Backend ---------------------------------------------------------------
# The stamp file matters: if a previous run created the venv but the install
# failed, checking only for the directory would skip straight to launching a
# uvicorn that isn't there.
if [ ! -f "$STAMP" ]; then
  if [ ! -d "$VENV" ]; then
    echo "creating backend virtualenv…"
    python3 -m venv "$VENV"
  fi

  echo "installing backend dependencies…"
  "$VENV/bin/pip" install -q --upgrade pip
  if ! "$VENV/bin/pip" install -q -r backend/requirements.txt; then
    echo
    echo "Backend install failed. Clear the partial virtualenv and retry:"
    echo "  rm -rf \"$VENV\" && ./dev.sh"
    exit 1
  fi

  # Optional: enables uvicorn --reload. Not worth failing the run over.
  "$VENV/bin/pip" install -q watchfiles 2>/dev/null || true

  touch "$STAMP"
fi

# --- Frontend --------------------------------------------------------------
if [ ! -d frontend/node_modules ]; then
  echo "installing frontend dependencies…"
  (cd frontend && npm install --no-audit --no-fund)
fi

# --- Run -------------------------------------------------------------------
RELOAD=""
if "$VENV/bin/python" -c "import watchfiles" 2>/dev/null; then
  RELOAD="--reload"
fi

cleanup() { kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo
echo "api      → http://localhost:8000  (docs at /docs)"
echo "frontend → http://localhost:3000"
echo

(cd "$ROOT/backend" && "$VENV/bin/uvicorn" app.main:app --port 8000 $RELOAD) &
(cd "$ROOT/frontend" && npm run dev) &

wait
