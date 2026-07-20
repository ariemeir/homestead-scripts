#!/bin/zsh
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python3 ]; then
  python3 -m venv .venv
fi
.venv/bin/python3 -m pip install -q -r requirements.txt
set -a
source .env
set +a
exec .venv/bin/python3 server.py
