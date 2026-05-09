#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ -f .env ]; then
    set -a
    . ./.env
    set +a
fi
exec .venv/bin/uvicorn app:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8765}"
