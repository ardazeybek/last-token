#!/usr/bin/env bash
# autoinstall.sh — SessionStart hook: installs last-token once into code projects under ~/PROJECTS/
# and keeps their .ctx/ctx.py copy (and the global-mode copy) up to date with this repo. Never fails or blocks the session.
# Opt out per project: touch <project>/.no-last-token
repo="$HOME/PROJECTS/Last Token"
log="$HOME/.claude/last-token/autoinstall.log"
d="${CLAUDE_PROJECT_DIR:-$PWD}"

# Global mode: keep the user-level copy of ctx.py current with this repo (every session, any folder).
if [ -f "$HOME/.claude/last-token/global.json" ] && [ -f "$repo/system/ctx.py" ] && \
   ! cmp -s "$repo/system/ctx.py" "$HOME/.claude/last-token/ctx.py"; then
  cp "$repo/system/ctx.py" "$HOME/.claude/last-token/ctx.py" 2>/dev/null && echo "$(date '+%F %T') updated global ctx.py" >> "$log"
fi

# Only projects directly under ~/PROJECTS (never ~/PROJECTS itself), never this repo.
case "$d" in "$HOME/PROJECTS/"*) ;; *) exit 0;; esac
case "$d" in "$repo"*) exit 0;; esac
name="$(echo "${d#$HOME/PROJECTS/}" | cut -d/ -f1)"
[ -n "$name" ] || exit 0
top="$HOME/PROJECTS/$name"
[ -d "$top" ] || exit 0
[ -f "$top/.no-last-token" ] && exit 0
[ -f "$repo/system/ctx.py" ] || exit 0

# Installed already: when the repo has a newer ctx.py, re-run init (copies it and migrates old settings).
if [ -d "$top/.ctx" ]; then
  if ! cmp -s "$repo/system/ctx.py" "$top/.ctx/ctx.py"; then
    python3 "$repo/system/ctx.py" init "$top" >/dev/null 2>&1 && echo "$(date '+%F %T') updated $top" >> "$log"
  fi
  exit 0
fi

# Install only into code projects (a repo or a known project file), not folders of notes or media.
code=0
[ -d "$top/.git" ] && code=1
for f in package.json pyproject.toml setup.py requirements.txt Cargo.toml go.mod CMakeLists.txt Makefile \
         build.gradle pom.xml composer.json Gemfile pubspec.yaml ProjectSettings meson.build; do
  [ -e "$top/$f" ] && code=1
done
[ "$code" = 1 ] || exit 0

python3 "$repo/system/ctx.py" init "$top" >/dev/null 2>&1 || exit 0
[ -d "$top/.git" ] && ! grep -qx '.ctx/archive/' "$top/.gitignore" 2>/dev/null && printf '.ctx/archive/\n.ctx/out/\n' >> "$top/.gitignore"
echo "$(date '+%F %T') installed $top" >> "$log"
echo "last-token installed in $top (active from the next session)"
exit 0
