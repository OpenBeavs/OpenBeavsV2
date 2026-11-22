#!/bin/bash
# Reuse the shared launcher to run all four services in this terminal.
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

for folder in agent-registry chat-system/conversation-agent backend; do
    if [[ ! -x "$folder/.venv/bin/python" ]]; then
        printf '%s\n' "Environment missing. Run uv sync --locked --python 3.12 from $folder/ first." >&2
        exit 1
    fi
done

export DATABASE_URL='sqlite:///./openbeavs.db'
exec backend/.venv/bin/python start-dev.py
