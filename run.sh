#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    echo "Warning: ANTHROPIC_API_KEY is not set. Digest and research features will not work."
fi

echo "Starting 2brain web UI at http://127.0.0.1:5000"
python -m uvicorn src.web.app:get_app --factory --host 127.0.0.1 --port 5000 --reload
