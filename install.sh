#!/usr/bin/env bash
# install.sh — install context-economy into a project: ./install.sh [project-dir] [--pct 25] [--window 200000]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }
python3 "$HERE/system/ctx.py" init "${@:-.}"
