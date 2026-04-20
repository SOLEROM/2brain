#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ -f .env ]]; then
    set -a
    source .env
    set +a
fi

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    echo "Warning: ANTHROPIC_API_KEY is not set. Digest and research features will not work."
fi

HOST="127.0.0.1"
if [[ "${1:-}" == "--public" ]]; then
    HOST="0.0.0.0"
fi

echo "Starting 2brain web UI at http://${HOST}:5000"
python -m uvicorn src.web.app:get_app --factory --host "$HOST" --port 5000 --reload
