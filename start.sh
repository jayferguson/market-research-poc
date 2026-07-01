#!/usr/bin/env bash
# Simple launcher (WSL/Linux/mac)
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate

if ! python -c "import openai" 2>/dev/null; then
  pip install -r requirements.txt
fi

python -m market_research.cli "$@"
