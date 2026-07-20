#!/bin/zsh
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p "$HOME/.wife-signal/logs"
set -a
source .env
set +a
exec .venv/bin/python3 server.py
