#!/usr/bin/env python3
"""context-economy: small core + disk archive + early native compaction for Claude Code.

Single stdlib-only script. Installed into a project as .ctx/ctx.py.
Commands (agent/user): init, rule, decide, note, recall, check, status
Commands (hooks):      hook-precompact, hook-guard
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

VERSION = "0.2.0"

# ---- tunables (can be overridden with env vars of the same name) -----------------
CTX_DIR = ".ctx"
MAX_INDEX = int(os.environ.get("CTX_MAX_INDEX", 40))          # index lines kept in core
MAX_DECISIONS = int(os.environ.get("CTX_MAX_DECISIONS", 60))  # decision lines kept in core
GUARD_LINES = int(os.environ.get("CTX_GUARD_LINES", 400))     # whole-file read limit (lines)
GUARD_BYTES = int(os.environ.get("CTX_GUARD_BYTES", 32_000))  # whole-file read limit (bytes)
CORE_TOKEN_LIMIT = 2500                                        # warn above this core size
DEFAULT_WINDOW = 200_000                                       # reference context window
DEFAULT_PCT = 25                                               # compact at 25 % of window (benchmark round 2)
BEGIN = "<!-- context-economy:begin"
END = "<!-- context-economy:end -->"
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".ipynb", ".zip", ".gz"}

HERE = Path(__file__).resolve().parent


# ---- paths -------------------------------------------------------------------------
def project_root() -> Path:
    """Return the project root: $CLAUDE_PROJECT_DIR, else nearest parent holding .ctx/."""
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env)
    cur = Path.cwd().resolve()
    for p in [cur, *cur.parents]:
        if (p / CTX_DIR).is_dir():
            return p
    return cur


def ctx_dir(root: Path) -> Path:
    """Return the .ctx directory of a project, creating the archive folder."""
    d = root / CTX_DIR
    (d / "archive").mkdir(parents=True, exist_ok=True)
    return d


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
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
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
    print(f"archived {eid} -> {rel}")
    return 0


def upsert_keyed_line(path: Path, key: str, line: str, cap: int) -> None:
    """Replace the line whose key matches (case-insensitive) or append; keep at most cap."""
    lines = [l for l in path.read_text().splitlines() if l.startswith("- ")] if path.exists() else []
    norm = key.strip().lower()
    lines = [l for l in lines if l[2:].split(":", 1)[0].strip().lower() != norm]
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
    upsert_keyed_line(ctx_dir(root) / "DECISIONS.md", key, line, MAX_DECISIONS)
    print(f"decision saved: {line[2:]}")
    return 0


def cmd_rule(args: list[str]) -> int:
    """Record a lasting house rule given by the user: rule "<rule text>"."""
    text = one_line(" ".join(args), 300)
    if not text:
        print('usage: ctx.py rule "<rule>"')
        return 2
    path = ctx_dir(project_root()) / "RULES.md"
    lines = [l for l in path.read_text().splitlines() if l.startswith("- ")] if path.exists() else []
    if f"- {text}" not in lines:
        lines.append(f"- {text}")
    path.write_text("\n".join(lines) + "\n")
    print(f"rule saved ({len(lines)} rules)")
    return 0


def cmd_recall(args: list[str]) -> int:
    """Search the archive for lines containing all keywords; print path:line hits."""
    words = [w.lower() for w in args if w.strip()]
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
            if all(w in line.lower() for w in words):
                print(f"{f.relative_to(d.parent)}:{i}: {one_line(line, 220)}")
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
    """Return the newest transcript file of this project."""
    base = Path.home() / ".claude" / "projects"
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(root.resolve()))
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
            key = (m.get("id"), kind, json.dumps(b, sort_keys=True)[:300])
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
        if kind == "text" and text and not d.get("isMeta") and not text.lstrip().startswith("<"):
            prompts.append(text)
            return [f"\n### User\n{text}"]
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
    try:
        data = json.load(sys.stdin)
    except ValueError:
        data = {}
    root = Path(data.get("cwd") or project_root())
    root = project_root() if not (root / CTX_DIR).is_dir() else root
    eid = next_id(root, "L")
    rel = f"{CTX_DIR}/archive/{eid}-log.md"
    tp = data.get("transcript_path")
    md, prompts = condense_transcript(Path(tp)) if tp and Path(tp).exists() else ([], [])
    stamp = time.strftime("%Y-%m-%d %H:%M")
    head = [f"# {eid} — conversation log archived before compaction ({data.get('trigger', '?')}, {stamp})",
            "", "## User prompts in this segment"]
    head += [f"{i}. {one_line(p, 400)}" for i, p in enumerate(prompts, 1)] + ["", "## Condensed transcript"]
    text = "\n".join(head + md).replace(str(root) + "/", "")
    (root / rel).write_text(text + "\n")
    topics = " | ".join(one_line(p, 45) for p in prompts[-6:]) or "no user prompts"
    add_index_line(root, eid, f"log before compaction ({len(prompts)} prompts)", rel, "prompts: " + topics)
    print(summary_rules(rel, eid))
    return 0


def summary_rules(rel: str, eid: str) -> str:
    """Summarisation instructions printed to stdout for the compactor."""
    return f"""CONTEXT-ECONOMY COMPACTION RULES (follow exactly):
The conversation so far is archived on disk at {rel} (index id {eid}); your summary is a pointer, not the only copy.
Write at most ~350 words under these headings:
1. Current task and the very next step.
2. User decisions and facts: copy EVERY name, number, setting, identifier and change of plan EXACTLY, including ones that override docs/spec.
3. House rules the user gave: verbatim, one line each (skip if they are already in CLAUDE.md / .ctx/RULES.md).
4. Files created or changed: paths only.
5. Open problems / failing tests.
Do NOT include code, file contents or long tool output: refer to file paths instead.
End with the line: "Archive: {rel} (python3 .ctx/ctx.py recall <word>) for anything not listed here."
"""


# ---- read guard (PreToolUse) ---------------------------------------------------------
def big_file_info(path: str) -> tuple[int, int] | None:
    """Return (lines, bytes) when a text file is over the guard limits, else None."""
    p = Path(path)
    if p.suffix.lower() in BINARY_EXT or not p.is_file():
        return None
    size = p.stat().st_size
    if size > 5_000_000:
        return (-1, size)
    with p.open("rb") as f:
        lines = sum(1 for _ in f)
    return (lines, size) if lines > GUARD_LINES or size > GUARD_BYTES else None


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
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    tool, inp = data.get("tool_name"), data.get("tool_input") or {}
    target = None
    if tool == "Read" and not inp.get("limit"):
        target = inp.get("file_path")
    elif tool == "Read" and int(inp.get("limit") or 0) > GUARD_LINES:
        target = inp.get("file_path")
    elif tool == "Bash":
        m = re.fullmatch(r"\s*cat\s+([^\s|;&<>]+)\s*", str(inp.get("command", "")))
        target = m.group(1) if m else None
    if not target:
        return 0
    path = target if os.path.isabs(target) else os.path.join(data.get("cwd") or os.getcwd(), target)
    info = big_file_info(path)
    if not info:
        return 0
    lines, size = info
    return deny(f"context-economy: {target} is big ({lines} lines, {size // 1024} KB, ~{size // 4000}k tokens). "
                f"Reading it whole bloats the context for every later call. Instead: `grep -n '<pattern>' {target}` "
                f"then Read with offset/limit (≤{GUARD_LINES} lines), or delegate to a subagent (Task, subagent_type "
                f"Explore) and ask it for ≤15 lines with file:line refs.")


# ---- install -------------------------------------------------------------------------
PROTOCOL = """<!-- context-economy:begin (managed by .ctx/ctx.py — edit outside this block) -->
## Context economy protocol (always follow)
Context is kept small on purpose: older details are archived to disk, not lost.
1. User states a lasting house rule → `python3 .ctx/ctx.py rule "<rule>"`.
   User gives a decision/fact (name, number, setting, change of plan) → `python3 .ctx/ctx.py decide "<key>: <value>"`. Do this immediately, before the task.
2. Subtask finished → `python3 .ctx/ctx.py note "<title>" "<one line with key values>" <<'EOF'` + details (decisions, file paths, open issues) + `EOF`.
3. Need a detail you no longer see (earlier decision, finding, value) → check Rules/Decisions/Index below, then `python3 .ctx/ctx.py recall <keyword>` and read only the hit (Read offset/limit). Use it; do not paste it back.
4. Big inputs: never read a whole big file; `grep -n` then Read with offset/limit. Questions needing >2 files, >400 lines, or long logs/test output → delegate to a subagent (Task, Explore) and ask for ≤15 lines with file:line refs.
5. Keep command output short (`-q`, `| tail -n 30`).
### Rules
@.ctx/RULES.md
### Decisions (latest wins)
@.ctx/DECISIONS.md
### Archive index (id · title · path · summary)
@.ctx/INDEX.md
<!-- context-economy:end -->
"""


def install_claude_md(root: Path) -> None:
    """Insert or refresh the protocol block in CLAUDE.md."""
    f = root / "CLAUDE.md"
    text = f.read_text() if f.exists() else ""
    if BEGIN in text and END in text:
        pre, rest = text.split(BEGIN, 1)
        text = pre + PROTOCOL + rest.split(END, 1)[1].lstrip("\n")
    else:
        text = (text.rstrip() + "\n\n" if text.strip() else "") + PROTOCOL
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


def install_settings(root: Path, window: int, pct: int) -> None:
    """Merge env, compaction window and hooks into .claude/settings.json (keeps user keys)."""
    f = root / ".claude" / "settings.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    s = json.loads(f.read_text()) if f.exists() and f.read_text().strip() else {}
    if f.exists():
        shutil.copy(f, f.with_suffix(".json.bak"))
    s["autoCompactWindow"] = window
    s.setdefault("env", {})["CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"] = str(pct)
    hooks = s.setdefault("hooks", {})
    merge_hook(hooks, "PreCompact", None, "hook-precompact")
    merge_hook(hooks, "PreToolUse", "Read|Bash", "hook-guard")
    f.write_text(json.dumps(s, indent=2) + "\n")


def cmd_init(args: list[str]) -> int:
    """Install into a project: init [dir] [--window N] [--pct P]."""
    opts = {"--window": DEFAULT_WINDOW, "--pct": DEFAULT_PCT}
    pos = []
    it = iter(args)
    for a in it:
        if a in opts:
            opts[a] = int(next(it))
        else:
            pos.append(a)
    root = Path(pos[0] if pos else ".").resolve()
    d = ctx_dir(root)
    if Path(__file__).resolve() != (d / "ctx.py").resolve():
        shutil.copy(Path(__file__).resolve(), d / "ctx.py")
    for name in ("RULES.md", "DECISIONS.md", "INDEX.md"):
        (d / name).touch()
    skill_src = HERE / "skill" / "SKILL.md"
    if skill_src.exists():
        dst = root / ".claude" / "skills" / "context-economy"
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy(skill_src, dst / "SKILL.md")
    install_claude_md(root)
    install_settings(root, opts["--window"], opts["--pct"])
    print(f"context-economy {VERSION} installed in {root}")
    print(f"  compaction at {opts['--pct']}% of {opts['--window']:,} tokens; core = CLAUDE.md + .ctx/*.md")
    return 0


COMMANDS = {"init": cmd_init, "note": cmd_note, "decide": cmd_decide, "rule": cmd_rule,
            "recall": cmd_recall, "check": cmd_check, "status": cmd_status,
            "hook-precompact": hook_precompact, "hook-guard": hook_guard}


def main(argv: list[str]) -> int:
    """Dispatch a sub-command."""
    if not argv or argv[0] not in COMMANDS:
        print(f"context-economy {VERSION}\nusage: ctx.py {{{','.join(COMMANDS)}}} ...")
        return 2
    try:
        return COMMANDS[argv[0]](argv[1:])
    except Exception as e:  # hooks must never crash the session
        print(f"context-economy error: {e}", file=sys.stderr)
        return 0 if argv[0].startswith("hook-") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
