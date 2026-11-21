#!/usr/bin/env bash
# resume.sh — run one condition and keep resuming after rate limits / network stops:
#   bench/resume.sh <log> <run.py args...>   (waits 20 min between attempts, max 15)
set -u
log=$1; shift
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
args=("$@")
for i in $(seq 1 15); do
  python3 "$HERE/run.py" "${args[@]}" >> "$log" 2>&1
  steps=$(tail -n 1 "$log" | grep -oE 'resume with --steps [0-9]+-[0-9]+' | awk '{print $4}')
  [ -z "$steps" ] && exit 0
  echo "=== resume.sh: waiting 20 min, then --steps $steps (attempt $i)" >> "$log"
  sleep 1200
  # drop any previous --steps and append the new range
  clean=(); skip=0
  for a in "${args[@]}"; do
    if [ $skip = 1 ]; then skip=0; continue; fi
    [ "$a" = "--steps" ] && { skip=1; continue; }
    clean+=("$a")
  done
  args=("${clean[@]}" --steps "$steps")
done
