# DESIGN — context-economy

Goal: long Claude Code sessions that stay small (< ~40 % of a 200K reference window),
cost fewer tokens than "work until full, then start a new chat and re-explain", keep
obeying the rules from turn 1, and can still recall archived details.

## 1. Alternatives considered

### A. Memory bank (Cline style)
The agent keeps 5–6 markdown files (brief, progress, decisions…) and reads all of them at
the start of every task. Native compaction unchanged.
- \+ zero deps, human-readable, works with any agent.
- − purely voluntary: if the model forgets to update/read, nothing happens.
- − reads *all* files each time → cost grows with project age.
- − does nothing about the real bloat (tool outputs) or about late compaction.

### B. Handoff + `/clear` loop
A `Stop` hook measures fill from the transcript; above X % it writes `HANDOFF.md` and asks
the user to run `/clear`; `SessionStart(clear)` injects the handoff.
- \+ smallest possible context after each reset.
- − needs a human action every time (hooks cannot clear or compact).
- − throws away the preserved tail and recently-read files that native compaction keeps;
  the model re-reads files → extra tokens (this is our baseline **(b)**, roughly).
- − handoff quality depends on one LLM write at the worst moment (context already full).

### C. Retrieval server (claude-mem / basic-memory style)
Hooks stream every event to a local DB + vector index; an MCP tool searches it.
- \+ powerful recall over months.
- − heavy dependencies, background process, often an extra LLM per event.
- − injects retrieved snippets per prompt → per-turn tokens, cache churn.

### D. Early native compaction + deterministic archive + tiny core *(chosen)*
Keep Claude Code's own compaction but trigger it early, steer what the summary keeps,
archive everything raw right before it happens, and keep a tiny always-loaded index.
- \+ builds only on documented features; one stdlib Python script; no server.
- \+ no per-turn injection: the core changes only at compaction, which rebuilds the
  cache anyway → prompt-cache friendly.
- \+ nothing is lost: the raw (condensed) conversation is on disk before each summary.
- − compaction calls themselves cost tokens (one summarisation request per compaction).
- − recall of archived details still needs the model to look at the index (but the index
  is always in context, and the summary ends with the archive path).

Why D: it is the only option that is automatic (no human step), adds no per-turn tokens,
and attacks both drivers of cost: *prefix length × number of calls* (early compaction) and
*single huge tool outputs* (read guard).

## 2. Components

```
your-project/
├── CLAUDE.md                ← your rules + project summary + our 15-line protocol block
├── .claude/settings.json    ← env + 3 hooks (merged, your hooks kept)
└── .ctx/
    ├── ctx.py               ← the only script (stdlib)
    ├── RULES.md             ← house rules the user states in chat     (@imported, always loaded)
    ├── DECISIONS.md         ← one line per user decision / fact   (@imported, always loaded)
    ├── INDEX.md             ← one line per archive entry           (@imported, always loaded)
    └── archive/
        ├── N001-<slug>.md   ← notes written by the agent at subtask end
        └── L001-log.md      ← condensed raw conversation, written before each compaction
```

### 2.1 Core (always in context, cache friendly)
- = `CLAUDE.md` (user rules + project summary) + protocol block + `RULES.md` + `DECISIONS.md` + `INDEX.md`.
  Rules given in chat are persisted with `ctx.py rule "..."` so they survive every compaction verbatim.
- **Size limit: 2,500 tokens total** (≈ 10 KB; ~1.25 % of 200K). Docs advise < 200 lines
  per CLAUDE.md; we stay well below. `ctx.py check` warns when exceeded.
- `INDEX.md` keeps the newest 40 entries; older ones roll into `archive/INDEX-old.md`
  (one pointer line stays). `DECISIONS.md` keeps 60 lines; `ctx.py decide` replaces a line
  with the same key, so "latest decision wins" and it cannot grow without bound.
- Claude Code re-reads root CLAUDE.md + imports from disk after compaction [doc+test], so the
  index is refreshed exactly when the cache is rebuilt anyway. Edits in between do not touch
  the cached prefix [doc].

### 2.2 Archive and index format (how the agent knows what it forgot)
One line per entry, newest last:
```
- N004 · Pricing port from legacy · .ctx/archive/N004-pricing-port.md · bulk tiers 50/250/1000, HALF_EVEN rounding
- L002 · log before compaction #2 · .ctx/archive/L002-log.md · prompts: add tax module | fix parser bug | read spec §7
```
`id · title · path · one-line summary`. Notes (`N`) are written by the agent; logs (`L`)
are written by the hook. The protocol block tells the agent: *"If you need a detail that
is not in context, check INDEX/DECISIONS, then `grep -n` the archive and read only the hit."*

### 2.3 When to archive — both
1. **Subtask end (agent, cheap, high quality):** `python3 .ctx/ctx.py note "<title>" "<one line>"`
   with details on stdin. Decisions from the user go to `ctx.py decide "key: value"` the
   moment they are given.
2. **Threshold (hook, deterministic, guaranteed):** project settings set
   `autoCompactWindow: 200000` and `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` (default 25; 35 in round 0–1, see BENCHMARK.md) so native
   auto-compaction fires at ~33 % of the reference window instead of ~97 % of 1M.
   The `PreCompact` hook runs first and (a) writes `L00n-log.md` from the transcript since the
   last boundary, (b) adds the index line, (c) prints summarisation rules to stdout, which
   Claude Code feeds to the summariser [doc+test].

### 2.4 Heavy reading → subagents / slices
- `PreToolUse(Read)` guard: whole-file read of a file > 400 lines or > 32 KB is **denied** with
  a reason that states the size and the alternatives (`grep -n` + `Read offset/limit`, or a
  subagent). `PreToolUse(Bash)` guard does the same for `cat <bigfile>`.
- Protocol rule: delegate to a subagent (Explore) when answering needs > 2 files or > 400
  lines, or log/test output > 200 lines; ask for ≤ 15 lines with `file:line` refs.
- Subagent tokens are still paid, but they are paid once; reading in the main thread is paid
  again on every later call until the next compaction.

### 2.5 Recall and release
- Recall trigger: the needed detail is a value/decision/reason not visible in context; the
  index or decisions mention it; or the user refers to earlier work.
- Procedure: `grep -n "<keyword>" .ctx/archive/*.md` → `Read` only the hit (offset/limit).
- Release: don't paste recalled text back into answers; put results in files. The next
  compaction drops it from the context; the archive still holds it.

### 2.6 Minimising loss in summaries
1. Raw log archived *before* the summariser runs → the summary is a cache, not the only copy.
2. Summariser instructions (PreCompact stdout): keep current task + next step, every user
   decision with exact values, changed file paths, open issues; no code or file contents;
   end with the archive path.
3. Decisions live in `DECISIONS.md` (core) — they survive any number of compactions verbatim.
4. Index lines carry the 3–6 most important keywords so `grep` finds them.

## 3. What we deliberately do not do
- No per-prompt injection (`UserPromptSubmit`) → no per-turn tokens, no cache churn.
- No extra LLM calls, no MCP server, no database.
- No `Stop`-hook nagging (each forced continuation is a full extra call).

## 4. Risks
- Too-early compaction → many summarisation calls; tuned in the benchmark (PCT value).
- Weak models may skip `note`/`decide`; the deterministic log archive is the safety net.
- Native compaction re-attaches recently read files; the read guard keeps those small.
