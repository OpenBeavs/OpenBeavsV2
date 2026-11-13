#!/bin/bash
# Reuse the shared launcher to run all four services in this terminal.
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if [[ ! -x backend/.venv/bin/python ]]; then
    printf '%s\n' 'Backend environment missing. Run uv sync --locked --python 3.12 from backend/ first.' >&2
    exit 1
fi

export DATABASE_URL='sqlite:///./openbeavs.db'
exec backend/.venv/bin/python start-dev.py
