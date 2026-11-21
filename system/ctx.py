#!/usr/bin/env python3
"""last-token: small core + disk archive + early native compaction for Claude Code.

Single stdlib-only script. Installed into a project as .ctx/ctx.py.
Commands (agent/user): init, rule, decide, note, recall, check, status, audit, pause, resume, trigger
Commands (hooks):      hook-precompact, hook-guard, hook-session, compact-summary (mod)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import sys
import time
from pathlib import Path
from typing import Any

VERSION = "1.0.0"

# ---- tunables (can be overridden with env vars of the same name) -----------------
CTX_DIR = ".ctx"
MAX_INDEX = int(os.environ.get("CTX_MAX_INDEX", 40))          # index lines kept in core
MAX_DECISIONS = int(os.environ.get("CTX_MAX_DECISIONS", 60))  # decision lines kept in core
GUARD_LINES = int(os.environ.get("CTX_GUARD_LINES", 400))     # whole-file read limit (lines)
GUARD_BYTES = int(os.environ.get("CTX_GUARD_BYTES", 32_000))  # whole-file read limit (bytes)
CORE_TOKEN_LIMIT = 2500                                        # warn above this core size
DEFAULT_WINDOW = 400_000           # compaction window for 1M-context models (set per model, see LONG_MODELS)
DEFAULT_PCT = 80                   # compact at 80 % of it: 320K on 1M models, ~native on 200K models
MIN_WORK = 100_000                 # conversation room the trigger must leave above the fixed base
# Quota (docs/RESEARCH.md): cache reads are cheap, cache writes dear. With the no-LLM digest a compaction writes
# only a few K, so 1M models compact once the work above the base reaches MIN_WORK (bench r19: −23 % quota).
FALLBACK_BASE = 95_000             # assumed fixed base (system prompt + tools) when none measured
LONG_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-2")  # 1M-context models (measured)
OLD_WINDOWS = (200_000,)           # windows older versions wrote at top level / into projects
MAX_PCT = 95                       # never push the trigger past this
BEGIN = "<!-- last-token:begin"
END = "<!-- last-token:end -->"
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".ipynb", ".zip", ".gz"}

HERE = Path(__file__).resolve().parent
TR_ASCII = str.maketrans("çğıöşüÇĞİÖŞÜâîû", "cgiosuCGIOSUaiu")


# ---- paths -------------------------------------------------------------------------
LT_HOME = Path(os.environ.get("CTX_HOME") or Path.home() / ".claude" / "last-token")  # global install
GLOBAL_FLAG = LT_HOME / "global.json"   # {"enabled": true} = last-token in every Claude Code session
STORE = LT_HOME / "store"               # per-folder memory of sessions outside a last-token project
PAUSED = LT_HOME / "paused.json"        # {"sessions": [...]}: sessions where every hook steps aside


def global_enabled() -> bool:
    """True when global mode is switched on (ctx.py global on)."""
    try:
        return bool(json.loads(GLOBAL_FLAG.read_text()).get("enabled"))
    except (OSError, ValueError, AttributeError):
        return False


def hook_input() -> dict:
    """The hook's stdin JSON as a dict ({} when empty, broken or not an object)."""
    try:
        data = json.load(sys.stdin)
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def paused_sessions() -> list[str]:
    """Session ids where last-token steps aside (ctx.py pause)."""
    try:
        return [str(x) for x in json.loads(PAUSED.read_text()).get("sessions", [])]
    except (OSError, ValueError, AttributeError):
        return []


def paused(data: dict) -> bool:
    """True when the hook's session was paused with `ctx.py pause`."""
    sid = str(data.get("session_id") or "")
    return bool(sid) and sid in paused_sessions()


def cmd_pause(args: list[str], on: bool = True) -> int:
    """pause|resume <session-id>: switch every last-token hook and the mod's compaction off/on for one session."""
    if not args:
        print(f"usage: ctx.py {'pause' if on else 'resume'} <session-id>   (paused now: {', '.join(paused_sessions()) or 'none'})")
        return 2
    ids = [x for x in paused_sessions() if x != args[0]] + ([args[0]] if on else [])
    PAUSED.parent.mkdir(parents=True, exist_ok=True)
    PAUSED.write_text(json.dumps({"sessions": ids[-50:]}, indent=2) + "\n")
    print(f"last-token {'paused' if on else 'resumed'} for session {args[0]}")
    return 0


def find_project(base: Path) -> Path | None:
    """Nearest folder at or above base holding a project .ctx/ (never inside the global store)."""
    base = base.resolve()
    if base == STORE.resolve() or STORE.resolve() in base.parents:
        return base
    for p in [base, *base.parents]:
        if (p / CTX_DIR / "ctx.py").is_file() or (p / CTX_DIR / "INDEX.md").is_file():
            return p
    return None


def store_root(base: Path) -> Path:
    """Global-store folder that stands in for a project root (its .ctx/ holds the memory)."""
    path = str(base.resolve())
    old = re.sub(r"[^A-Za-z0-9]", "-", path).strip("-")[:120]
    new = STORE / f"{old[:100]}-{hashlib.sha1(path.encode()).hexdigest()[:8]}"
    # Folder names alone collide (/a/b-c vs /a/b/c): the hash keeps them apart; old stores move over once.
    if not new.exists() and (STORE / old).is_dir():
        try:
            (STORE / old).rename(new)
        except OSError:
            return STORE / old
    return new


def is_spare(base: Path | str) -> bool:
    """True for the desktop app's pre-warmed placeholder folders (~/.claude/spares/...): never real work."""
    return "/.claude/spares/" in str(base) + "/"


def real_folder() -> Path:
    """The folder the session works in ($CLAUDE_PROJECT_DIR or --at, else cwd)."""
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd())


def is_store(root: Path) -> bool:
    """True when root is a global-store folder."""
    return STORE.resolve() in root.resolve().parents


def resolve_root(base: Path | str | None = None) -> Path:
    """Project root holding .ctx/, else (global mode) the folder's store, else base itself."""
    b = Path(base or os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd())
    proj = find_project(b)
    if proj:
        return proj
    return store_root(b) if global_enabled() else b.resolve()


def project_root() -> Path:
    """Root for agent commands: $CLAUDE_PROJECT_DIR (or --at) / cwd, resolved by resolve_root."""
    return resolve_root()


def shown(root: Path, rel: str) -> str:
    """A .ctx-relative path as the agent must use it: absolute for the global store."""
    return str(root / rel) if is_store(root) else rel


def ctx_cmd(root: Path, real: Path | None = None) -> str:
    """How the agent calls ctx.py for this root."""
    if is_store(root) and real is not None:
        return f"python3 {shlex.quote(str(LT_HOME / 'ctx.py'))} --at {shlex.quote(str(real))}"
    return "python3 .ctx/ctx.py"


def ctx_dir(root: Path) -> Path:
    """Return the .ctx directory of a project, creating the archive folder."""
    d = root / CTX_DIR
    (d / "archive").mkdir(parents=True, exist_ok=True)
    return d


def fold(text: str) -> str:
    """Case- and Turkish-letter-insensitive form for matching (İ/I/ı → i, ç → c, ...)."""
    return text.translate(TR_ASCII).casefold()


def est_tokens(text: str) -> int:
    """Rough token estimate (chars / 4)."""
    return len(text) // 4


# ---- index -------------------------------------------------------------------------
def next_id(root: Path, prefix: str) -> str:
    """Return the next free archive id for a prefix (N = note, L = log)."""
    nums = [int(m.group(1)) for f in (ctx_dir(root) / "archive").glob(f"{prefix}[0-9]*")
            if (m := re.match(rf"{prefix}(\d+)", f.name))]
    return f"{prefix}{max(nums, default=0) + 1:03d}"


def slugify(text: str) -> str:
    """Make a short filesystem-safe slug."""
    s = re.sub(r"[^a-z0-9]+", "-", text.translate(TR_ASCII).lower()).strip("-")
    return s[:40] or "entry"


def one_line(text: str, limit: int = 200) -> str:
    """Collapse whitespace and cut to a single line."""
    s = " ".join(text.split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


def add_index_line(root: Path, eid: str, title: str, path: str, summary: str) -> None:
    """Append one index line; roll the oldest lines into archive/INDEX-old.md."""
    idx = ctx_dir(root) / "INDEX.md"
    lines = [l for l in idx.read_text().splitlines() if l.startswith("- ")] if idx.exists() else []
    pointer = f"- (older entries: {CTX_DIR}/archive/INDEX-old.md)"
    has_old = pointer in lines
    entries = [l for l in lines if l != pointer]
    entries.append(f"- {eid} · {one_line(title, 60)} · {path} · {one_line(summary)}")
    if len(entries) > MAX_INDEX:
        with (ctx_dir(root) / "archive" / "INDEX-old.md").open("a") as f:
            f.write("\n".join(entries[: len(entries) - MAX_INDEX]) + "\n")
        entries, has_old = entries[len(entries) - MAX_INDEX:], True
    idx.write_text("\n".join(([pointer] if has_old else []) + entries) + "\n")


# ---- agent commands ----------------------------------------------------------------
def read_stdin_body() -> str:
    """Read optional detail text from stdin (empty when stdin is a terminal)."""
    if sys.stdin is None or sys.stdin.isatty():
        return ""
    try:
        return sys.stdin.read().strip()
    except OSError:
        return ""


def cmd_note(args: list[str]) -> int:
    """Archive a subtask note: note "<title>" "<one-line summary>" (details on stdin)."""
    if len(args) < 2:
        print('usage: ctx.py note "<title>" "<one-line summary>"  (details via stdin)')
        return 2
    root = project_root()
    title, summary = args[0], " ".join(args[1:])
    eid = next_id(root, "N")
    rel = f"{CTX_DIR}/archive/{eid}-{slugify(title)}.md"
    body = read_stdin_body()
    stamp = time.strftime("%Y-%m-%d %H:%M")
    (root / rel).write_text(f"# {eid} — {title}\n_{stamp}_\n\n**Summary:** {summary}\n\n{body}\n")
    add_index_line(root, eid, title, rel, summary)
    print(f"archived {eid} -> {shown(root, rel)}")
    return 0


def line_key(line: str) -> str:
    """Matching form of a "- key: value" line's key."""
    return fold(line[2:].split(":", 1)[0].strip())


def upsert_keyed_line(path: Path, key: str, line: str, cap: int) -> None:
    """Replace the line whose key matches (case/Turkish-insensitive) or append; keep at most cap."""
    lines = [l for l in path.read_text().splitlines() if l.startswith("- ")] if path.exists() else []
    norm = fold(key.strip())
    lines = [l for l in lines if line_key(l) != norm]
    lines.append(line)
    if len(lines) > cap:
        with (path.parent / "archive" / f"{path.stem}-old.md").open("a") as f:
            f.write("\n".join(lines[: len(lines) - cap]) + "\n")
        lines = lines[len(lines) - cap:]
    path.write_text("\n".join(lines) + "\n")


def cmd_decide(args: list[str]) -> int:
    """Record a user decision/fact: decide "<key>: <value>" (latest value per key wins)."""
    text = " ".join(args).strip()
    if ":" not in text:
        print('usage: ctx.py decide "<key>: <value>"')
        return 2
    key, value = text.split(":", 1)
    root = project_root()
    line = f"- {one_line(key, 60)}: {one_line(value, 240)}"
    # The stored (possibly cut) key is the one later calls are compared with.
    upsert_keyed_line(ctx_dir(root) / "DECISIONS.md", one_line(key, 60), line, MAX_DECISIONS)
    print(f"decision saved: {line[2:]}")
    return 0


# A numbered list packed into one call ("R1 … R2 …" / "1. … 2. …"): split it into one rule per item.
RULE_R = re.compile(r"(?:(?<=\s)|^)(?=R\d{1,2}[.:)]?\s)")
RULE_N = re.compile(r"(?:(?<=\s)|^)(?=\d{1,2}[.)]\s)")


def split_rules(text: str) -> list[str]:
    """One rule per numbered item; plain text stays one rule. Never cut: a lost rule costs quality."""
    if len(re.findall(r"(?:^|\s)R\d{1,2}[.:)]?\s", text)) >= 2:
        pat = RULE_R
    elif re.match(r"1[.)]\s", text) and re.search(r"\s2[.)]\s", text):
        pat = RULE_N
    else:
        return [text]
    return [p.strip() for p in pat.split(text) if p.strip()]


def cmd_rule(args: list[str]) -> int:
    """Record lasting house rule(s) given by the user: rule "<rule text>" (numbered lists become one line each)."""
    text = one_line(" ".join(args), 4000)
    if not text:
        print('usage: ctx.py rule "<rule>"')
        return 2
    path = ctx_dir(project_root()) / "RULES.md"
    lines = [l for l in path.read_text().splitlines() if l.startswith("- ")] if path.exists() else []
    for item in split_rules(text):
        if f"- {item}" not in lines:
            lines.append(f"- {item}")
    path.write_text("\n".join(lines) + "\n")
    print(f"rule saved ({len(lines)} rules)")
    return 0


def cmd_recall(args: list[str]) -> int:
    """Search the archive for lines containing all keywords; print path:line hits."""
    words = [fold(w) for w in args if w.strip()]
    if not words:
        print("usage: ctx.py recall <keyword> [more keywords]")
        return 2
    d = ctx_dir(project_root())
    files = sorted((d / "archive").glob("*.md")) + [d / n for n in ("DECISIONS.md", "RULES.md", "INDEX.md")]
    hits = 0
    for f in files:
        if not f.exists():
            continue
        for i, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
            if all(w in fold(line) for w in words):
                where = f if is_store(d.parent) else f.relative_to(d.parent)
                print(f"{where}:{i}: {one_line(line, 220)}")
                hits += 1
                if hits >= 20:
                    print("… (20 hits shown; refine keywords)")
                    return 0
    if hits == 0:
        print("no hits; try fewer or different keywords")
    return 0


def core_files(root: Path) -> list[Path]:
    """Files that make up the always-loaded core."""
    d = root / CTX_DIR
    return [root / "CLAUDE.md", d / "RULES.md", d / "DECISIONS.md", d / "INDEX.md"]


def cmd_check(args: list[str]) -> int:
    """Report the core size and warn when it exceeds the budget."""
    root = project_root()
    total = 0
    for f in core_files(root):
        if f.exists():
            t = est_tokens(f.read_text())
            total += t
            print(f"{f.relative_to(root)}: ~{t} tokens")
    print(f"core total: ~{total} tokens (budget {CORE_TOKEN_LIMIT})")
    if total > CORE_TOKEN_LIMIT:
        print("WARNING: core over budget — move details into notes (ctx.py note) and shorten CLAUDE.md")
        return 1
    return 0


def find_transcript(root: Path) -> Path | None:
    """Return the newest transcript file of this project (global store: of the real folder)."""
    base = Path.home() / ".claude" / "projects"
    slug = re.sub(r"[^A-Za-z0-9]", "-", str((real_folder() if is_store(root) else root).resolve()))
    cands = sorted((base / slug).glob("*.jsonl"), key=lambda p: p.stat().st_mtime) if (base / slug).is_dir() else []
    return cands[-1] if cands else None


def last_context_tokens(transcript: Path) -> int:
    """Context size of the last main-thread API call in a transcript."""
    last = 0
    for line in transcript.open(errors="replace"):
        if '"usage"' not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        m = d.get("message")
        if d.get("type") == "assistant" and isinstance(m, dict) and m.get("usage") and not d.get("isSidechain"):
            u = m["usage"]
            last = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
    return last


# ---- savings (what early compaction kept out of the requests) --------------------------
NATIVE_LIMIT = int(os.environ.get("CTX_NATIVE_LIMIT", 167_000))  # native auto-compact point of a 200K window
NATIVE_LIMIT_1M = 967_000  # ... and of a 1M window
WINDOW_200K = 200_000      # a context past this means a 1M window
NATIVE_EXTRA = 20_000   # native summary + re-attached files, over our digest, after a native compaction


def session_requests(tp: Path) -> tuple[list[tuple[int, int]], list[dict]]:
    """(line, context tokens) of each main-thread API call and the compaction boundaries, in order."""
    reqs, bounds, seen = [], [], set()
    lines = tp.read_text(errors="replace").splitlines()
    for i, line in enumerate(lines):
        if '"usage"' not in line and "compact_boundary" not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("subtype") == "compact_boundary":
            meta = d.get("compactMetadata") or {}
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            bounds.append({"line": i, "pre": int(meta.get("preTokens") or 0), "post": int(meta.get("postTokens") or 0),
                           "llm": "[last-token compaction" not in nxt})
            continue
        m = d.get("message")
        if d.get("type") != "assistant" or d.get("isSidechain") or not isinstance(m, dict) or not m.get("usage"):
            continue
        if m.get("id") in seen:
            continue
        seen.add(m.get("id"))
        u = m["usage"]
        reqs.append((i, u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)))
    return reqs, bounds


def savings(tp: Path, limit: int = NATIVE_LIMIT) -> dict:
    """Input tokens early compaction saved vs. native compaction alone (simulated counterfactual)."""
    reqs, bounds = session_requests(tp)
    # A session that ever ran past the 200K-window point runs a 1M window: native compacts near 967K.
    if any(c > WINDOW_200K for _, c in reqs) or any(x["pre"] > WINDOW_200K for x in bounds):
        limit = NATIVE_LIMIT_1M
    # A compaction near the native point is native (would happen anyway): only early ones count.
    bounds = [x for x in bounds if x["pre"] < 0.9 * limit]
    saved, sent, extra_dropped, b = 0, 0, 0, 0
    cf_summaries, cf_count = 0, 0
    for line, ctx_now in reqs:
        while b < len(bounds) and bounds[b]["line"] < line:
            extra_dropped += max(0, bounds[b]["pre"] - bounds[b]["post"])
            b += 1
        cf = ctx_now + extra_dropped
        if cf > limit and extra_dropped > NATIVE_EXTRA:  # without last-token, native compaction fires here
            cf_summaries += cf
            cf_count += 1
            extra_dropped = min(extra_dropped, NATIVE_EXTRA)
            cf = ctx_now + extra_dropped
        saved += cf - ctx_now
        sent += ctx_now
    llm_input = sum(x["pre"] for x in bounds if x["llm"])  # our compactions that still called the summarizer
    total = saved + cf_summaries - llm_input
    return {"requests": len(reqs), "sent": sent, "saved": total, "compactions": len(bounds),
            "deterministic": sum(1 for x in bounds if not x["llm"]),
            "context": reqs[-1][1] if reqs else 0,
            "pct": round(100 * total / (total + sent)) if total + sent > 0 else 0,
            # raw parts for the quota estimate (quota_report)
            "_reads": saved, "_cf_ctx": cf_summaries, "_cf_n": cf_count, "_llm_ctx": llm_input,
            "_llm_n": sum(1 for x in bounds if x["llm"]), "_rewrites": sum(x["post"] for x in bounds)}


# ---- plan quota (what the 5-hour window really charges; docs/RESEARCH.md) ---------------
# % of a Pro 5-hour window per Haiku token, measured 2026-11-21 (bench/quota_probe.py).
QUOTA_W = {"input": 4.6e-6, "cache_write": 4.6e-6, "output": 5.0e-6, "cache_read": 0.15e-6}
# Other models: assumed to scale with API price vs. Haiku (not measured; panel says "tahmini").
MODEL_MUL = {"haiku": 1.0, "sonnet": 3.0, "opus": 5.0, "fable": 5.0}
SUMMARY_OUT = 8_000  # output tokens of one summarizer (LLM) compaction


def model_mul(model: str | None) -> float:
    """Quota multiplier of a model id relative to Haiku."""
    m = (model or "").lower()
    return next((v for k, v in MODEL_MUL.items() if k in m), 1.0)


def usage_quota(files: list[Path]) -> tuple[float, float, str]:
    """(quota points, mean model multiplier, main model) of every API call in the given transcripts."""
    pts, mul_sum, n, model = 0.0, 0.0, 0, ""
    for f in files:
        seen: set = set()
        for line in f.open(errors="replace"):
            if '"usage"' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            m = d.get("message")
            if d.get("type") != "assistant" or not isinstance(m, dict) or not m.get("usage") or m.get("id") in seen:
                continue
            seen.add(m.get("id"))
            u, k = m["usage"], model_mul(m.get("model"))
            pts += k * (u.get("input_tokens", 0) * QUOTA_W["input"] + u.get("cache_creation_input_tokens", 0) * QUOTA_W["cache_write"]
                        + u.get("output_tokens", 0) * QUOTA_W["output"] + u.get("cache_read_input_tokens", 0) * QUOTA_W["cache_read"])
            if f is files[0] and "synthetic" not in str(m.get("model")):
                mul_sum, n, model = mul_sum + k, n + 1, str(m.get("model"))
    return pts, (mul_sum / n if n else 1.0), model


def quota_report(tp: Path, sv: dict) -> dict:
    """Quota of the session (main + subagents) and the quota early compaction saved, in % of a 5-hour window."""
    subs = sorted(tp.with_suffix("").glob("subagents/*.jsonl"))
    main_pts, k, model = usage_quota([tp])
    sub_pts = usage_quota(subs)[0] if subs else 0.0
    w = QUOTA_W
    # Without last-token: the dropped context would be re-read every call, native compactions would run
    # a summarizer; with it: each compaction re-writes its (small) result, LLM-mode ones also ran a summarizer.
    saved = k * (sv["_reads"] * w["cache_read"]
                 + sv["_cf_ctx"] * w["cache_read"] + sv["_cf_n"] * (SUMMARY_OUT * w["output"] + NATIVE_EXTRA * w["cache_write"])
                 - sv["_llm_ctx"] * w["cache_read"] - sv["_llm_n"] * SUMMARY_OUT * w["output"]
                 - sv["_rewrites"] * w["cache_write"]
                 + sv.get("_idle_pre", 0) * w["cache_write"])  # cold-cache compaction: the dropped part is not rewritten
    used = main_pts + sub_pts
    return {"quota": round(used, 3), "quota_sub": round(sub_pts, 3), "quota_saved": round(saved, 3),
            "quota_pct": round(100 * saved / (saved + used)) if saved + used > 0 else 0,
            "model": model, "measured": k == 1.0}


# ---- prompt cache health (docs/DESIGN.md "cache-aware compaction") ------------------------
# A cache read costs ~1/30 of a write: what burns quota is the prompt cache being written again —
# after an idle gap longer than its TTL, after a changed prefix (tool list, CLAUDE.md, model switch),
# after every compaction. The mod prunes old tool outputs on the first request after a cold gap
# (the whole context is re-written then anyway); this report shows what still re-wrote the cache.
BUST_MIN = 5_000  # a rewrite smaller than this is ordinary new content


def iso_ts(s: str) -> float:
    """Unix time of a transcript ISO timestamp (0 when missing or unreadable)."""
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return 0.0


def main_calls(tp: Path) -> list[dict]:
    """Main-thread API calls in order: time, model, token parts, cache TTL, and whether a compaction came before."""
    calls, seen, after_compact = [], set(), False
    for line in tp.open(errors="replace"):
        if '"usage"' not in line and "compact_boundary" not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("subtype") == "compact_boundary":
            meta = d.get("compactMetadata") or {}
            calls.append({"boundary": True, "ts": iso_ts(d.get("timestamp")),
                          "pre": int(meta.get("preTokens") or 0), "post": int(meta.get("postTokens") or 0)})
            after_compact = True
            continue
        m = d.get("message")
        if d.get("type") != "assistant" or d.get("isSidechain") or not isinstance(m, dict) or not m.get("usage"):
            continue
        if m.get("id") in seen or "synthetic" in str(m.get("model")):
            continue
        seen.add(m.get("id"))
        u = m["usage"]
        cc = u.get("cache_creation") or {}
        calls.append({"ts": iso_ts(d.get("timestamp")), "model": str(m.get("model")),
                      "cw": u.get("cache_creation_input_tokens", 0), "cr": u.get("cache_read_input_tokens", 0),
                      "inp": u.get("input_tokens", 0), "out": u.get("output_tokens", 0),
                      "ttl": 300 if cc.get("ephemeral_5m_input_tokens", 0) and not cc.get("ephemeral_1h_input_tokens", 0) else 3600,
                      "after_compact": after_compact})
        after_compact = False
    return calls


def cache_report(tp: Path) -> dict:
    """Cache rewrites of a session by cause, and the idle compactions that shrank a cold-cache rewrite."""
    calls = main_calls(tp)
    busts: dict[str, list] = {"idle": [0, 0], "prefix": [0, 0], "model": [0, 0]}  # cause → [count, tokens]
    idle_pre, idle_n, prev = 0, 0, None
    for c in calls:
        if c.get("boundary"):
            # A compaction made after the cache went cold: without it the full context was rewritten.
            if prev and c["ts"] and prev["ts"] and c["ts"] - prev["ts"] > prev["ttl"]:
                idle_pre, idle_n = idle_pre + max(0, c["pre"] - c["post"]), idle_n + 1
            continue
        if prev and not c["after_compact"]:
            prefix = prev["cr"] + prev["cw"] + prev["inp"]
            lost = min(c["cw"], prefix - c["cr"])
            if c["cw"] > BUST_MIN and lost > BUST_MIN:
                cause = "idle" if c["ts"] - prev["ts"] > prev["ttl"] else "model" if c["model"] != prev["model"] else "prefix"
                busts[cause][0] += 1
                busts[cause][1] += lost
        prev = c
    return {"busts": {k: {"n": v[0], "tokens": v[1]} for k, v in busts.items()},
            "idle_compactions": idle_n, "_idle_pre": idle_pre}


def cmd_savings(args: list[str]) -> int:
    """savings [--session ID | --transcript PATH] [--json]: tokens saved in a session."""
    opts = {a: args[i + 1] for i, a in enumerate(args[:-1]) if a in ("--session", "--transcript")}
    tp = Path(opts["--transcript"]) if "--transcript" in opts else \
        find_session_transcript(opts.get("--session", "")) or find_transcript(project_root())
    if not tp or not tp.exists():
        print(json.dumps({"error": "no transcript"}) if "--json" in args else "no transcript found")
        return 1
    r = savings(tp)
    r.update(quota_report(tp, r))
    r = {k: v for k, v in r.items() if not k.startswith("_")}
    if "--json" in args:
        print(json.dumps(r))
    else:
        print(f"quota: ~{r['quota']}% of a 5-hour window (subagents {r['quota_sub']}%), saved ~{r['quota_saved']}% ({r['quota_pct']}% less)")
        print(f"requests: {r['requests']}  compactions: {r['compactions']} ({r['deterministic']} without a model call)")
        print(f"input sent: {r['sent']:,} tokens  saved: {r['saved']:,} tokens ({r['pct']}% less)")
        print(f"context now: {r['context']:,} tokens")
    return 0


def cmd_status(args: list[str]) -> int:
    """Print the current context fill (from the newest transcript) and archive stats."""
    root = project_root()
    t = find_transcript(root)
    if t:
        n = last_context_tokens(t)
        print(f"context: {n:,} tokens = {100 * n / DEFAULT_WINDOW:.0f}% of {DEFAULT_WINDOW:,}")
    arch = list((ctx_dir(root) / "archive").glob("*.md"))
    print(f"archive: {len(arch)} files")
    return cmd_check([])


# ---- transcript condensing (PreCompact) ----------------------------------------------
def block_text(content) -> list[tuple[str, object]]:
    """Normalise message content into (kind, block) pairs."""
    if isinstance(content, str):
        return [("text", content)]
    out = []
    for b in content or []:
        if isinstance(b, dict):
            out.append((b.get("type", "?"), b))
    return out


def tool_use_line(b: Any) -> str:
    """One-line description of a tool call."""
    name, inp = b.get("name", "?"), b.get("input", {}) or {}
    if name == "Read":
        extra = f" offset={inp.get('offset')} limit={inp.get('limit')}" if inp.get("limit") else ""
        return f"Read {inp.get('file_path')}{extra}"
    if name == "Bash":
        return f"Bash `{one_line(str(inp.get('command')), 300)}`"
    if name in ("Edit", "Write"):
        what = f"{len(str(inp.get('content', '')))} chars" if name == "Write" else one_line(str(inp.get("new_string", "")), 160)
        return f"{name} {inp.get('file_path')} ({what})"
    if name in ("Task", "Agent"):
        return f"{name} [{inp.get('subagent_type', '')}] {one_line(str(inp.get('prompt', '')), 300)}"
    return f"{name} {one_line(json.dumps(inp), 200)}"


def result_text(b: Any) -> str:
    """Plain text of a tool_result block."""
    c = b.get("content")
    if isinstance(c, list):
        c = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
    return str(c or "")


SKIP_PROMPT = ("<task-notification", "<local-command-stdout", "<local-command-stderr", "<local-command-caveat",
               "[last-token", "[Request interrupted", "<bash-stdout", "<bash-stderr")
REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)


def prompt_text(text: str) -> str | None:
    """What the person typed in a user text block; None for rows they did not write (notifications, command output, digests)."""
    t = REMINDER.sub("", text).strip()
    if not t or t.startswith(SKIP_PROMPT):
        return None
    if t.startswith("<command-"):  # a slash command: keep it as "/name args"
        name = re.search(r"<command-name>(.*?)</command-name>", t, re.S)
        args = re.search(r"<command-args>(.*?)</command-args>", t, re.S)
        parts = [name.group(1).strip() if name else "", args.group(1).strip() if args else ""]
        return " ".join(x for x in parts if x) or None
    return t  # pasted content, HTML, plain text: all the person's


def head_tail(text: str, n: int) -> str:
    """Text cut to about n chars keeping its start and end, with a visible cut mark."""
    if len(text) <= n:
        return text
    head, tail = text[: int(n * 0.6)], text[-int(n * 0.4):]
    return f"{head}\n…[{len(text) - len(head) - len(tail):,} chars cut here; full text in the archive]…\n{tail}"


def block_key(d: dict, m: dict, kind: str, b: Any) -> tuple:
    """Dedup key of a content block: streamed assistant parts share a message id, user rows have only a uuid."""
    tid = b.get("tool_use_id") if isinstance(b, dict) else None
    return (m.get("id") or d.get("uuid"), kind, tid, json.dumps(b, sort_keys=True)[:300])


def user_prompts(entries: list[dict]) -> list[tuple[str, str]]:
    """(uuid, text) of every prompt the person wrote in these main-thread entries, oldest first."""
    out, seen = [], set()
    for d in entries:
        m = d.get("message")
        if d.get("type") != "user" or d.get("isSidechain") or d.get("isMeta") or d.get("isCompactSummary") \
                or not isinstance(m, dict):
            continue
        for kind, b in block_text(m.get("content")):
            text = b if isinstance(b, str) else b.get("text", "") if kind == "text" else ""
            t = prompt_text(text) if kind == "text" and text else None
            if t and block_key(d, m, kind, b) not in seen:
                seen.add(block_key(d, m, kind, b))
                out.append((str(d.get("uuid")), t))
    return out


def condense_transcript(path: Path) -> tuple[list[str], list[str]]:
    """Condense transcript entries since the last compaction into markdown lines + prompts."""
    entries = []
    for line in path.open(errors="replace"):
        try:
            entries.append(json.loads(line))
        except ValueError:
            pass
    start = max((i for i, d in enumerate(entries) if d.get("subtype") == "compact_boundary"), default=-1) + 1
    md, prompts, seen = [], [], set()
    for d in entries[start:]:
        m = d.get("message")
        if d.get("isSidechain") or not isinstance(m, dict) or d.get("type") not in ("user", "assistant"):
            continue
        for kind, b in block_text(m.get("content")):
            key = block_key(d, m, kind, b)
            if key in seen:
                continue
            seen.add(key)
            md.extend(render_block(d, kind, b, prompts))
    return md, prompts


def render_block(d: dict, kind: str, b: Any, prompts: list[str]) -> list[str]:
    """Render one content block of a transcript entry as markdown lines."""
    text = b if isinstance(b, str) else b.get("text", "") if kind == "text" else ""
    if d["type"] == "user":
        if d.get("isCompactSummary"):
            return [f"\n### Previous summary\n{text[:3000]}"]
        t = prompt_text(text) if kind == "text" and text and not d.get("isMeta") else None
        if t:
            prompts.append(t)
            return [f"\n### User\n{t}"]
        if kind == "tool_result":
            r = result_text(b)
            return [f"  ↳ {one_line(r, 600)}"] if r else []
        return []
    if kind == "text" and text.strip():
        return [f"**Claude:** {text.strip()[:1500]}"]
    if kind == "tool_use":
        return [f"- tool: {tool_use_line(b)}"]
    return []


def hook_precompact(args: list[str]) -> int:
    """PreCompact hook: archive the condensed log, update index, print summary rules."""
    data = hook_input()
    if paused(data) or is_spare(data.get("cwd") or "") or ("--global" in args and not global_turn(data.get("cwd"))):
        return 0
    root = resolve_root(data.get("cwd"))
    tp = Path(data["transcript_path"]) if data.get("transcript_path") else None
    rel = shown(root, archive_segment(root, tp, data.get("trigger", "?")))
    if tp and tp.exists():
        raise_trigger_if_thrashing(root, tp)
        auto_capture(root, segment_facts(segment_entries(tp))[0])
    print(summary_rules(rel, rel.split("/")[-1].split("-")[0]))
    return 0


# ---- deterministic compaction (mod `session.compact`: no summarizer call) --------------
SUM_PROMPT_CHARS = 4000   # latest user prompt is kept verbatim up to this size
SUM_OLD_PROMPTS = 6       # earlier prompts of the segment kept (each cut to 700 chars)
SUM_ACTIONS = 15          # older tool actions listed (beyond the verbatim recent steps)
RECENT_CHARS = int(os.environ.get("CTX_RECENT_CHARS", 6000))  # newest steps shown in full (replaces a kept tail)
RECENT_RESULT = 1500      # per tool result in that section


def tool_use_line_full(b: Any) -> str:
    """Tool call line for the recent-steps section (Edit/Write show the new text, cut)."""
    inp = b.get("input", {}) if isinstance(b, dict) else {}
    if isinstance(b, dict) and b.get("name") == "Edit":
        return f"Edit {inp.get('file_path')}: {one_line(str(inp.get('old_string', '')), 200)} ⇒ {str(inp.get('new_string', ''))[:600]}"
    return tool_use_line(b) if isinstance(b, dict) and b else "?"


def segment_entries(tp: Path) -> list[dict]:
    """Main-thread transcript entries since the last compaction boundary."""
    entries = []
    for line in tp.open(errors="replace"):
        try:
            entries.append(json.loads(line))
        except ValueError:
            pass
    start = max((i for i, d in enumerate(entries) if d.get("subtype") == "compact_boundary"), default=-1) + 1
    return [d for d in entries[start:] if not d.get("isSidechain")]


def all_main_entries(tp: Path) -> list[dict]:
    """Every main-thread transcript entry (all segments)."""
    out = []
    for line in tp.open(errors="replace"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not d.get("isSidechain"):
            out.append(d)
    return out


def segment_facts(entries: list[dict]) -> tuple[list[str], list[str], list[str], list[str]]:
    """Prompts, tool actions (with short outcome), changed files and assistant notes of a segment."""
    prompts, actions, files, notes, seen = [], [], [], [], set()
    pending: dict[str, int] = {}
    recent: list[str] = []
    b_by_id: dict[str, Any] = {}
    for d in entries:
        m = d.get("message")
        if not isinstance(m, dict) or d.get("type") not in ("user", "assistant"):
            continue
        for kind, b in block_text(m.get("content")):
            key = block_key(d, m, kind, b)
            if key in seen:
                continue
            seen.add(key)
            text = b if isinstance(b, str) else b.get("text", "") if kind == "text" else ""
            if d["type"] == "user":
                t = prompt_text(text) if kind == "text" and text else None
                if t and not d.get("isMeta") and not d.get("isCompactSummary"):
                    prompts.append(t)
                elif kind == "tool_result" and b.get("tool_use_id") in pending:
                    i = pending.pop(b["tool_use_id"])
                    r = result_text(b).strip()
                    flag = "ERROR " if b.get("is_error") else ""
                    actions[i] += f" → {flag}{one_line(r.splitlines()[-1] if r else 'ok', 160)}"
                    line = f"- {tool_use_line_full(b_by_id.get(b['tool_use_id'], {}))}"
                    # Empty/boilerplate results add nothing: show the call alone.
                    if r and not EMPTY_RESULT.match(r):
                        line += f"\n  result: {flag}{head_tail(r, RECENT_RESULT)}"
                    elif flag:
                        line += "\n  result: ERROR"
                    recent.append(line)
            elif kind == "tool_use":
                inp = b.get("input") or {}
                if b.get("name") in ("Edit", "Write") and inp.get("file_path") not in files:
                    files.append(str(inp.get("file_path")))
                pending[b.get("id")] = len(actions)
                b_by_id[b.get("id")] = b
                actions.append(one_line(tool_use_line(b), 220))
            elif kind == "text" and text.strip():
                notes.append(text.strip())
                recent.append(f"- (you) {head_tail(text.strip(), RECENT_RESULT)}")
    # Calls still waiting for a result were running (or cut off) when compaction came: never drop them.
    for tid, i in pending.items():
        actions[i] += " → (no result yet)"
        recent.append(f"- {tool_use_line_full(b_by_id.get(tid, {}))}\n  result: (none yet: it was running or was "
                      "cut off by the compaction; check its effect before running it again)")
    segment_facts.recent = recent  # type: ignore[attr-defined]
    return prompts, actions, files, notes


EMPTY_RESULT = re.compile(r"^\s*(\(Bash completed with no output\)|ok|done|success|\[?image\]?)?\s*$", re.I)
SUM_FINDINGS = 6          # latest assistant remarks listed as "your findings"
SUM_FINDING_CHARS = 400   # each cut to this
SUM_IMAGES = 5            # latest images/screenshots named (their pixels are not carried over)
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
PLAN_TOOLS = ("TodoWrite", "mcp__ccd_turn__update_plan")
WRAP_TOOL = "mcp__ccd_turn__wrap_up"


def tool_uses(entries: list[dict]) -> list[dict]:
    """All tool_use blocks of main-thread assistant entries, oldest first (deduplicated)."""
    out, seen = [], set()
    for d in entries:
        m = d.get("message")
        if d.get("type") != "assistant" or d.get("isSidechain") or not isinstance(m, dict):
            continue
        for kind, b in block_text(m.get("content")):
            if kind == "tool_use" and isinstance(b, dict) and b.get("id") not in seen:
                seen.add(b.get("id"))
                out.append(b)
    return out


def apply_plan_call(plan: list[dict], name: str, inp: dict) -> list[dict]:
    """New task list after one TodoWrite / update_plan / wrap_up call."""
    if name == WRAP_TOOL:
        return [{**it, "status": "completed"} for it in plan]
    if name == "TodoWrite":
        return [{"content": str(t.get("content", "")), "status": str(t.get("status", "pending"))}
                for t in inp.get("todos") or [] if isinstance(t, dict)]
    if inp.get("items"):
        return [{"content": str(t.get("content", "")), "status": str(t.get("status", "pending"))}
                for t in inp["items"] if isinstance(t, dict)]
    plan = [dict(it) for it in plan]
    if inp.get("advance"):
        cur = next((i for i, it in enumerate(plan) if it["status"] == "in_progress"), None)
        if cur is not None:
            plan[cur]["status"] = "completed"
        nxt = next((i for i, it in enumerate(plan) if it["status"] == "pending"), None)
        if nxt is not None:
            plan[nxt]["status"] = "in_progress"
    for n in inp.get("done") or []:
        if isinstance(n, (int, float)) and 1 <= int(n) <= len(plan):
            plan[int(n) - 1]["status"] = "completed"
    if isinstance(inp.get("start"), (int, float)) and 1 <= int(inp["start"]) <= len(plan):
        for it in plan:
            if it["status"] == "in_progress":
                it["status"] = "pending"
        plan[int(inp["start"]) - 1]["status"] = "in_progress"
    return plan


def plan_state(entries: list[dict]) -> list[dict]:
    """The agent's current task list, replayed from every plan call of the whole transcript."""
    plan: list[dict] = []
    for b in tool_uses(entries):
        if b.get("name") in PLAN_TOOLS + (WRAP_TOOL,):
            plan = apply_plan_call(plan, b["name"], b.get("input") or {})
    return plan


def recent_images(entries: list[dict]) -> list[str]:
    """Image files the agent looked at last (newest last); a screenshot tool counts as '(screenshot)'."""
    seen: list[str] = []
    for b in tool_uses(entries):
        inp, name = b.get("input") or {}, str(b.get("name", ""))
        path = str(inp.get("file_path") or "")
        if name == "Read" and path.lower().endswith(IMAGE_EXT):
            item = path
        elif "screenshot" in name.lower() or inp.get("action") == "screenshot":
            item = f"(screenshot via {name.split('__')[-1]})"
        else:
            continue
        if item in seen:
            seen.remove(item)
        seen.append(item)
    return seen[-SUM_IMAGES:]


def turn_in_progress(entries: list[dict]) -> bool:
    """True when the newest main-thread step is a tool call/result, i.e. compaction hit mid-turn."""
    for d in reversed(entries):
        m = d.get("message")
        if d.get("isSidechain") or not isinstance(m, dict) or d.get("type") not in ("user", "assistant"):
            continue
        blocks = block_text(m.get("content"))
        kinds = [k for k, _ in blocks]
        if d["type"] == "user":
            if "tool_result" in kinds:
                return True
            if d.get("isMeta") or d.get("isCompactSummary"):
                continue
            texts = [b if isinstance(b, str) else b.get("text", "") for k, b in blocks if k == "text"]
            # Slash-command output and digests are not requests waiting for an answer.
            if texts and all(REMINDER.sub("", t).strip().startswith(SKIP_PROMPT[1:]) for t in texts):
                continue
            return True  # an unanswered prompt (or a task notification)
        if "tool_use" in kinds:
            return True
        if "text" in kinds:
            return False
    return False


def collapse_repeats(lines: list[str]) -> list[str]:
    """Merge runs of identical recent-step lines into one line with a count."""
    out: list[str] = []
    count = 0
    for ln in lines:
        if out and ln == out[-1].split("  (×")[0]:
            count += 1
            out[-1] = f"{ln}  (×{count})"
            continue
        count = 1
        out.append(ln)
    return out


def plan_lines(plan: list[dict]) -> list[str]:
    """Markdown lines of a task list."""
    mark = {"completed": "x", "in_progress": ">", "pending": " "}
    return [f"- [{mark.get(it['status'], ' ')}] {one_line(it['content'], 160)}" for it in plan]


SUM_EARLIER = 4           # substantive prompts of earlier segments carried into the digest
SUM_EARLIER_CHARS = 1500  # each cut to this (start + end kept)


def earlier_requests(entries: list[dict], all_entries: list[dict] | None) -> list[str]:
    """Substantive prompts written before this segment (short "go on"-style replies skipped), newest last."""
    seg = {str(d.get("uuid")) for d in entries}
    older = [t for u, t in user_prompts(all_entries or []) if u not in seg]
    return [t for t in older if len(t) >= 30][-SUM_EARLIER:]


def build_extra(root: Path, all_entries: list[dict], rel: str) -> str:
    """Block appended after the model's own compaction summary: the person's words and the task list, verbatim."""
    prompts = [t for _, t in user_prompts(all_entries)]
    keep = [t for t in prompts[:-1] if len(t) >= 30][-(SUM_EARLIER - 1):] + prompts[-1:]
    plan = plan_state(all_entries)
    out = [f"{DIGEST_HEAD} kept verbatim next to the summary above: the user's own words and your task list. "
           f"Archive of everything: {rel} (`recall <word>`). This is not a new message from the user.]"]
    if keep:
        out += ["", "## User requests (verbatim, cut; newest last — the last one is the current request)"]
        out += [f"- {head_tail(p, 2500)}" for p in keep]
    if plan and any(it["status"] != "completed" for it in plan):
        out += ["", "## Your task list ([x] done, [>] in progress) — keep it, do not rewrite it", *plan_lines(plan)]
    text = "\n".join(out)
    return text if is_store(root) else text.replace(str(root) + "/", "")


DIGEST_HEAD = "[last-token compaction:"


def build_summary(root: Path, entries: list[dict], rel: str, all_entries: list[dict] | None = None,
                  core: str = "") -> str:
    """Deterministic post-compaction message: request, task list, findings, state and recent steps."""
    prompts, actions, files, notes = segment_facts(entries)
    recent = collapse_repeats(getattr(segment_facts, "recent", []))
    plan = plan_state(all_entries if all_entries is not None else entries)
    busy = turn_in_progress(entries)
    images = recent_images(entries)
    out = [f"{DIGEST_HEAD} older turns were replaced by this digest; nothing was summarised "
           f"by a model. Full log: {rel} (`ctx.py recall <word>`). Rules, decisions and the archive index "
           f"({'below' if core else 'in CLAUDE.md'}) stay authoritative. This is not a new message from the user.]"]
    # Where the work stands: the one thing the agent must not lose.
    if busy:
        out += ["", "## State: you were in the MIDDLE of the latest request when context was compacted",
                "Do not restart or re-plan from scratch. Continue from the last step under \"Most recent steps\". "
                "Anything you only saw (screens, command output) is gone: re-check live state before acting on it."]
    if prompts:
        out += ["", "## Latest user request (verbatim — continue it if not finished)", head_tail(prompts[-1], SUM_PROMPT_CHARS)]
        if len(prompts) > 1:
            out += ["", "## Earlier user requests in this segment (verbatim, cut)"]
            out += [f"- {head_tail(p, 700)}" for p in prompts[-1 - SUM_OLD_PROMPTS:-1]]
    # Requests of earlier segments: after a second compaction the real task is often only there.
    earlier = earlier_requests(entries, all_entries)
    if earlier:
        out += ["", "## Requests from before the previous compaction (verbatim, cut; newest last)"]
        out += [f"- {head_tail(p, SUM_EARLIER_CHARS)}" for p in earlier]
    if plan and any(it["status"] != "completed" for it in plan):
        out += ["", "## Your task list ([x] done, [>] in progress) — keep it, do not rewrite it", *plan_lines(plan)]
    if notes:
        out += ["", "## Your latest findings/remarks (oldest first)"]
        out += [f"- {one_line(n, SUM_FINDING_CHARS)}" for n in notes[-SUM_FINDINGS:]]
    if images:
        out += ["", "## Images you looked at last (pixels not carried over — open/capture again if needed)",
                *[f"- {i}" for i in images]]
    if files:
        out += ["", "## Files created/changed in this segment", ", ".join(f.replace(str(root) + "/", "") for f in files)]
    keep, used = [], 0
    for r in reversed(recent):
        used += len(r)
        if used > RECENT_CHARS and keep:
            break
        keep.append(r)
    # Older actions only: the ones shown in full below are not listed twice.
    shown = sum(int(r.split("(×")[-1].rstrip(")")) if r.endswith(")") and "  (×" in r else 1
                for r in keep if not r.startswith("- (you)"))
    older = actions[:max(0, len(actions) - shown)]
    if older:
        out += ["", f"## Earlier tool actions of this segment (newest {min(len(older), SUM_ACTIONS)}, oldest first)"]
        out += [f"- {a}" for a in collapse_repeats(older[-SUM_ACTIONS:])]
    if keep:
        out += ["", "## Most recent steps (verbatim, oldest first) — pick up exactly here", *reversed(keep)]
    if core:  # global mode: the protocol + memory came with the first message, which this digest replaces
        out += ["", core.strip()]
    text = "\n".join(out)
    return text if is_store(root) else text.replace(str(root) + "/", "")


DECISION_HINT = re.compile(
    r"\b(we agreed|agreed|decided|decision|will be (called|named)|is called|instead of|rather than|"
    r"from now on|switch(ed)? to|changed? (it )?to|override|overrides|not the spec|client (wants|asked|said|prefers|"
    r"confirmed|insists)|our (contact|port|codename|name)|codename|contact person|port:? ?\d+|\w+ header|deadline)\b"
    # Turkish: "bundan sonra", "artık", "karar verdik", "anlaştık", "X yerine", "her zaman", "asla", ...
    r"|(?<!\w)(bundan sonra|bundan böyle|karar(ı|ımız|laştırdık|laştık| verdik| verildi)?|anlaştık|"
    r"\S+ yerine \S+ (kullan|olsun|yap)\w*|her zaman|asla|hiçbir zaman|hiç bir zaman|varsayılan|son tarih|teslim tarihi|"
    r"(adı|ismi|portu|rengi|yazı tipi|fontu) .{1,40} (olsun|olacak|olmalı)|kullanma(yalım|yacağız|yın)?|"
    r"kullan(alım|acağız|ın)|tercih (ediyorum|ederim|et)|müşteri (istiyor|istedi|dedi|söyledi))(?!\w)", re.I)
MAX_AUTO = 8          # auto-captured decision sentences per compaction
MAX_AUTO_CHARS = 180  # longer "sentences" are talk (unpunctuated dictation), not one decision


def words(text: str) -> set[str]:
    """Significant lowercase words of a text."""
    return {w for w in re.findall(r"[\w`'-]{4,}", text.lower())}


def values(text: str) -> set[str]:
    """Numbers and code-like tokens of a text (what a changed decision changes)."""
    return set(re.findall(r"\d[\w.:/-]*|`[^`]+`", text))


def auto_capture(root: Path, prompts: list[str]) -> int:
    """Copy decision-like sentences of user prompts into DECISIONS.md; a changed value replaces the old line."""
    path = ctx_dir(root) / "DECISIONS.md"
    known = [(l, words(l)) for l in (path.read_text().splitlines() if path.exists() else []) if l.startswith("- ")]
    added = 0
    for p in prompts:
        for sent in re.split(r"(?<=[.!?])\s+|\n+", p):
            sent = sent.strip()
            if not 12 <= len(sent) <= MAX_AUTO_CHARS or re.match(r"R\d+\.", sent) or not DECISION_HINT.search(sent):
                continue
            w = words(sent)
            if not w:
                continue
            same = [(l, k) for l, k in known if len(w & k) >= 0.6 * len(w)]
            # Same topic, same values: already known. Same topic, new values: the user changed it.
            if same and all(values(sent) <= values(l) for l, _ in same):
                continue
            if same:
                drop = {l for l, _ in same if l.startswith("- (user) ")}
                lines = [l for l in path.read_text().splitlines() if l.startswith("- ") and l not in drop]
                path.write_text("\n".join(lines) + ("\n" if lines else ""))
                known = [(l, k) for l, k in known if l not in drop]
            line = f"- (user) {one_line(sent, 240)}"
            upsert_keyed_line(path, line[2:].split(":", 1)[0], line, MAX_DECISIONS)
            known.append((line, w))
            added += 1
            if added >= MAX_AUTO:
                return added
    return added


def find_session_transcript(sid: str) -> Path | None:
    """Transcript JSONL of a session id."""
    hits = list((Path.home() / ".claude" / "projects").glob(f"*/{sid}.jsonl")) if sid else []
    return hits[0] if hits else None


def latest_log(root: Path) -> str:
    """Path of the newest archived conversation log (written by the PreCompact hook), as the agent uses it."""
    logs = sorted((ctx_dir(root) / "archive").glob("L[0-9]*-log.md"))
    return shown(root, f"{CTX_DIR}/archive/{logs[-1].name}") if logs else shown(root, f"{CTX_DIR}/archive/")


def cmd_compact_summary(args: list[str]) -> int:
    """Mod helper: --extra prints the block kept beside the model's summary; else archive + full digest."""
    data = hook_input()
    if paused(data) or is_spare(data.get("cwd") or ""):
        return 1  # the mod falls back to the engine's own compaction
    root = resolve_root(data.get("cwd"))
    tp = Path(data["transcript_path"]) if data.get("transcript_path") else find_session_transcript(data.get("session_id", ""))
    if not tp or not tp.exists():
        return 1
    if "--extra" in args:
        print(build_extra(root, all_main_entries(tp), latest_log(root)))
        return 0
    rel = shown(root, archive_segment(root, tp, data.get("trigger", "auto")))
    raise_trigger_if_thrashing(root, tp)
    entries = segment_entries(tp)
    auto_capture(root, segment_facts(entries)[0])
    real = Path(data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd())
    core = global_core(root, real) if is_store(root) else ""
    print(build_summary(root, entries, rel, all_main_entries(tp), core))
    return 0


def archive_segment(root: Path, tp: Path | None, trigger: str) -> str:
    """Write the condensed segment log to the archive and index it; returns its relative path."""
    eid = next_id(root, "L")
    rel = f"{CTX_DIR}/archive/{eid}-log.md"
    md, prompts = condense_transcript(tp) if tp and tp.exists() else ([], [])
    stamp = time.strftime("%Y-%m-%d %H:%M")
    head = [f"# {eid} — conversation log archived before compaction ({trigger}, {stamp})",
            "", "## User prompts in this segment"]
    head += [f"{i}. {one_line(p, 400)}" for i, p in enumerate(prompts, 1)] + ["", "## Condensed transcript"]
    text = "\n".join(head + md).replace(str(root) + "/", "")
    (root / rel).write_text(text + "\n")
    topics = " | ".join(one_line(p, 45) for p in prompts[-6:]) or "no user prompts"
    add_index_line(root, eid, f"log before compaction ({len(prompts)} prompts)", rel, "prompts: " + topics)
    return rel


def base_after_last_compact(tp: Path) -> int | None:
    """First context size after the last compaction, if it came only a few calls ago."""
    first, calls = None, 0
    with tp.open(errors="replace") as f:
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("subtype") == "compact_boundary":
                first, calls = None, 0
                continue
            n = usage_total(e)
            if n:
                calls += 1
                first = first or n
    return first if first and calls <= 6 else None


def raise_trigger_if_thrashing(root: Path, tp: Path) -> None:
    """Compaction came right after the previous one: raise pct in settings so it stops looping."""
    base = base_after_last_compact(tp)
    proj = root / ".claude" / "settings.json"
    # The pct lives where Claude Code reads it: the project's file if it sets one, else the user's.
    f = proj if not is_store(root) and "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE" in (read_settings(proj).get("env") or {}) \
        else USER_SETTINGS
    if not base or not f.exists():
        return
    try:
        s = load_settings(f)
    except SettingsError:
        return
    env = s.setdefault("env", {})
    window = int(s.get("autoCompactWindow") or DEFAULT_WINDOW)
    old = int(env.get("CLAUDE_AUTOCOMPACT_PCT_OVERRIDE") or DEFAULT_PCT)
    new = safe_pct(window, old, base)
    if new > old:
        env["CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"] = str(new)
        f.write_text(json.dumps(s, indent=2) + "\n")
        print(f"last-token: compaction too frequent (base {base:,}); pct {old} -> {new}", file=sys.stderr)


def summary_rules(rel: str, eid: str) -> str:
    """Summarisation instructions printed to stdout for the compactor."""
    return f"""LAST-TOKEN COMPACTION RULES (follow exactly):
The conversation so far is archived on disk at {rel} (index id {eid}); your summary is a pointer, not the only copy.
Write at most ~350 words under these headings:
1. Current task and the very next step.
2. User decisions and facts: copy EVERY name, number, setting, identifier and change of plan EXACTLY, including ones that override docs/spec.
3. House rules the user gave: verbatim, one line each (skip if they are already in CLAUDE.md / .ctx/RULES.md).
4. Files created or changed: paths only.
5. Open problems / failing tests.
Do NOT include code, file contents or long tool output: refer to file paths instead.
End with the line: "Archive: {rel} (ctx.py recall <word>) for anything not listed here."
"""


# ---- read guard (PreToolUse) ---------------------------------------------------------
def big_file_info(path: str) -> tuple[int, int] | None:
    """Return (lines, bytes) when a text file is over the guard limits, else None."""
    p = Path(path)
    if p.suffix.lower() in BINARY_EXT or not p.is_file():
        return None
    size = p.stat().st_size
    with p.open("rb") as f:
        if b"\0" in f.read(8192):  # binary (database, archive, image without a known suffix): Read handles it
            return None
    if size > 5_000_000:
        return (-1, size)
    with p.open("rb") as f:
        lines = sum(1 for _ in f)
    return (lines, size) if lines > GUARD_LINES or size > GUARD_BYTES else None


def whole_cat_target(cmd: str) -> str | None:
    """The file of a bare `cat FILE` command (quoted names too), else None."""
    if re.search(r"[|;&<>`$]", cmd):
        return None
    try:
        parts = shlex.split(cmd)
    except ValueError:
        return None
    return parts[1] if len(parts) == 2 and parts[0] == "cat" else None


def deny(reason: str) -> int:
    """Emit a PreToolUse deny decision."""
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))
    return 0


def hook_guard(args: list[str]) -> int:
    """PreToolUse hook: refuse whole-file reads of big files, suggest slices or a subagent."""
    if os.environ.get("CTX_GUARD") == "off":
        return 0
    data = hook_input()
    if paused(data) or ("--global" in args and not global_turn(data.get("cwd"))):
        return 0
    tool, inp = data.get("tool_name"), data.get("tool_input")
    inp = inp if isinstance(inp, dict) else {}
    target = None
    try:
        limit = int(inp.get("limit") or 0)
    except (TypeError, ValueError):
        limit = 0
    if tool == "Read" and (not limit or limit > GUARD_LINES):
        target = inp.get("file_path")
    elif tool == "Bash":
        target = whole_cat_target(str(inp.get("command", "")))
    if not target:
        return 0
    path = target if os.path.isabs(target) else os.path.join(data.get("cwd") or os.getcwd(), target)
    info = big_file_info(path)
    if not info:
        return 0
    lines, size = info
    return deny(f"last-token: {target} is big ({lines} lines, {size // 1024} KB, ~{size // 4000}k tokens). "
                f"Reading it whole bloats the context for every later call. Instead: `grep -n '<pattern>' {target}` "
                f"then Read with offset AND limit (limit ≤{GUARD_LINES})" + ("." if os.environ.get("CTX_NO_AGENT") == "1" else
                ", or delegate to a subagent (Task, subagent_type Explore) and ask it for ≤15 lines with file:line refs."))


# ---- audit: what the fixed base of every request is made of ---------------------------
DESC_CAP = 250   # skill description cap applied by `audit --apply` (Claude Code default 1536)


def base_parts(tp: Path) -> dict[str, Any]:
    """Collect the first request shape and context attachments of a transcript."""
    parts: dict[str, Any] = {"tools": {}, "skills": {}, "files": {}, "other": {}}
    with tp.open(errors="replace") as f:
        for i, line in enumerate(f):
            if i > 400:
                break
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") == "api-request-shape" and "system" not in parts:
                shape = d.get("shape") or {}
                parts["system"] = len(json.dumps(shape.get("system", "")))
                for t in shape.get("tools") or []:
                    name = str(t.get("name", "?")) if isinstance(t, dict) else "?"
                    group = name.split("__")[1] if name.startswith("mcp__") else "built-in"
                    parts["tools"][group] = parts["tools"].get(group, 0) + len(json.dumps(t))
            a = d.get("attachment")
            if not isinstance(a, dict):
                continue
            kind = a.get("type")
            if kind == "skill_listing":
                for row in str(a.get("content", "")).split("\n- "):
                    name, _, desc = row.lstrip("- ").partition(": ")
                    if name.strip():
                        parts["skills"][name.strip()] = len(desc)
            elif kind == "instructions":
                for fl in a.get("files") or []:
                    parts["files"][str(fl.get("path"))] = len(str(fl.get("content", "")))
            elif kind in ("deferred_tools_delta", "agent_listing_delta", "mcp_instructions_delta"):
                parts["other"][kind.replace("_delta", "")] = len(json.dumps(a))
    return parts


def fmt_k(chars: int) -> str:
    """Chars → rough token count as text."""
    return f"{chars / 4000:5.1f}K"


def cmd_audit(args: list[str]) -> int:
    """Show the fixed per-request base; --apply caps skill descriptions, --off a,b hides skills."""
    root = project_root()
    tp = find_transcript(root)
    if not tp:
        print("audit: no transcript for this project yet; start one Claude Code session here first.")
        return 1
    p = base_parts(tp)
    print(f"fixed base of {tp.name} (measured {first_context(tp):,} tokens on the first call)")
    print(f"  {fmt_k(p.get('system', 0))}  system prompt (Claude Code, not adjustable)")
    for g, n in sorted(p["tools"].items(), key=lambda x: -x[1]):
        print(f"  {fmt_k(n)}  tools: {g}")
    for k, n in p["other"].items():
        print(f"  {fmt_k(n)}  {k}")
    sk = p["skills"]
    print(f"  {fmt_k(sum(sk.values()))}  skill listing ({len(sk)} skills)")
    for f, n in p["files"].items():
        print(f"  {fmt_k(n)}  memory file {f}")
    known = (p.get("system", 0) + sum(p["tools"].values()) + sum(p["other"].values())
             + sum(sk.values()) + sum(p["files"].values()))
    print(f"  {fmt_k(max(0, first_context(tp) * 4 - known))}  rest (first prompt, reminders, formatting)")
    # ---- suggestions
    save = sum(max(0, n - DESC_CAP) for n in sk.values())
    print("\nlevers (each token cut here is saved on EVERY request and lets the trigger go lower):")
    if save > 2000:
        print(f"  - cap skill descriptions at {DESC_CAP} chars: saves ~{fmt_k(save).strip()} → `ctx.py audit --apply`")
    big = sorted(sk.items(), key=lambda x: -x[1])[:8]
    if big:
        print("  - hide skills this project never uses (`ctx.py audit --off name1,name2`); biggest:")
        print("      " + ", ".join(f"{k} ({fmt_k(v).strip()})" for k, v in big))
    for f, n in p["files"].items():
        if n > 8000:
            print(f"  - {f} is {fmt_k(n).strip()}: move rarely-needed parts into a skill or @import")
    print("  - disable plugins/MCP servers unused here (`enabledPlugins` in .claude/settings.json)")
    print("  - then re-run `ctx.py init` so the compaction trigger follows the smaller base")
    if "--apply" in args or "--off" in args:
        apply_audit(root, args)
    return 0


def apply_audit(root: Path, args: list[str]) -> None:
    """Write skill listing levers into the project's .claude/settings.json."""
    f = root / ".claude" / "settings.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    s = load_settings(f)
    if "--apply" in args:
        s["skillListingMaxDescChars"] = DESC_CAP
    if "--off" in args and args.index("--off") + 1 < len(args):
        ov = s.setdefault("skillOverrides", {})
        for name in args[args.index("--off") + 1].split(","):
            if name.strip():
                ov[name.strip()] = "off"
    f.write_text(json.dumps(s, indent=2) + "\n")
    print(f"written: {f} (takes effect in the next session)")


# ---- install -------------------------------------------------------------------------
PROTOCOL = """<!-- last-token:begin (managed by .ctx/ctx.py — edit outside this block) -->
## Last Token protocol (always follow)
Context is kept small on purpose: older details are archived to disk, not lost.
1. User states a lasting house rule → `python3 .ctx/ctx.py rule "<rule>"`.
   User gives a decision/fact (name, number, setting, change of plan) → `python3 .ctx/ctx.py decide "<key>: <value>"`. Do this immediately, before the task.
2. Subtask finished → `python3 .ctx/ctx.py note "<title>" "<one line with key values>" <<'EOF'` + details (decisions, file paths, open issues) + `EOF`.
3. Need a detail you no longer see (earlier decision, finding, value) → check Rules/Decisions/Index below, then `python3 .ctx/ctx.py recall <keyword>` and read only the hit (Read offset/limit). Use it; do not paste it back.
4. Big inputs: never read a whole big file; `grep -n` then Read with offset/limit.{delegate}
5. Keep command output short (`-q`, `| tail -n 30`).
### Rules
@.ctx/RULES.md
### Decisions (latest wins)
@.ctx/DECISIONS.md
### Archive index (id · title · path · summary)
@.ctx/INDEX.md
<!-- last-token:end -->
"""


DELEGATE = (" Questions needing >2 files, >400 lines, or long logs/test output → delegate to a subagent"
            " (Task, Explore) and ask for ≤15 lines with file:line refs.")


def protocol(agent: bool = True) -> str:
    """Protocol block; without the Agent tool rule 4 drops the subagent advice."""
    return PROTOCOL.replace("{delegate}", DELEGATE if agent else "")


def install_claude_md(root: Path, agent: bool = True) -> None:
    """Insert or refresh the protocol block in CLAUDE.md."""
    f = root / "CLAUDE.md"
    text = f.read_text() if f.exists() else ""
    if BEGIN in text and END in text:
        pre, rest = text.split(BEGIN, 1)
        text = pre + protocol(agent) + rest.split(END, 1)[1].lstrip("\n")
    else:
        text = (text.rstrip() + "\n\n" if text.strip() else "") + protocol(agent)
    f.write_text(text)


def hook_entry(sub: str) -> dict:
    """Hook command entry calling this script."""
    return {"type": "command", "command": f'python3 "$CLAUDE_PROJECT_DIR/{CTX_DIR}/ctx.py" {sub}'}


def merge_hook(hooks: dict, event: str, matcher: str | None, sub: str) -> None:
    """Add our hook to an event unless an identical command already exists."""
    groups = hooks.setdefault(event, [])
    entry = hook_entry(sub)
    if any(h.get("command") == entry["command"] for g in groups for h in g.get("hooks", [])):
        return
    g: dict = {"hooks": [entry]}
    if matcher:
        g["matcher"] = matcher
    groups.append(g)


# ---- safe trigger (fixed base must fit under it) ----------------------------------------
def usage_total(entry: dict) -> int:
    """Total input tokens of one transcript entry (0 when it has no usage)."""
    m = entry.get("message")
    u = m.get("usage") if isinstance(m, dict) else None
    if not isinstance(u, dict):
        return 0
    return sum(int(u.get(k) or 0) for k in
               ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))


def first_context(path: Path, limit: int = 2000) -> int:
    """Context size of the first API call in a transcript = fixed base of that session."""
    try:
        with path.open(errors="replace") as f:
            for i, line in enumerate(f):
                if i >= limit:
                    break
                try:
                    n = usage_total(json.loads(line))
                except ValueError:
                    continue
                if n:
                    return n
    except OSError:
        pass
    return 0


def measure_base(root: Path) -> int | None:
    """Largest fixed base over this project's 5 latest sessions, None if none recorded."""
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(root))
    d = Path.home() / ".claude" / "projects" / slug
    files = sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:5] if d.is_dir() else []
    sizes = [first_context(f) for f in files]
    return max(sizes) if any(sizes) else None


def safe_pct(window: int, pct: int, base: int) -> int:
    """Raise pct so the trigger leaves MIN_WORK tokens above the base (else compaction thrashes)."""
    floor = -(-(base + MIN_WORK) * 100 // window)
    return min(MAX_PCT, max(pct, floor))


def install_lean(s: dict, lean: dict) -> None:
    """Shrink the fixed base: skill description cap, optional Agent tool removal, effort level."""
    if lean.get("skill_cap"):
        s["skillListingMaxDescChars"] = lean["skill_cap"]
    if lean.get("no_agent"):
        deny = s.setdefault("permissions", {}).setdefault("deny", [])
        if "Agent" not in deny:
            deny.append("Agent")
        s.setdefault("env", {})["CTX_NO_AGENT"] = "1"
    if lean.get("effort"):
        s["effortLevel"] = lean["effort"]


def long_window(base: int, pct: int = DEFAULT_PCT) -> int:
    """Window for 1M models so pct of it = fixed base + MIN_WORK (rounded up to 10K)."""
    need = (base + MIN_WORK) * 100 // pct
    return -(-need // 10_000) * 10_000


def apply_trigger(s: dict, window: int, pct: int, tuned: dict | None = None) -> None:
    """Compaction trigger: window per model (tuned per model when given, else `window` on 1M models), pct for all."""
    if s.get("autoCompactWindow") in OLD_WINDOWS:
        s.pop("autoCompactWindow")  # a top-level 200K window capped 1M models too (old versions wrote it)
    ms = s.setdefault("modelSettings", {})
    for m in LONG_MODELS:
        ms.setdefault(m, {})["autoCompactWindow"] = window
    for m, w in (tuned or {}).items():
        if w:
            ms.setdefault(m, {})["autoCompactWindow"] = w
        elif m not in LONG_MODELS and "autoCompactWindow" in ms.get(m, {}):
            ms[m].pop("autoCompactWindow")  # native is cheaper for this model: drop an older tuned window
            if not ms[m]:
                ms.pop(m)
    s.setdefault("env", {})["CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"] = str(pct)


def clean_old_project_settings(s: dict, keep_effort: bool) -> None:
    """Drop what old versions forced into projects: a 200K window, their pct, and effortLevel low."""
    if s.get("autoCompactWindow") in OLD_WINDOWS:
        s.pop("autoCompactWindow")
    env = s.get("env") or {}
    env.pop("CLAUDE_AUTOCOMPACT_PCT_OVERRIDE", None)
    if not env:
        s.pop("env", None)
    if not keep_effort and s.get("effortLevel") == "low":
        s.pop("effortLevel")


def install_settings(root: Path, window: int, pct: int, lean: dict | None = None, own_trigger: bool = False) -> None:
    """Merge hooks (and, when asked, an own trigger) into .claude/settings.json (keeps user keys)."""
    f = root / ".claude" / "settings.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    s = load_settings(f)
    if f.exists():
        shutil.copy(f, f.with_suffix(".json.bak"))
    lean = lean or {}
    clean_old_project_settings(s, keep_effort=bool(lean.get("effort")))
    if own_trigger:
        apply_trigger(s, window, pct)
    hooks = s.setdefault("hooks", {})
    merge_hook(hooks, "PreCompact", None, "hook-precompact")
    merge_hook(hooks, "PreToolUse", "Read|Bash", "hook-guard")
    install_lean(s, lean)
    f.write_text(json.dumps(s, indent=2) + "\n")


def cmd_init(args: list[str]) -> int:
    """Install: init [dir] [--window N] [--pct P] [--base N] [--skill-cap N] [--no-agent] [--effort E].

    The compaction trigger is set at user level (`ctx.py trigger`, `global on`); --window/--pct write
    an own trigger into the project instead."""
    opts = {"--window": DEFAULT_WINDOW, "--pct": DEFAULT_PCT, "--base": 0, "--skill-cap": 0}
    lean: dict = {}
    pos = []
    own = False
    it = iter(args)
    for a in it:
        if a in opts:
            opts[a] = int(next(it))
            own = own or a in ("--window", "--pct")
        elif a == "--no-agent":
            lean["no_agent"] = True
        elif a == "--effort":
            lean["effort"] = next(it)
        else:
            pos.append(a)
    root = Path(pos[0] if pos else ".").resolve()
    if root == Path.home().resolve() or root == Path("/") or is_spare(root):
        print(f"refusing to install into {root}: pick a project folder")
        return 2
    d = ctx_dir(root)
    if Path(__file__).resolve() != (d / "ctx.py").resolve():
        shutil.copy(Path(__file__).resolve(), d / "ctx.py")
    for name in ("RULES.md", "DECISIONS.md", "INDEX.md"):
        (d / name).touch()
    skill_src = HERE / "skill" / "SKILL.md"
    if skill_src.exists():
        dst = root / ".claude" / "skills" / "last-token"
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy(skill_src, dst / "SKILL.md")
    lean["skill_cap"] = opts["--skill-cap"]
    install_claude_md(root, agent=not lean.get("no_agent"))
    base = opts["--base"] or measure_base(root)
    pct = safe_pct(opts["--window"], opts["--pct"], base or FALLBACK_BASE)
    if pct != opts["--pct"]:
        src = f"measured {base:,}" if base else f"assumed {FALLBACK_BASE:,}"
        print(f"  note: fixed base ({src} tokens) needs room: pct {opts['--pct']} -> {pct}")
    opts["--pct"] = pct
    install_settings(root, opts["--window"], pct, lean, own_trigger=own)
    print(f"last-token {VERSION} installed in {root}")
    where = "this project" if own else "user settings (ctx.py trigger)"
    print(f"  compaction at {opts['--pct']}% of {opts['--window']:,} tokens on 1M models, set in {where}; "
          "core = CLAUDE.md + .ctx/*.md")
    print("  next: `python3 .ctx/ctx.py audit` after one session shows what else every request carries")
    return 0


# ---- mod install (user level: the mod is a no-op in projects without .ctx/) -----------
MOD_HOME = LT_HOME / "mod"
USER_SETTINGS = Path(os.environ.get("CTX_USER_SETTINGS") or Path.home() / ".claude" / "settings.json")


def plugin_dirs(s: dict) -> list[str]:
    """CLAUDE_CODE_PLUGIN_DIRS entries of a settings dict."""
    raw = (s.get("env") or {}).get("CLAUDE_CODE_PLUGIN_DIRS", "")
    return [p for p in raw.split(os.pathsep) if p]


def cmd_mod(args: list[str]) -> int:
    """mod install|uninstall|status: copy the mod to ~/.claude/last-token/mod and list it in user settings."""
    action = args[0] if args else "status"
    s = load_settings(USER_SETTINGS)
    dirs = plugin_dirs(s)
    if action == "status":
        print(f"mod {'installed' if str(MOD_HOME) in dirs and MOD_HOME.is_dir() else 'not installed'}: {MOD_HOME}")
        return 0
    if action not in ("install", "uninstall"):
        print("usage: ctx.py mod install|uninstall|status")
        return 2
    src = HERE / "mod"
    if action == "install" and not (src / "hooks" / "register.tsx").exists():
        print(f"mod source not found next to ctx.py ({src}); run from the last-token repo")
        return 1
    if USER_SETTINGS.exists():
        shutil.copy(USER_SETTINGS, USER_SETTINGS.with_name(f"settings.json.bak-ctx-{time.strftime('%Y%m%d%H%M%S')}"))
    if action == "install":
        if MOD_HOME.exists():
            shutil.rmtree(MOD_HOME)
        shutil.copytree(src, MOD_HOME)
        dirs = [d for d in dirs if d != str(MOD_HOME)] + [str(MOD_HOME)]
    else:
        dirs = [d for d in dirs if d != str(MOD_HOME)]
    env = s.setdefault("env", {})
    if dirs:
        env["CLAUDE_CODE_PLUGIN_DIRS"] = os.pathsep.join(dirs)
    else:
        env.pop("CLAUDE_CODE_PLUGIN_DIRS", None)
    USER_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    USER_SETTINGS.write_text(json.dumps(s, indent=2) + "\n")
    print(f"mod {action}ed ({MOD_HOME}); takes effect in new sessions")
    return 0


# ---- global mode: last-token in every Claude Code session ------------------------------
GLOBAL_PROTOCOL = """[last-token: active in this session (global mode). Memory of this folder: {store}]
## Last Token protocol (always follow)
Context is kept small on purpose: older details are archived to disk, not lost. `LT` below means: {cmd}
1. User states a lasting rule → `LT rule "<rule>"`. User gives a decision/fact (name, number, setting,
   change of plan) → `LT decide "<key>: <value>"`. Do this immediately, before the task.
2. Subtask finished → `LT note "<title>" "<one line with key values>" <<'EOF'` + details + `EOF`.
3. Need a detail you no longer see → check Rules/Decisions/Index below, then `LT recall <keyword>`
   and read only the hit (Read offset/limit).
4. Never read a whole big file: `grep -n`, then Read with offset/limit.
5. Keep command output short (`-q`, `| tail -n 30`).
### Rules
{rules}
### Decisions (latest wins)
{decisions}
### Archive index (id · title · path · summary)
{index}
"""
GLOBAL_HOOKS = (("SessionStart", None, "hook-session"), ("PreCompact", None, "hook-precompact"),
                ("PreToolUse", "Read|Bash", "hook-guard"))


# Throwaway folders global mode never keeps memory for (colon list; tests set it empty).
TEMP_DIRS = tuple(x for x in os.environ.get("CTX_TEMP_DIRS", "/tmp/:/var/tmp/:/.config/Claude/scratch-workspaces/").split(":") if x)


def global_turn(cwd: str | None) -> bool:
    """A user-level (--global) hook acts only in global mode, outside last-token projects and throwaway temp folders."""
    base = Path(cwd or os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd())
    if any(t in str(base) + "/" for t in TEMP_DIRS):
        return False
    if any((d / ".no-last-token").exists() for d in (base, *base.parents)):
        return False  # the user opted this folder out
    return global_enabled() and find_project(base) is None


def global_core(root: Path, real: Path) -> str:
    """Protocol + rules, decisions and index of a store folder, paths made absolute."""
    d = ctx_dir(root)
    part = {}
    for key, name in (("rules", "RULES.md"), ("decisions", "DECISIONS.md"), ("index", "INDEX.md")):
        f = d / name
        text = f.read_text().strip() if f.exists() else ""
        part[key] = text.replace(f"{CTX_DIR}/archive/", f"{d}/archive/") or "(none yet)"
    return GLOBAL_PROTOCOL.format(store=d, cmd=ctx_cmd(root, real), **part)


def hook_session(args: list[str]) -> int:
    """SessionStart hook (user level): print the global protocol + this folder's memory."""
    data = hook_input()
    cwd = data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    if paused(data) or is_spare(cwd) or not global_turn(cwd):
        return 0
    print(global_core(resolve_root(cwd), Path(cwd).resolve()))
    if global_enabled():
        retune_daily()
    return 0


def global_hook_entry(sub: str) -> dict:
    """User-level hook entry calling the global copy of ctx.py."""
    return {"type": "command", "command": f'python3 "{LT_HOME}/ctx.py" {sub} --global'}


def measure_base_global(n: int = 20) -> int | None:
    """Largest fixed base over the newest real sessions of all folders (bench/tmp runs skipped)."""
    base = Path.home() / ".claude" / "projects"
    if not base.is_dir():
        return None
    files = [f for f in base.glob("*/*.jsonl") if not re.match(r"-(tmp|var-tmp)-", f.parent.name)]
    files = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:n]
    sizes = [first_context(f) for f in files]
    return max(sizes) if any(sizes) else None


class SettingsError(Exception):
    """A settings file that is not valid JSON: never overwrite it."""


def read_settings(f: Path) -> dict:
    """A settings file as a dict, for reading only ({} when missing, empty or broken)."""
    try:
        return load_settings(f)
    except (SettingsError, OSError):
        return {}


def load_settings(f: Path) -> dict:
    """A settings file as a dict before changing it; raises SettingsError when it is broken."""
    if not f.exists() or not f.read_text().strip():
        return {}
    try:
        s = json.loads(f.read_text())
    except ValueError as e:
        raise SettingsError(f"{f} is not valid JSON ({e}); fix it first — last-token did not touch it") from e
    if not isinstance(s, dict):
        raise SettingsError(f"{f} is not a JSON object; last-token did not touch it")
    return s


def strip_global_hooks(hooks: dict) -> None:
    """Remove every user-level last-token hook entry (identified by `--global`)."""
    for event in list(hooks):
        groups = []
        for g in hooks[event]:
            g["hooks"] = [h for h in g.get("hooks", []) if not (str(h.get("command", "")).endswith(" --global")
                                                                 and "ctx.py" in str(h.get("command", "")))]
            if g["hooks"]:
                groups.append(g)
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]


def restore_trigger(s: dict, prev: dict) -> None:
    """Put back the window/pct the user had before `global on`."""
    env = s.setdefault("env", {})
    for key, val in (("autoCompactWindow", prev.get("autoCompactWindow")),):
        if val is None:
            s.pop(key, None)
        else:
            s[key] = val
    if prev.get("pct") is None:
        env.pop("CLAUDE_AUTOCOMPACT_PCT_OVERRIDE", None)
    else:
        env["CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"] = prev["pct"]
    if not env:
        s.pop("env", None)
    ms = s.get("modelSettings") or {}
    models = {m: None for m in prev.get("tuned") or []}  # windows only tuning wrote: remove
    models.update(prev.get("models") or {})
    for m, val in models.items():
        if val is None and m in ms:
            ms[m].pop("autoCompactWindow", None)
            if not ms[m]:
                ms.pop(m)
        elif val is not None:
            ms.setdefault(m, {})["autoCompactWindow"] = val
    if "modelSettings" in s and not s["modelSettings"]:
        s.pop("modelSettings")


# ---- per-model trigger from the user's own usage (docs/DESIGN.md 2.13) ---------------------
# Per call a context of C costs C·cr; a compaction costs one re-write R·cw and shrinks C to P (base + digest).
# With growth g per call the cost per call is cr·(P + E/2) + cw·R·g/E for a trigger at P + E, which is
# lowest at E* = sqrt(2·(cw/cr)·R·g). The curve is flat around E* (±50 % costs ~5 %), so we take 1.5·E*:
# fewer compactions = less digest loss for almost no quota.
TUNE_DAYS = 14
TUNE_BIAS = 1.5                  # E = 1.5·E* (quality side of a flat optimum)
TUNE_E = (60_000, 300_000)       # bounds of the working room above P
DIGEST_EST = 12_000              # context a digest adds over the fixed base
NATIVE_200K = 160_000            # 200K models compact natively near here: never set a later trigger
TUNE_PROJECTS = Path.home() / ".claude" / "projects"  # transcripts the profile reads (tests point it elsewhere)


def usage_profile(days: int = TUNE_DAYS) -> dict:
    """Per model id from the last `days` of real sessions: mean growth per call, median re-write and size after compaction."""
    root = TUNE_PROJECTS
    out: dict[str, dict] = {}
    if not root.is_dir():
        return out
    cutoff = time.time() - days * 86400
    for f in root.glob("*/*.jsonl"):
        if re.match(r"-(tmp|var-tmp)-", f.parent.name) or f.stat().st_mtime < cutoff:
            continue
        prev = None
        for c in main_calls(f):
            if c.get("boundary"):
                prev = None
                continue
            p = out.setdefault(c["model"], {"g": [], "R": [], "P": []})
            tot = c["cr"] + c["cw"] + c["inp"]
            if prev is None:
                if c["after_compact"]:
                    p["R"].append(c["cw"])
                    p["P"].append(tot)
            elif c["ts"] - prev["ts"] < 3600 and c["model"] == prev["model"]:
                grow = tot - (prev["cr"] + prev["cw"] + prev["inp"])
                if grow > 0:
                    p["g"].append(grow)
            prev = c
    return out


def tuned_window(prof: dict, base: int, model: str, pct: int = DEFAULT_PCT) -> int | None:
    """autoCompactWindow for one model from its profile; None = native compaction is cheaper (200K models)."""
    import math
    import statistics
    g = statistics.mean(prof["g"]) if len(prof.get("g", [])) >= 30 else 2_200.0
    has = len(prof.get("P", [])) >= 5
    P = max(statistics.median(prof["P"]) if has else 0, base + DIGEST_EST)  # the desktop base, not a -p run's
    R = statistics.median(prof["R"]) if has else 0.45 * P  # measured on Opus: the system prefix stays cached
    e_star = math.sqrt(2 * QUOTA_W["cache_write"] / QUOTA_W["cache_read"] * R * g)
    trigger = P + min(max(TUNE_BIAS * e_star, TUNE_E[0]), TUNE_E[1])
    limit = model_window(model)
    if limit <= 200_000 and trigger >= NATIVE_200K:
        return None
    window = -(-int(trigger * 100 / pct) // 10_000) * 10_000
    return max(100_000, min(window, limit))


def tune_windows(base: int, pct: int = DEFAULT_PCT, profile: dict | None = None) -> dict:
    """Tuned window per model: the known 1M models and every model the user ran lately (synthetic ids skipped)."""
    profile = usage_profile() if profile is None else profile
    models = set(LONG_MODELS) | {m for m in profile if m.startswith("claude-") and len(profile[m]["g"]) >= 30}
    return {m: tuned_window(profile.get(m, {}), base, m, pct) for m in sorted(models)}


def cmd_tune(args: list[str]) -> int:
    """tune [--dry]: per-model compaction windows from the last 14 days (user level; global mode re-runs it daily)."""
    base = measure_base_global() or FALLBACK_BASE
    tuned = tune_windows(base)
    for m, w in tuned.items():
        print(f"{m}: " + (f"window {w:,} → compacts at ~{w * DEFAULT_PCT // 100:,}" if w else "native (cheaper)"))
    if "--dry" in args:
        return 0
    s = load_settings(USER_SETTINGS)
    if USER_SETTINGS.exists():
        shutil.copy(USER_SETTINGS, USER_SETTINGS.with_name("settings.json.bak-ctx-tune"))
    apply_trigger(s, long_window(base), DEFAULT_PCT, tuned)
    USER_SETTINGS.write_text(json.dumps(s, indent=2) + "\n")
    LT_HOME.mkdir(parents=True, exist_ok=True)
    flag = read_settings(GLOBAL_FLAG)
    if flag.get("enabled"):
        flag["tuned"] = sorted(tuned)
        GLOBAL_FLAG.write_text(json.dumps(flag, indent=2) + "\n")
    (LT_HOME / "tune.json").write_text(json.dumps({"at": time.time(), "windows": tuned}) + "\n")
    return 0


def retune_daily() -> None:
    """Start `tune` in the background at most once a day (SessionStart must stay fast; never raises)."""
    try:
        stamp = LT_HOME / "tune.json"
        if time.time() - float(read_settings(stamp).get("at") or 0) < 86400 or not (LT_HOME / "ctx.py").exists():
            return
        stamp.write_text(json.dumps({"at": time.time(), "running": True}) + "\n")  # no second start meanwhile
        import subprocess
        subprocess.Popen([sys.executable, str(LT_HOME / "ctx.py"), "tune"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, start_new_session=True)
    except Exception:
        pass


def cmd_trigger(args: list[str]) -> int:
    """trigger [--window N] [--pct P]: set the user-level compaction trigger (1M models: window, all: pct)."""
    opts = {a: int(args[i + 1]) for i, a in enumerate(args[:-1]) if a in ("--window", "--pct")}
    s = load_settings(USER_SETTINGS)
    base = measure_base_global() or FALLBACK_BASE
    window = opts.get("--window") or long_window(base, opts.get("--pct", DEFAULT_PCT))
    pct = safe_pct(window, opts.get("--pct", DEFAULT_PCT), base)
    if USER_SETTINGS.exists():
        shutil.copy(USER_SETTINGS, USER_SETTINGS.with_name(f"settings.json.bak-ctx-{time.strftime('%Y%m%d%H%M%S')}"))
    apply_trigger(s, window, pct)
    USER_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    USER_SETTINGS.write_text(json.dumps(s, indent=2) + "\n")
    print(f"trigger: {pct}% of {window:,} on {', '.join(LONG_MODELS)}; {pct}% of the own window elsewhere")
    return 0


def cmd_global(args: list[str]) -> int:
    """global on|off|status: run last-token in every Claude Code session (user settings + store)."""
    action = args[0] if args else "status"
    if action == "status":
        print(f"global mode: {'on' if global_enabled() else 'off'} ({GLOBAL_FLAG}); store: {STORE}")
        return 0
    if action not in ("on", "off"):
        print("usage: ctx.py global on|off|status")
        return 2
    s = load_settings(USER_SETTINGS)
    if USER_SETTINGS.exists():
        shutil.copy(USER_SETTINGS, USER_SETTINGS.with_name(f"settings.json.bak-ctx-{time.strftime('%Y%m%d%H%M%S')}"))
    flag = read_settings(GLOBAL_FLAG)
    hooks = s.setdefault("hooks", {})
    strip_global_hooks(hooks)
    env = s.setdefault("env", {})
    if action == "on":
        LT_HOME.mkdir(parents=True, exist_ok=True)
        if Path(__file__).resolve() != (LT_HOME / "ctx.py").resolve():
            shutil.copy(Path(__file__).resolve(), LT_HOME / "ctx.py")
        if "prev" not in flag:  # remember what the user had, for `global off`
            flag["prev"] = {"autoCompactWindow": s.get("autoCompactWindow"),
                            "pct": env.get("CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"),
                            "models": {m: (s.get("modelSettings") or {}).get(m, {}).get("autoCompactWindow")
                                       for m in LONG_MODELS}}
        elif "models" not in (flag["prev"] or {}):  # flag from <0.7: those per-model windows were ours
            flag["prev"] = {**(flag["prev"] or {}), "models": {m: None for m in LONG_MODELS}}
        base = measure_base_global() or FALLBACK_BASE
        pct = DEFAULT_PCT
        window = long_window(base, pct)
        tuned = tune_windows(base, pct)
        apply_trigger(s, window, pct, tuned)
        flag["tuned"] = sorted(tuned)
        for event, matcher, sub in GLOBAL_HOOKS:
            g: dict = {"hooks": [global_hook_entry(sub)]}
            if matcher:
                g["matcher"] = matcher
            hooks.setdefault(event, []).append(g)
        flag.update({"enabled": True, "version": VERSION, "base": base, "pct": pct})
        per = ", ".join(f"{m} ~{w * pct // 100 // 1000}K" if w else f"{m} native" for m, w in tuned.items())
        msg = (f"global mode on: compaction per model (tuned to your usage, fixed base {base:,}): {per}; "
               f"re-tuned daily")
    else:
        if "prev" in flag:  # a second `off` has nothing left to restore: leave the settings alone
            restore_trigger(s, {**(flag.pop("prev") or {}), "tuned": flag.pop("tuned", [])})
        flag["enabled"] = False
        msg = "global mode off (project installs keep working; store kept)"
    if not hooks:
        s.pop("hooks", None)
    GLOBAL_FLAG.parent.mkdir(parents=True, exist_ok=True)
    GLOBAL_FLAG.write_text(json.dumps(flag, indent=2) + "\n")
    USER_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    USER_SETTINGS.write_text(json.dumps(s, indent=2) + "\n")
    print(msg + "; takes effect in new sessions")
    return 0


def cmd_doctor(args: list[str]) -> int:
    """doctor: check the global install part by part and print a clear success / fix message."""
    s = read_settings(USER_SETTINGS)
    flag = read_settings(GLOBAL_FLAG)
    # One row per part: (name, ok, what it means for the user)
    rows = [
        ("Python 3.9+", sys.version_info >= (3, 9), f"python {sys.version.split()[0]}"),
        ("Global mode", bool(flag.get("enabled")), "active in every Claude Code session"),
        ("Memory loader (SessionStart)", has_hook(s, "hook-session"), "rules + decisions survive every compaction"),
        ("Archive (PreCompact)", has_hook(s, "hook-precompact"), "nothing is lost when context is compacted"),
        ("Big-file guard (PreToolUse)", has_hook(s, "hook-guard"), "no 50K-token whole-file reads"),
        ("Mod (no-LLM compaction, cold pruning)", str(MOD_HOME) in plugin_dirs(s) and MOD_HOME.is_dir(),
         "compaction without a paid summarizer call"),
    ]
    tuned = {m: (s.get("modelSettings") or {}).get(m, {}).get("autoCompactWindow") for m in flag.get("tuned", [])}
    pct = flag.get("pct") or DEFAULT_PCT
    # Report
    for name, ok, why in rows:
        print(f"  {'✅' if ok else '❌'} {name:<40} {why}")
    if tuned:
        per = ", ".join(f"{m.replace('claude-', '')} ~{w * pct // 100 // 1000}K" for m, w in tuned.items() if w)
        print(f"  ✅ {'Compaction tuned to YOUR usage':<40} {per}")
    if all(ok for _, ok, _ in rows):
        print(f"\n  ★ Last Token {VERSION} is installed. Open a NEW Claude Code session; the status line shows 'last-token ✓'.")
        return 0
    print("\n  ✗ Some parts are missing: run `bash install.sh --global` again from the repo.")
    return 1


# ---- health + savings for the mod's pane ------------------------------------------------
def has_hook(s: dict, sub: str) -> bool:
    """True when a settings dict runs `ctx.py <sub>`."""
    return any(sub in str(h.get("command", "")) for g in sum((s.get("hooks") or {}).values(), [])
               for h in g.get("hooks", []))


def model_window(model: str | None) -> int:
    """Context window of a model (1M for the measured long-context ones, else 200K)."""
    return 1_000_000 if model and any(model.startswith(m) for m in LONG_MODELS) else 200_000


def effective_trigger(real: Path, model: str | None = None) -> tuple[int, int]:
    """(window, pct) as Claude Code resolves them: per-model over top level, project over user, capped by the model."""
    user = read_settings(USER_SETTINGS)
    proj: dict = {}
    for f in (real / ".claude" / "settings.json", real / ".claude" / "settings.local.json"):
        s = read_settings(f)
        proj.update({k: v for k, v in s.items() if k != "env"})
        proj.setdefault("env", {}).update(s.get("env") or {})

    def per_model(s: dict) -> int:
        return int(((s.get("modelSettings") or {}).get(model or "") or {}).get("autoCompactWindow") or 0)
    window = (per_model(proj) or per_model(user) or int(proj.get("autoCompactWindow") or 0)
              or int(user.get("autoCompactWindow") or 0) or model_window(model))
    window = min(window, model_window(model)) if model else window
    pct = int((proj.get("env") or {}).get("CLAUDE_AUTOCOMPACT_PCT_OVERRIDE")
              or (user.get("env") or {}).get("CLAUDE_AUTOCOMPACT_PCT_OVERRIDE") or 0)
    return window, pct


def health(real: Path, tp: Path | None) -> dict:
    """Which parts of last-token work in this folder: mode, hooks, trigger vs. fixed base."""
    root = resolve_root(real)
    proj = find_project(real)
    mode = "project" if proj else "global" if is_store(root) else "off"
    settings = read_settings(proj / ".claude" / "settings.json") if proj else read_settings(USER_SETTINGS)
    if proj and not has_hook(settings, "hook-precompact"):
        settings = read_settings(USER_SETTINGS)
    window, pct = effective_trigger(proj or real, transcript_model(tp))
    trigger = window * pct // 100 if window and pct else 0
    base = first_context(tp) if tp and tp.exists() else 0
    checks = [
        {"name": "Early compaction", "ok": bool(trigger), "detail": f"at {fmt_tok(trigger)} tokens" if trigger else "not set"},
        {"name": "Loop safety", "ok": not trigger or not base or trigger - base >= MIN_WORK // 2,
         "detail": f"fixed base {fmt_tok(base)}" if base else "not measured"},
        {"name": "Archive (PreCompact)", "ok": has_hook(settings, "hook-precompact"), "detail": ""},
        {"name": "Big-file guard", "ok": has_hook(settings, "hook-guard"), "detail": ""},
    ]
    if mode == "global":
        checks.append({"name": "Memory load (SessionStart)", "ok": has_hook(settings, "hook-session"), "detail": ""})
    label = proj.name if proj else str(real)
    return {"mode": mode, "label": label, "store": str(ctx_dir(root)) if mode != "off" else "", "checks": checks}


def transcript_model(tp: Path | None) -> str | None:
    """Model of the newest main-thread reply in a transcript."""
    model = None
    if tp and tp.exists():
        for line in tp.open(errors="replace"):
            if '"model"' in line and '"assistant"' in line:
                m = re.search(r'"model":"(claude-[^"]+)"', line)
                model = m.group(1) if m else model
    return model


def fmt_tok(n: int) -> str:
    """93594 → '94K', 4215145 → '4.2M'."""
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{round(n / 1e3)}K" if n >= 1e3 else str(n)


def cmd_panel(args: list[str]) -> int:
    """panel --session ID [--at DIR]: JSON for the mod's pane (savings + health)."""
    sid = args[args.index("--session") + 1] if "--session" in args[:-1] else ""
    real = real_folder()
    tp = find_session_transcript(sid)
    sv = savings(tp) if tp and tp.exists() else {}
    cache = cache_report(tp) if sv else {"busts": {}, "idle_compactions": 0}
    if sv:
        sv["_idle_pre"] = cache.pop("_idle_pre", 0)
        k = model_mul(transcript_model(tp))
        cache["bust_quota"] = round(k * QUOTA_W["cache_write"] * sum(b["tokens"] for b in cache["busts"].values()), 3)
    q = quota_report(tp, sv) if sv else {"quota": 0, "quota_sub": 0, "quota_saved": 0, "quota_pct": 0, "model": "", "measured": True}
    sv = {k: v for k, v in sv.items() if not k.startswith("_")} or {"requests": 0, "sent": 0, "saved": 0, "compactions": 0,
                                                                   "deterministic": 0, "context": 0, "pct": 0}
    out = {**sv, **q, "cache": cache, **health(real, tp)}
    print(json.dumps(out, ensure_ascii=False))
    return 0


COMMANDS = {"init": cmd_init, "note": cmd_note, "decide": cmd_decide, "rule": cmd_rule,
            "recall": cmd_recall, "pause": cmd_pause, "resume": lambda a: cmd_pause(a, on=False), "trigger": cmd_trigger, "check": cmd_check, "doctor": cmd_doctor, "status": cmd_status, "audit": cmd_audit,
            "savings": cmd_savings, "panel": cmd_panel, "tune": cmd_tune, "global": cmd_global, "hook-session": hook_session, "compact-summary": cmd_compact_summary, "mod": cmd_mod, "hook-precompact": hook_precompact, "hook-guard": hook_guard}


def main(argv: list[str]) -> int:
    """Dispatch a sub-command (`--at DIR` first = act for that folder)."""
    if len(argv) >= 2 and argv[0] == "--at":
        os.environ["CLAUDE_PROJECT_DIR"] = argv[1]
        argv = argv[2:]
    if not argv or argv[0] not in COMMANDS:
        print(f"last-token {VERSION}\nusage: ctx.py {{{','.join(COMMANDS)}}} ...")
        return 2
    try:
        return COMMANDS[argv[0]](argv[1:])
    except SettingsError as e:
        print(f"last-token: {e}", file=sys.stderr)
        return 0 if argv[0].startswith("hook-") else 1
    except Exception as e:  # hooks must never crash the session
        print(f"last-token error: {e}", file=sys.stderr)
        return 0 if argv[0].startswith("hook-") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
