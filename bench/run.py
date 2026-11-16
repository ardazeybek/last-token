#!/usr/bin/env python3
"""Run one benchmark condition end-to-end with headless Claude Code.

  a = no system (native defaults, one long session)
  b = no system + start a new chat (re-explaining the project) when context >= --newchat-at
  c = context-economy installed

usage: run.py --cond a|b|c|d --dir RUN_DIR [--model haiku] [--steps 1-32] [--pct 35]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fixture  # noqa: E402
from steps import NEW_CHAT_BRIEF, STEPS  # noqa: E402

WINDOW = 200_000           # reference window, identical for all conditions
TOOLS = "Task,Bash,Read,Edit,Write,Skill"
STEP_TIMEOUT = 1500
RETRIES, RETRY_WAIT = 5, 60  # transient API errors: retries per step, base wait (s)
STALL, POLL = 360, 10        # kill a turn whose transcript has not changed for STALL s


def clean_env() -> dict:
    """Minimal environment: no desktop/host variables, no auto memory."""
    keep = {k: os.environ[k] for k in ("HOME", "PATH", "USER", "LANG", "TERM") if k in os.environ}
    keep["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
    return keep


def transcript_of(sid: str) -> Path | None:
    """Locate the transcript JSONL of a session id."""
    hits = glob.glob(str(Path.home() / ".claude" / "projects" / "*" / f"{sid}.jsonl"))
    return Path(hits[0]) if hits else None


def main_calls(tp: Path) -> list[int]:
    """Context sizes of main-thread API calls (deduplicated by message id), in order."""
    seen, out = set(), []
    for line in tp.open(errors="replace"):
        if '"usage"' not in line:
            continue
        d = json.loads(line)
        m = d.get("message")
        if d.get("type") != "assistant" or d.get("isSidechain") or not isinstance(m, dict) or not m.get("usage"):
            continue
        if m.get("id") in seen:
            continue
        seen.add(m.get("id"))
        u = m["usage"]
        out.append(u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0))
    return out


def compactions(tp: Path) -> list[dict]:
    """compact_boundary metadata entries of a transcript."""
    out = []
    for line in tp.open(errors="replace"):
        if "compact_boundary" in line:
            d = json.loads(line)
            if d.get("subtype") == "compact_boundary":
                out.append(d.get("compactMetadata", {}))
    return out


def claude_cmd(model: str, prompt: str, sid: str, resume: bool) -> list[str]:
    """Build the headless claude command line."""
    cmd = ["claude", "-p", prompt, "--model", model, "--setting-sources", "project", "--strict-mcp-config",
           "--tools", TOOLS, "--permission-mode", "bypassPermissions", "--output-format", "json",
           "--autocompact", str(WINDOW)]
    return cmd + (["--resume", sid] if resume else ["--session-id", sid])


def prepare(work: Path, cond: str, pct: int) -> None:
    """Create a fresh fixture project; install context-economy (c) or early compaction only (d)."""
    if work.exists():
        shutil.rmtree(work)
    fixture.build(work)
    if cond == "d":  # ablation: early native compaction only, no context-economy
        (work / ".claude").mkdir(exist_ok=True)
        (work / ".claude" / "settings.json").write_text(json.dumps(
            {"autoCompactWindow": WINDOW, "env": {"CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": str(pct)}}, indent=2) + "\n")
    if cond == "c":
        subprocess.run([sys.executable, str(HERE.parent / "system" / "ctx.py"), "init", str(work), "--pct", str(pct)],
                       check=True, stdout=subprocess.DEVNULL)


def last_activity(sid: str, since: float) -> float:
    """Newest write time of the session transcript or its subagent files (at least `since`)."""
    tp = transcript_of(sid)
    if not tp:
        return since
    files = [tp] + [Path(f) for f in glob.glob(str(tp.with_suffix("")) + "/**/*.jsonl", recursive=True)]
    return max([since] + [f.stat().st_mtime for f in files if f.exists()])


def run_claude(cmd: list[str], work: Path, sid: str) -> str:
    """Run one headless turn; kill it on timeout or when the transcript stalls. Returns stdout."""
    t0 = time.time()
    with open(os.devnull, "w") as err:
        p = subprocess.Popen(cmd, cwd=work, env=clean_env(), stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=err, text=True)
        while True:
            try:
                return p.communicate(timeout=POLL)[0]
            except subprocess.TimeoutExpired:
                now = time.time()
                if now - t0 > STEP_TIMEOUT or now - last_activity(sid, t0) > STALL:
                    p.kill()
                    p.communicate()
                    return json.dumps({"is_error": True, "result": f"stalled: no transcript activity "
                                       f"for {STALL}s (killed after {now - t0:.0f}s)"})


def run_step(args, work: Path, state: dict, n: int) -> dict:
    """Run one user turn; decide (cond b) whether it opens a new chat."""
    prompt = STEPS[n - 1]
    new_chat = not state["sessions"]
    if args.cond == "b" and state["sessions"] and state["last_ctx"] >= args.newchat_at * WINDOW:
        new_chat = True
        prompt = NEW_CHAT_BRIEF + prompt
    if new_chat:
        state["sessions"].append(str(uuid.uuid4()))
    sid = state["sessions"][-1]
    t0 = time.time()
    out = run_claude(claude_cmd(args.model, prompt, sid, not new_chat), work, sid)
    try:
        res = json.loads(out.strip().splitlines()[-1]) if out.strip() else {"is_error": True, "result": "no output"}
    except ValueError:
        res = {"is_error": True, "result": out[-500:]}
    tp = transcript_of(sid)
    calls = main_calls(tp) if tp else []
    prev = state["calls_seen"].get(sid, 0)
    new = calls[prev:]
    state["calls_seen"][sid] = len(calls)
    state["last_ctx"] = calls[-1] if calls else 0
    return {"step": n, "session": sid, "new_chat": new_chat, "secs": round(time.time() - t0, 1),
            "is_error": res.get("is_error"), "num_turns": res.get("num_turns"),
            "max_ctx": max(new, default=0), "last_ctx": state["last_ctx"], "calls": new,
            "session_cost_usd": res.get("total_cost_usd"), "session_model_usage": res.get("modelUsage"),
            "result": (res.get("result") or "")[:2000]}


def rate_limited(rec: dict) -> bool:
    """True when a step failed because the account usage limit was hit."""
    r = (rec.get("result") or "").lower()
    return bool(rec.get("is_error")) and "limit" in r and ("hit your" in r or "rate" in r)


def transient_error(rec: dict) -> bool:
    """True when a step failed because of a network/API hiccup (worth retrying)."""
    r = (rec.get("result") or "").lower()
    return bool(rec.get("is_error")) and any(k in r for k in
                                             ("connection", "econnreset", "overloaded", "timed out", "no output", "529", "stalled"))


def truncate_transcript(sid: str, prompt: str) -> None:
    """Cut a transcript just before the first mention of a (failed) step prompt."""
    tp = transcript_of(sid)
    if not tp:
        return
    lines = tp.read_text().splitlines(keepends=True)
    keys = {json.dumps(prompt[:60])[1:-1], json.dumps(prompt[:60], ensure_ascii=False)[1:-1]}
    cut = next((i for i, l in enumerate(lines) if any(k in l for k in keys)), None)
    if cut is not None:
        tp.write_text("".join(lines[:cut]))


def rollback(state: dict, lo: int) -> None:
    """Drop steps >= lo (and sessions only they used) so a run can resume cleanly at step lo."""
    keep = [s for s in state["steps"] if s["step"] < lo]
    used = [sid for sid in state["sessions"] if any(s["session"] == sid for s in keep)]
    if used:
        truncate_transcript(used[-1], STEPS[lo - 1].split(". ", 1)[1] if lo > 1 else STEPS[0])
    state["steps"], state["sessions"] = keep, used
    state["last_ctx"] = keep[-1]["last_ctx"] if keep else 0
    tp = transcript_of(used[-1]) if used else None
    if tp:
        state["calls_seen"][used[-1]] = len(main_calls(tp))


def leaking_memory(run_dir: Path) -> list[Path]:
    """CLAUDE.md files above the run dir; Claude Code would load them into every turn."""
    return [f for d in run_dir.resolve().parents for f in (d / "CLAUDE.md", d / ".claude" / "CLAUDE.md") if f.exists()]


def main() -> int:
    """Run all requested steps of one condition and save per-step records."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--cond", choices="abcd", required=True)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--steps", default=f"1-{len(STEPS)}")
    ap.add_argument("--pct", type=int, default=35)
    ap.add_argument("--newchat-at", type=float, default=0.60)
    args = ap.parse_args()
    run_dir = Path(args.dir).resolve()
    work = run_dir / "work"
    leaks = leaking_memory(run_dir)
    if leaks:  # e.g. ~/.claude/CLAUDE.md is loaded as an ancestor file for any dir under $HOME
        print(f"refusing: {', '.join(map(str, leaks))} would leak into the run; use a dir like /tmp/bench", file=sys.stderr)
        return 2
    lo, hi = (int(x) for x in args.steps.split("-"))
    state_f = run_dir / "state.json"
    if lo == 1:
        run_dir.mkdir(parents=True, exist_ok=True)
        prepare(work, args.cond, args.pct)
        state = {"cond": args.cond, "model": args.model, "pct": args.pct, "sessions": [], "calls_seen": {}, "last_ctx": 0, "steps": []}
    else:
        state = json.loads(state_f.read_text())
        rollback(state, lo)
    for n in range(lo, hi + 1):
        rec = run_step(args, work, state, n)
        # network/API hiccup: roll the turn back and retry it (work-tree edits of the try remain)
        for attempt in range(1, RETRIES + 1):
            if not transient_error(rec):
                break
            state["steps"].append(rec)
            rollback(state, n)
            state_f.write_text(json.dumps(state, indent=1))
            print(f"[{args.cond}] step {n} transient error ({rec['result'][:60]}), retry {attempt}/{RETRIES}", flush=True)
            time.sleep(RETRY_WAIT * attempt)
            rec = run_step(args, work, state, n)
            rec["retries"] = attempt
        if transient_error(rec):
            state["steps"].append(rec)
            rollback(state, n)
            state_f.write_text(json.dumps(state, indent=1))
            print(f"[{args.cond}] NETWORK at step {n} -> resume with --steps {n}-{hi}", flush=True)
            return 4
        if rate_limited(rec):
            state["steps"].append(rec)
            rollback(state, n)
            state_f.write_text(json.dumps(state, indent=1))
            print(f"[{args.cond}] RATE LIMIT at step {n}: {rec['result'][:120]} -> resume with --steps {n}-{hi}", flush=True)
            return 3
        state["steps"].append(rec)
        state_f.write_text(json.dumps(state, indent=1))
        print(f"[{args.cond}] step {n:2d} ctx_max={rec['max_ctx']:>7,} last={rec['last_ctx']:>7,} "
              f"new_chat={rec['new_chat']} err={rec['is_error']} {rec['secs']}s", flush=True)
    # keep transcripts with the run for re-scoring
    for sid in state["sessions"]:
        tp = transcript_of(sid)
        if tp:
            shutil.copy(tp, run_dir / f"{sid}.jsonl")
            state.setdefault("compactions", {})[sid] = compactions(tp)
    state_f.write_text(json.dumps(state, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
