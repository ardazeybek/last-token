#!/usr/bin/env bash
# install.sh — install last-token into a project:
#   ./install.sh [project-dir] [--pct 80] [--window 400000] [--base N] [--max]
#   ./install.sh --global   = last-token in EVERY Claude Code session (user settings + mod); --global off undoes it
#   --max = also the mod for this user (effort stays the user's choice: low effort made the model shallower)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }
if [ "${1:-}" = "--global" ]; then
  if [ "${2:-}" = "off" ]; then python3 "$HERE/system/ctx.py" global off; exit 0; fi
  python3 "$HERE/system/ctx.py" global on
  python3 "$HERE/system/ctx.py" mod install
  mkdir -p "$HOME/.claude/last-token" && cp "$HERE/system/autoinstall.sh" "$HOME/.claude/last-token/autoinstall.sh"
  exit 0
fi
args=(); max=0
for a in "$@"; do [ "$a" = "--max" ] && max=1 || args+=("$a"); done
[ ${#args[@]} -eq 0 ] && args=(.)
if [ $max = 1 ]; then
  python3 "$HERE/system/ctx.py" init "${args[@]}"
  python3 "$HERE/system/ctx.py" mod install
else
  python3 "$HERE/system/ctx.py" init "${args[@]}"
  echo "  tip: './install.sh <dir> --max' also adds the mod (smaller fixed base + savings pane)"
fi
