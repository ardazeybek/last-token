#!/usr/bin/env python3
"""usage_window.py — sum token usage of EVERY Claude Code session (all transcripts) in a time window.

usage: usage_window.py START [END]   (ISO times, e.g. 2026-11-21T03:50:00+03:00)
Prints per model: calls, input, output, cache read, cache write. Pairs with plan quota % read at
START and END to fit how the quota counts each token type (bench/quota_fit.py).
"""
import glob
import json
import os
import sys
from datetime import datetime


# ISO string → epoch seconds.
def ts(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


# Sum usage of assistant messages in [t0, t1), each API response counted once.
def window(t0: float, t1: float) -> dict:
    tot, seen = {}, set()
    for f in glob.glob(os.path.expanduser("~/.claude/projects/**/*.jsonl"), recursive=True):
        if os.path.getmtime(f) < t0:
            continue
        for line in open(f, errors="replace"):
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            m = d.get("message")
            if d.get("type") != "assistant" or not isinstance(m, dict) or not m.get("usage"):
                continue
            if not (t0 <= ts(d.get("timestamp", "1970-01-01T00:00:00Z")) < t1):
                continue
            key = (m.get("id"), d.get("requestId"))
            if key in seen:
                continue
            seen.add(key)
            u = m["usage"]
            r = tot.setdefault(m.get("model", "?"), {"n": 0, "in": 0, "out": 0, "cr": 0, "cw": 0})
            r["n"] += 1
            r["in"] += u.get("input_tokens", 0)
            r["out"] += u.get("output_tokens", 0)
            r["cr"] += u.get("cache_read_input_tokens", 0)
            r["cw"] += u.get("cache_creation_input_tokens", 0)
    return tot


if __name__ == "__main__":
    t1 = ts(sys.argv[2]) if len(sys.argv) > 2 else 9e18
    print(json.dumps(window(ts(sys.argv[1]), t1), indent=1))
