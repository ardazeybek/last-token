#!/usr/bin/env python3
"""quota_probe.py — spend a known token mix with headless Claude Code, to learn how plan quota is counted.

usage: quota_probe.py {output,read,write} --budget 0.6 [--model haiku] [--dir /var/tmp/quota] [--log probes.jsonl]
  output = fresh short sessions that write long text   (mostly output tokens)
  read   = one big cached prefix, many tiny resumed turns (mostly cache reads)
  write  = fresh sessions with a new big unique prefix   (mostly cache writes)
Runs calls until the summed API-equivalent cost reaches --budget, then prints the token totals.
Read the plan's quota % before and after (desktop usage card / get_usage) to pair with these totals.
"""
import argparse
import json
import random
import string
import subprocess
import time
import uuid
from pathlib import Path

BIG_WORDS = 25_000  # ≈ 125K tokens of random letters (they tokenize ~5 tokens/word)


# Random text no cache has seen (seeded per call so every 'write' prefix is new).
def big_text(seed: str) -> str:
    rnd = random.Random(seed)
    words = ("".join(rnd.choices(string.ascii_lowercase, k=rnd.randint(3, 9))) for _ in range(BIG_WORDS))
    return "Reference notes (ignore their content):\n" + " ".join(words)


# One headless call; returns the parsed json result.
def call(args, work: Path, prompt: str, stdin: str = "", sid: str = "", resume: bool = False) -> dict:
    cmd = ["claude", "-p", prompt, "--model", args.model, "--effort", "low", "--setting-sources", "project",
           "--strict-mcp-config", "--tools", "", "--output-format", "json"]
    cmd += ["--resume", sid] if resume else (["--session-id", sid] if sid else [])
    r = subprocess.run(cmd, cwd=work, input=stdin, capture_output=True, text=True, timeout=600)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"is_error": True, "result": (r.stdout + r.stderr)[-300:]}


# Token fields of one result (this call only: `usage`, not cumulative modelUsage).
def tokens(res: dict) -> dict:
    u = res.get("usage") or {}
    return {"input": u.get("input_tokens", 0), "output": u.get("output_tokens", 0),
            "cache_read": u.get("cache_read_input_tokens", 0), "cache_write": u.get("cache_creation_input_tokens", 0),
            "cost": res.get("total_cost_usd") or 0.0}


# Run one probe kind until the budget is spent; returns totals.
def probe(args) -> dict:
    work = Path(args.dir) / args.kind
    work.mkdir(parents=True, exist_ok=True)
    tot = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "cost": 0.0, "calls": 0, "errors": 0}
    sid = str(uuid.uuid4())
    first = True
    while tot["cost"] < args.budget and (not args.calls or tot["calls"] < args.calls):
        if args.kind == "output":
            res = call(args, work, "Write a 2500-word original story about a lighthouse keeper. Output only the story.")
        elif args.kind == "read":
            if first:
                res = call(args, work, "Reply only: OK", stdin=big_text("fixed"), sid=sid)
            else:
                res = call(args, work, f"Reply only: OK {tot['calls']}", sid=sid, resume=True)
        else:
            res = call(args, work, "Reply only: OK", stdin=big_text(str(uuid.uuid4())))
        if res.get("is_error"):
            tot["errors"] += 1
            print("error:", str(res.get("result"))[:200], flush=True)
            if tot["errors"] >= 5:
                break
            time.sleep(10)
            continue
        first = False
        for k, v in tokens(res).items():
            tot[k] += v
        tot["calls"] += 1
        print(json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in tot.items()}), flush=True)
    return tot


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["output", "read", "write"])
    ap.add_argument("--budget", type=float, default=0.6)
    ap.add_argument("--calls", type=int, default=0, help="stop after N calls (read: cost is cumulative per resumed session)")
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--dir", default="/var/tmp/quota")
    ap.add_argument("--log", default="/var/tmp/quota/probes.jsonl")
    args = ap.parse_args()
    tot = probe(args)
    with open(args.log, "a") as f:
        f.write(json.dumps({"kind": args.kind, "model": args.model, "t": time.time(), **tot}) + "\n")
    print("DONE", json.dumps(tot))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
