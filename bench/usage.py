#!/usr/bin/env python3
"""usage.py — real-use numbers from every saved Claude Code transcript (main + subagents), split into
sessions where last-token was active and sessions where it was not. Prints numbers only, never content.

usage: python3 bench/usage.py [--root ~/.claude/projects] [--since 2026-11-01] [--json out.json]
Benchmark runs (/var/tmp/bench, /tmp) are left out. Quota points = docs/RESEARCH.md formula (ctx.QUOTA_W × model).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "system"))
import ctx  # type: ignore  # noqa: E402  (QUOTA_W, model_mul: one formula for panel and analysis)

LT_MARKS = ("Last Token protocol", "last-token: active")
BENCH_DIRS = ("-var-tmp-bench", "-tmp-")
CODEMAP_CMDS = (" where ", " uses ", " outline ", " map")
PARTS = ("input", "cache_write", "cache_read", "output")


# ---- one transcript file -> counters ------------------------------------------------
def scan(path: Path) -> dict:
    """Token parts, quota, calls, compactions, guard denials and ctx.py use of one jsonl file."""
    r = Counter()
    seen: set = set()
    lt = False
    with path.open(errors="replace") as fh:
        for line in fh:
            if not lt and any(m in line for m in LT_MARKS):
                lt = True
            if '"compact_boundary"' in line and '"subtype"' in line:
                try:
                    d = json.loads(line)
                except ValueError:
                    d = {}
                if d.get("type") == "system" and d.get("subtype") == "compact_boundary":
                    r["compactions"] += 1
                    r["_after"] = 1
                continue
            if '"usage"' not in line and '"tool_use"' not in line and "tool_result" not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            msg = d.get("message") if isinstance(d.get("message"), dict) else {}
            if d.get("type") == "assistant":
                usage_of(msg, seen, r)
                tools_of(msg, r)
            elif d.get("type") == "user":
                denials_of(msg, r)
    r["lt"] = int(lt)
    return r


def usage_of(msg: dict, seen: set, r: Counter) -> None:
    """Add one API call's tokens (deduplicated by message id) and its quota points."""
    u, mid = msg.get("usage"), msg.get("id")
    if not isinstance(u, dict) or not mid or mid in seen or msg.get("model") == "<synthetic>":
        return
    seen.add(mid)
    t = {"input": u.get("input_tokens", 0) or 0, "cache_write": u.get("cache_creation_input_tokens", 0) or 0,
         "cache_read": u.get("cache_read_input_tokens", 0) or 0, "output": u.get("output_tokens", 0) or 0}
    k = ctx.model_mul(msg.get("model"))
    r["calls"] += 1
    for p in PARTS:
        r[p] += t[p]
        r["q_" + p] += k * t[p] * ctx.QUOTA_W[p]
    ctx_size = t["input"] + t["cache_write"] + t["cache_read"]
    if r.pop("_after", 0):            # first call after a compaction: its re-write is the compaction's cache cost
        r["post_compact_write"] += t["cache_write"]
        r["q_post_compact"] += k * t["cache_write"] * ctx.QUOTA_W["cache_write"]
    r["ctx_sum"] += ctx_size
    if ctx_size and t["cache_write"] > 0.5 * ctx_size and ctx_size > 20_000:
        r["cold_calls"] += 1          # most of the prompt re-written: cache expired or prefix changed
        r["q_cold"] += k * t["cache_write"] * ctx.QUOTA_W["cache_write"]


def tools_of(msg: dict, r: Counter) -> None:
    """Count tool calls, ctx.py calls and code-map queries."""
    for b in msg.get("content") or []:
        if not isinstance(b, dict) or b.get("type") != "tool_use":
            continue
        r["tool_calls"] += 1
        name = b.get("name", "")
        inp = b.get("input") or {}
        if name == "Read":
            r["reads"] += 1
            if not inp.get("limit"):
                r["reads_whole"] += 1
        cmd = str(inp.get("command", "")) if name == "Bash" else ""
        if "ctx.py" in cmd:
            r["ctx_calls"] += 1
            if any(c in cmd + " " for c in CODEMAP_CMDS):
                r["codemap_calls"] += 1
            if " recall " in cmd:
                r["recall_calls"] += 1


def denials_of(msg: dict, r: Counter) -> None:
    """Count guard denials (tool results carrying the last-token big-file message)."""
    c = msg.get("content")
    if not isinstance(c, list):
        return
    for b in c:
        if isinstance(b, dict) and b.get("type") == "tool_result":
            txt = json.dumps(b.get("content", ""))[:600]
            if "last-token:" in txt and "is big" in txt:
                r["guard_denials"] += 1


# ---- sessions: main file + its subagents --------------------------------------------
def sessions(root: Path, since: str) -> list[dict]:
    """One record per main session: main counters, subagent counters, lt flag."""
    out = []
    for proj in sorted(root.iterdir()):
        if not proj.is_dir() or any(proj.name.startswith(b) for b in BENCH_DIRS):
            continue
        for main in proj.glob("*.jsonl"):
            if since and _mtime_day(main) < since:
                continue
            m = scan(main)
            sub = Counter()
            for sp in (proj / main.stem / "subagents").glob("*.jsonl"):
                s = scan(sp)
                s.pop("lt", None)
                sub.update(s)
            if m["calls"] or sub["calls"]:
                out.append({"lt": bool(m["lt"]), "main": m, "sub": sub, "prompts": 0})
    return out


def _mtime_day(p: Path) -> str:
    """File date as YYYY-MM-DD."""
    import time
    return time.strftime("%Y-%m-%d", time.localtime(p.stat().st_mtime))


# ---- report --------------------------------------------------------------------------
def summarize(rows: list[dict]) -> dict:
    """Totals and ratios of one group of sessions."""
    m, s = Counter(), Counter()
    for x in rows:
        m.update(x["main"])
        s.update(x["sub"])
    tot = m + s
    q = {p: tot["q_" + p] for p in PARTS}
    qsum = sum(q.values()) or 1
    calls = tot["calls"] or 1
    return {
        "sessions": len(rows), "api_calls": tot["calls"], "subagent_calls": s["calls"],
        "tokens": {p: tot[p] for p in PARTS},
        "quota_points": round(qsum, 2),
        "quota_share_%": {p: round(100 * q[p] / qsum, 1) for p in PARTS},
        "subagent_quota_%": round(100 * sum(s["q_" + p] for p in PARTS) / qsum, 1),
        "quota_per_call": round(qsum / calls * 1000, 3),        # milli-points per API call
        "mean_ctx_per_call": round(tot["ctx_sum"] / calls),
        "cold_calls_%": round(100 * tot["cold_calls"] / calls, 1),
        "compactions": tot["compactions"],
        "cold_write_quota_%": round(100 * tot["q_cold"] / qsum, 1),
        "post_compact_quota_%": round(100 * tot["q_post_compact"] / qsum, 1),
        "cache_write_per_call": round(tot["cache_write"] / calls),
        "output_per_call": round(tot["output"] / calls),
        "compactions_per_1k_calls": round(1000 * tot["compactions"] / calls, 2),
        "tool_calls": tot["tool_calls"], "reads": tot["reads"], "reads_whole_%": round(100 * tot["reads_whole"] / (tot["reads"] or 1), 1),
        "guard_denials": tot["guard_denials"], "ctx_calls": tot["ctx_calls"],
        "codemap_calls": tot["codemap_calls"], "recall_calls": tot["recall_calls"],
    }


def table(groups: dict) -> str:
    """Markdown table: one row per metric, one column per group."""
    keys = [k for k in next(iter(groups.values())) if not isinstance(next(iter(groups.values()))[k], dict)]
    head = "| metric | " + " | ".join(groups) + " |\n|---|" + "---|" * len(groups)
    rows = [f"| {k} | " + " | ".join(f"{g[k]:,}" if isinstance(g[k], int) else str(g[k]) for g in groups.values()) + " |"
            for k in keys]
    for sub in ("quota_share_%",):
        rows.append(f"| {sub} | " + " | ".join(" / ".join(f"{p} {v}" for p, v in g[sub].items()) for g in groups.values()) + " |")
    return head + "\n" + "\n".join(rows)


def main() -> int:
    """Scan, split by last-token on/off, print a table (and optional JSON)."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path.home() / ".claude" / "projects"))
    ap.add_argument("--since", default="", help="only sessions whose file changed on/after YYYY-MM-DD")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    rows = sessions(Path(a.root).expanduser(), a.since)
    groups = {"last-token on": summarize([r for r in rows if r["lt"]]),
              "last-token off": summarize([r for r in rows if not r["lt"]])}
    print(table(groups))
    if a.json:
        Path(a.json).write_text(json.dumps(groups, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
