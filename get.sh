#!/usr/bin/env bash
# get.sh — one-line installer: downloads Last Token into ~/.claude/last-token/src and turns it on globally.
#   curl -fsSL https://raw.githubusercontent.com/ardazeybek/last-token/master/get.sh | bash
set -euo pipefail
REPO="https://github.com/ardazeybek/last-token.git"
SRC="$HOME/.claude/last-token/src"

# Requirements
for c in git python3; do command -v "$c" >/dev/null || { echo "✗ '$c' is required (install it, then re-run)" >&2; exit 1; }; done
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || { echo "✗ python 3.9+ is required" >&2; exit 1; }

# Download (or update)
mkdir -p "$HOME/.claude/last-token"
if [ -d "$SRC/.git" ]; then git -C "$SRC" pull -q --ff-only; else git clone -q --depth 1 "$REPO" "$SRC"; fi

# Install for every Claude Code session, tuned to this user's own usage, then verify
bash "$SRC/install.sh" --global >/dev/null
python3 "$HOME/.claude/last-token/ctx.py" doctor
