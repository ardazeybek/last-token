# DESIGN — last-token

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

### 2.7 The mod (0.4.0)
The fixed base is re-sent on every call (36 % of bench tokens), so the mod trims it through the
official mods hooks instead of asking the model to be brief. Compaction becomes deterministic:
the conversation is replaced by one digest (verbatim user prompts, files changed, recent steps)
because the archive, the core and `auto_capture` already hold what a summary would keep. Only
new messages are returned (kept engine messages re-chain to the old history on `--resume`).

### 2.8 Digest that keeps the work going (0.5.0)
A real desktop session (103K → 2.6K tokens, mid-turn, phone UI work) showed the 0.4.0 digest lost
the thread: no task list, the agent's own conclusions buried under 25 empty `adb tap` lines, no
hint that the turn was still running, and screenshots silently gone. The digest now starts with a
"you were in the MIDDLE of the request" state line when the newest step is a tool call, replays the
task list (`TodoWrite` / desktop `update_plan` / `wrap_up`) over the whole transcript, lists the
agent's last 6 remarks and the last images it looked at, collapses repeated empty steps (`×3`) and
lists older actions only once. It is still deterministic and about the same size.
The row is user-role for the model, so `ui.render` draws it as one dim line on every surface:
the terminal keeps ctrl+o, other surfaces (no ctrl+o, so `isExpanded` is always true) get a
show/hide button. `auto_capture` also knows Turkish decision phrases and letters.

### 2.9 Savings pane (0.5.0)
`ctx.py savings` replays the transcript against a counterfactual: same requests, but every early
compaction's dropped tokens stay in context until native compaction would fire (167K for a 200K
window, 967K for 1M; it then keeps 20K more than our digest and costs one summarizer call of that
size). Compactions near the native point count as native; our compactions that still called the
summarizer count against us. The mod adds what its slimmer base removed from each main-thread
request (chars / 4) and shows both in a pane (`/lt-savings`) and the status line, refreshed once per
turn (no timer). Cross-check: bench r2/c gives 9.3M sent + 17.7M saved ≈ the 24.6M of condition a.

### 2.10 Global mode (0.6.0)
Goal: last-token in every session (settings tweaks, one-off jobs), not only in installed projects.
User-level hooks carry `--global` and act only when the flag file exists and no project `.ctx/` is
at or above the folder, so project installs and global mode never both fire. Memory lives outside
the folder (`~/.claude/last-token/store/<slug>/.ctx`) so nothing is written into random folders;
there is no CLAUDE.md to import it, so `SessionStart` injects the same core once per session and
after each compaction. The mod uses the same lookup: pane + digest only where a store or `.ctx` applies.

### 2.11 Quality first (0.7.0, audit 2026-11-20)
A zirve audit (docs/AUDIT-2026-11-20.md) found the system saving tokens at the cost of answers:
- **No low effort by default.** autoinstall had written `effortLevel: low` into 11 of 12 projects;
  the bench gain was Haiku on a simple task. Removed; `init` deletes the old value.
- **Later trigger.** Project `autoCompactWindow 200000` + pct 54-58 % overrode the user's 400K for
  Opus and compacted every ~100K, mid-task (13 times in one real session). Now the user level holds
  the trigger: `modelSettings.<1M model>.autoCompactWindow 400000`, pct 80 (≥120K work space);
  `effective_trigger` reads per-model > top-level, project > user, capped by the model window.
- **Summary + verbatim, not digest alone.** Default mod mode `summary` keeps the engine summary and
  appends the user's own requests (incl. ones from before the previous compaction, pasted text,
  slash commands, repeats; long ones cut head 60 % / tail 40 % with a visible mark) + the task list.
  The digest (`compact: "digest"`) got the same fixes plus pending tool calls and agent report heads.
- **Instructions untouched.** Tool/prompt/listing cuts are opt-in (`lean`).
- **Right folder.** The desktop starts in `~/.claude/spares/spare-*`; skipped by ctx.py and the mod.
- Memory: `auto_capture` ≤180 chars, fewer false triggers, a changed value replaces the old line;
  Turkish İ folding; store names carry a path hash; broken settings files are never overwritten.

### 2.12 Cache-aware levers (0.9.0)
Plan quota is spent where the prompt cache is *written*: a cache read costs ~1/30. So the cheapest moment to
shrink the context is when the cache is cold anyway — the first request after a gap longer than the TTL
re-writes everything. Compaction cannot be started by a mod in desktop/SDK sessions, so the mod prunes
in `http.fetch` instead: on that cold request, old big tool outputs become a one-line stub (the
conversation itself, decisions and the newest 3 prompts stay whole). The chosen ids are stored and re-applied
to every later request, which keeps the prefix byte-identical, so pruning never causes a cache miss of its
own. The transcript is never changed; the model is told it can re-run a tool. `ctx.py cache_report` shows
what still re-wrote the cache (gap, prefix change, model switch) in the pane.

### 2.13 Context window per model, from the user's own usage (0.9.1)
Per call, a context C costs C·cr; one compaction costs a re-write R·cw and brings C back to P. With growth g
per call, the cost per call at a trigger P + E is cr·(P + E/2) + cw·R·g/E, lowest at E* = sqrt(2·(cw/cr)·R·g).
Measured (14 days): Opus g ≈ 2.0K, R ≈ 33K, P ≈ 74K → E* ≈ 64K. The curve is flat (±50 % ≈ +5 %), so the
tool takes 1.5·E* (fewer compactions, less digest loss): Opus ~184K, Sonnet ~200K, Fable ~224K, Haiku ~152K
(200K models stay native when that is cheaper). A 1M trigger would cost ~3.6× more per call on Opus.
`ctx.py tune` writes `modelSettings.<model>.autoCompactWindow` for every model the user ran, so whichever
model is picked in a chat gets its own value; global mode re-tunes once a day in the background.

## 3. What we deliberately do not do
- No per-prompt injection (`UserPromptSubmit`) → no per-turn tokens, no cache churn.
- No extra LLM calls, no MCP server, no database.
- No `Stop`-hook nagging (each forced continuation is a full extra call).

## 4. Risks
- Too-early compaction → many summarisation calls; tuned in the benchmark (PCT value).
- Weak models may skip `note`/`decide`; the deterministic log archive is the safety net.
- Native compaction re-attaches recently read files; the read guard keeps those small.

