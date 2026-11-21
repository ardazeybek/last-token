# RESEARCH — what Claude Code already does, what others built, where we fit

Researched on 2026-11-16 against Claude Code **2.1.322**. Every behaviour we rely on
is marked **[doc]** (official docs, URL given) or **[test]** (we reproduced it with
`claude -p` in a throw-away directory; scripts in `bench/probes/`).

## 1. Native features we build on (do not re-implement)

| Feature | Facts that matter for us | Source |
|---|---|---|
| `CLAUDE.md` | Loaded at session start. Project-root CLAUDE.md is **re-read from disk and re-injected after compaction**. Mid-session edits do **not** apply until `/clear`, `/compact` or restart (so editing it does not break the prompt cache). Docs recommend < 200 lines. `@path` imports, max depth 4. | [doc] code.claude.com/docs/en/memory, /context-window, /prompt-caching · [test] `@.ctx/INDEX.md` showed the updated file after an auto-compaction |
| Auto memory (`MEMORY.md`) | Per-project, first 200 lines / 25 KB loaded every session. Machine-local, not in the repo. | [doc] /memory |
| `.claude/rules/*.md` | Optional, can be path-scoped with `paths:` frontmatter. | [doc] /memory |
| Auto-compaction | Default: compacts near the model's limit (~967K on 1M-window models such as Haiku 5.5). `autoCompactWindow` setting / `--autocompact` / `CLAUDE_CODE_AUTO_COMPACT_WINDOW` set the window (100K–1M). `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` (1–100) lowers the trigger as a % of that window. | [doc] /model-config, /env-vars · [test] window 100K → trigger at ~92K; window 100K + PCT 50 (set via `settings.json` `env`) → trigger at ~45K |
| What survives compaction | System prompt, root CLAUDE.md, auto memory, invoked skill bodies (5K each / 25K total), up to 5 recently touched files, a preserved tail of recent messages, and the output of `SessionStart` hooks with matcher `compact`. Older hook context is only summarised. | [doc] /context-window · [test] post-compact context = 15K, then +17K as the last read file was re-attached |
| `/compact <focus>` | Manual compaction with focus instructions. | [doc] /context-window |
| Hooks | 33 events. Relevant: `SessionStart` (startup/resume/clear/compact/fork), `PreCompact` (manual/auto; **stdout with exit 0 becomes summarisation instructions**, exit 2 blocks), `PostCompact`, `PreToolUse` (`permissionDecision: deny` + reason), `UserPromptSubmit`, `Stop`. Input includes `transcript_path`; no context-usage field. No hook can *trigger* compaction. Hooks run in `-p` mode. | [doc] /hooks · [test] PreCompact instruction "summary MUST contain BANANA-SUMMARY" was obeyed; SessionStart `additionalContext` reached the model |
| Skills | `SKILL.md`; only name + description sit in context until invoked (progressive disclosure). Keep body < 500 lines. | [doc] /skills |
| Subagents | Own context window; only the final report returns to the parent. Built-in `Explore` is read-only. Subagent tokens still count toward usage/cost (`modelUsage` includes them). | [doc] /sub-agents, /agent-sdk/cost-tracking |
| Prompt caching | Automatic. Cached layers: system/tools → project context (CLAUDE.md…) → conversation. Broken by: model/effort change, MCP changes, `/compact`. **Not** broken by file edits, CLAUDE.md edits, skill invocation, subagents. Subscription main thread uses 1h TTL. | [doc] /prompt-caching · [test] `ephemeral_1h_input_tokens` in usage |
| Status line JSON | `context_window.used_percentage`, `current_usage` (input + cache read + cache write). | [doc] /statusline |
| Headless | `--output-format json` gives `usage`, `modelUsage` (per model, **cumulative for the whole session incl. compaction + subagents**, also with `--resume`), `contextWindow`, `total_cost_usd`. Transcript JSONL has per-call `usage` and `compact_boundary` records with `preTokens`/`postTokens`. | [doc] /headless · [test] |

Practical consequence: the context-window problem is **not** "Claude Code cannot compact" — it can, very well.
The problems are (1) it compacts *late* (near 100 % of a 1M window by default), so every
call before that re-reads a huge prefix (cost grows ~quadratically with session length) and
quality drops with context rot; (2) whatever the summary drops is gone; (3) big tool outputs
(whole-file reads, logs) inflate the context in a single step.

## 2. Similar open-source projects

| Project | Mechanism | Good | Weak | Published numbers |
|---|---|---|---|---|
| [claude-mem](https://github.com/thedotmack/claude-mem) (~117k★) | 9 hooks → local Bun server; an *observer LLM* turns tool events into observations; SQLite FTS5 + Chroma; MCP search tools | Small index injected at session start, details pulled on demand; shows token cost per layer | Heavy deps (Node, Bun, uv, Chroma, Agent SDK); extra LLM calls; telemetry on | None measured ("index line ≈ 1/10 of the record") |
| [context-mode](https://github.com/mksglu/context-mode) (~34k★) | `PreToolUse` refuses big Read/`cat`, routes to a sandbox; outputs to SQLite FTS5; ≤2 KB state block after compaction | Attacks the real source of bloat (tool output); fast hooks | Injects BM25-selected lines on **every prompt** (per-turn tokens); Node 24+; Elastic 2.0 licence | Author: 99 % of output bytes kept out of context (bytes, not tokens/cost) |
| [claude-context](https://github.com/zilliztech/claude-context) (~13k★) | MCP semantic code search (Milvus + embeddings API) | Just-in-time retrieval for big repos | External service + API key; search only, no memory | ~40 % fewer tokens at equal retrieval quality (claimed) |
| [SuperClaude](https://github.com/SuperClaude-Org/SuperClaude_Framework) (~24k★) | Big prompt/command framework, "token-efficiency mode" | Rich workflows | Pure instruction-following; its own token footprint undisclosed | "30–50 % fewer tokens" without method |
| [cc-sessions](https://github.com/GWUDCAP/cc-sessions) (~1.5k★) | Hooks lock edits until discussion; task files; subagents | Discipline, subagents keep main context clean | High friction; gives subagents whole transcript (expensive) | None |
| [Cline Memory Bank](https://docs.cline.bot/prompting/cline-memory-bank) | 6 markdown files the model must read at every task start | Zero deps, human-readable | Voluntary; reads *all* files every time; grows unbounded | None |
| [basic-memory](https://github.com/basicmachines-co/basic-memory) (~4.6k★) | MCP over markdown + SQLite/vector | Pull-based, editable | Python 3.12 + uv, AGPL | None in README |
| [Letta / letta-code](https://github.com/letta-ai/letta) | Agent edits its own memory blocks; git-backed memory FS | Principled memory model | Separate agent framework, not an add-on | LoCoMo 74 % (not a coding benchmark) |
| Handoff tools ([ctx](https://github.com/AgusRdz/ctx), claude-handoff, snapshot) | PreCompact writes state file, SessionStart prints it | Light, deterministic | Unmeasured; "SessionStart tells model to read X" is unreliable (claude-code issue #43733) | None |

Independent measurement (computingforgeeks, one task, Sonnet 4.5): realistic savings of
token tools were **20–43 %**; the 98–99 % headlines only count tool-output bytes.

Anthropic guidance ([Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents),
[context management](https://claude.com/blog/context-management)): context is a finite
attention budget; use **compaction**, **structured note-taking outside the window**,
**sub-agents that return 1–2K-token summaries**, and **just-in-time retrieval** via light
references (paths) instead of pre-loading. API context editing + memory tool: −84 % tokens
in a 100-turn search eval.

## 3. Gaps we target (our difference)

1. **Nobody measures total cost against the real alternative** — "start a new chat and
   re-explain". We ship a reproducible 3-way benchmark (no system / new-chat / ours) with
   token totals, peak fill, rule compliance and recall.
2. **Build on native compaction instead of replacing it.** We only (a) move the trigger
   earlier, (b) steer the summary through `PreCompact` stdout, (c) archive the raw
   conversation deterministically *before* each compaction so nothing is truly lost,
   (d) re-load a tiny index through the `CLAUDE.md` import that Claude Code already
   re-reads after compaction.
3. **Cache-friendly by construction:** zero per-turn injection. The core changes only at
   compaction boundaries, which rebuild the cache anyway.
4. **Stop bloat at the source** with a `PreToolUse` guard on whole-file reads of big files
   (idea shared with context-mode, but without a sandbox or per-prompt injection).
5. **No dependencies:** one Python 3 stdlib script + markdown files. No server, no MCP,
   no vector DB, no extra model calls.

## 4. Phase 2 candidates: the author's own token-saving stack (2026-11-17)

Each is a candidate benchmark condition; only what wins a measured round moves into the product.

| Candidate | What it does | Origin / licence | How it could join |
|---|---|---|---|
| [rtk](https://github.com/rtk-ai/rtk) 1.2.0 | `PreToolUse(Bash)` hook rewrites commands through a Rust proxy that condenses output (git, ls, tests, logs) | rtk-ai, **Apache-2.0** (compatible with MIT; keep NOTICE/attribution if code is copied) | Measured as condition e (r6): −1.2 % tokens (noise), late rules 96 % → not recommended by this benchmark |
| Global "token saving" rules (`~/.claude/CLAUDE.md`) | grep before reading big files, `| tail -n 40`, Explore subagent for broad search, batch independent commands, no full re-reads | author's own (can be MIT) | grep/slices/subagent already in protocol + guard; "batch + no re-read" as rule 6 lowered R6 compliance (r6) → dropped |
| `harita` skill | keeps `MAP.md` (≤150 lines) + per-folder README, `@MAP.md` in CLAUDE.md so a new chat needs only a few K tokens | author's own | Condition `g`: matters for new-chat steps (recall), fixture needs a MAP |
| `devir` skill | writes `DEVIR.md` handoff + short paste message for a new chat | author's own | Overlaps with PreCompact archive + INDEX; measure on the new-chat steps |
| `kontrol`, animation and design skills, impeccable, frontend-design, pyright-lsp | quality/design tools, not token savers | various | Out of scope (but each adds to the fixed base: see thrash pitfall) |

Fixed base matters: in the desktop app this author's setup costs ~70K tokens per request before
any conversation (skill listing ~12K, deferred tools, MCP instructions, agent listing). Trimming
that base is a separate, unmeasured lever.

## 5. Competitor study and Claude Code internals (2026-11-18, Claude Code 2.1.322)

Nine repositories were cloned and read (code, not only READMEs; none was run):

| Project | Licence | Mechanism (from the code) | Their own numbers | Taken? |
|---|---|---|---|---|
| [context-mode](https://github.com/mksglu/context-mode) | Elastic-2.0 | PreToolUse denies Read > 16 KB; PostToolUse `updatedToolOutput` swaps outputs > 4 KB for ≤96 B excerpts + FTS search; ≤2 KB state after compaction | sessions −19.6 % median on large tasks, +5.7 % on small | idea only (licence); our r6/r7 clip already showed output cuts cost rule compliance |
| [claude-code-token-saver](https://github.com/ww-w-ai/claude-code-token-saver) | Apache-2.0 | background `--fork-session` pre-writes a summary, installs it through the mods `session.compact` hook; `includeGitInstructions:false` | one anecdote ($326 → $180/day) | **yes: the mods API route** (our compaction is deterministic, no fork call) |
| [claude-mem](https://github.com/thedotmack/claude-mem) | Apache-2.0 | observer LLM, SQLite/Chroma; auto-clear mod at 33 % (save state, `/clear`, continue) | read gate −6 % … +20 % | idea: compaction without a summarizer |
| [claude-token-optimizer](https://github.com/nadimtuhin/claude-token-optimizer) | MIT | prune CLAUDE.md; hook templates read `CLAUDE_TOOL_NAME` (probably inert) | startup 11K → 800 (CLAUDE.md only) | no |
| [claude-token-efficient](https://github.com/drona23/claude-token-efficient) | MIT | 7-line terse CLAUDE.md | output −1 % (Haiku) … −18 % (Sonnet) | no (output ≈ 3 % of tokens) |
| [cc-plugin](https://github.com/TokenRollAI/cc-plugin) | MIT (lockfile) | doc IDs instead of bodies after compaction; prompt-budget CI | none | idea: per-hook token budget |
| [Save-The-Token](https://github.com/ch040602/Save-The-Token) | MIT | MCP schema cost estimate + allowlists | static estimate −69 % | idea: shrink tool schemas |
| [caveman](https://github.com/JuliusBrussee/caveman) | Apache-2.0 | terse-speak skill, input proxy, `ENABLE_TOOL_SEARCH` | own doc: −44 % output = +0.06 % total cost | idea: defer tools behind ToolSearch |
| [token-reducer](https://github.com/madhan230205/token-reducer) | MIT | BM25+vector retrieval skill | per query only | no |

Nobody measured whole sessions against a no-tool baseline with quality checks; the only
whole-session numbers (context-mode, caveman) are mixed.

**Claude Code internals found by reading the 2.1.322 binary and the mods type file:**

- The fixed base is the biggest cost: in the bench it is 36 % of all tokens; in the author's
  CLI setup the first request is 39K tokens, of which the Artifact tool definition alone is ~9.6K.
- Mods hooks (official API) can change it: `tool.describe` (description text, `isDeferred` puts a
  tool behind ToolSearch — works only when ToolSearch is offered), `prompt.compose` (system
  prompt sections by id: `lean_body`, `heron_brook`, `session_guidance`, …), `prompt.attachment`
  (skill/agent listings, account context), `session.compact` (answer the compaction yourself).
- Measured base with the mod: bench 11.2K → 4.3K (all levers) / 6.8K (shipped levers); the
  author's CLI setup 39.1K → 13.3K.
- `clear_tool_uses_20250919` context editing exists in the binary but only as a server-gated
  idle feature; `CLAUDE_CODE_SIMPLE_SYSTEM_PROMPT` is already the default for Haiku in `-p`.
- Hook-built compaction pitfall: messages returned *with* their engine handle stay chained to the
  old history and come back on `--resume`. Return only new messages.

## Plan quota formula (measured 2026-11-21, Pro plan, Haiku 5.5 low effort)
Method: `bench/quota_probe.py` spends one token type; `bench/usage_window.py` sums EVERY session's
usage in the window (the chatting session included); the plan's 5-hour % is read before/after.
| probe | Haiku tokens (main type) | 5-hour quota |
|---|---|---|
| cache write | 4.61M cw | +21 pts |
| cache read  | 3.83M cr (+0.51M cw) | +3 pts |
| output      | 0.44M out (+0.42M cw, + ~2.8M Opus cache read of the chat) | +5 pts |
Fit (points per 1M Haiku tokens, ±1 pt rounding): cache write ≈ 4.6, output ≈ 3–7, cache read ≈ 0.1–0.2.
So 100 % of the 5-hour window ≈ 22M Haiku cache-write tokens. **Quota is not raw tokens and not API cost:**
a cache write weighs about as much as an output token and ~30× a cache read (API price: 10×).
Consequences for last-token: saving cache *reads* is almost worthless; what costs is cache *writes*
(every compaction, every cache miss: idle > cache TTL, a changed system prompt/tool list) and output.
Re-scored with this weight, bench r17 Opus k (1.31M cw) cost MORE quota than a (0.35M cw).

## Where the quota really goes, and the cache (measured 2026-11-21, 7 days of the author's transcripts)
Quota-weighted (Haiku weights × API-price factor): main cache read 42 %, main cache write 26 %, subagents 24 %,
output 8 %. Main cache write split: new content written once 59 %, re-write after a gap > TTL 18 %,
after a compaction 12 %, session start 9 %, changed prefix 2 %.
- Subscriptions get a **1-hour** cache TTL (`ephemeral_1h_input_tokens` on every call); `-p` too.
- Sessions share ~38–47K of cached prefix (system prompt + tools) when another session ran within the hour;
  the rest of the desktop base (~25–30K: skills, CLAUDE.md, environment) is written per session.
- Claude Code has a built-in `idleCompaction` (setting, default on): a timer at 90 % of the TTL (54 min)
  compacts while the cache is still warm — only when the conversation is ≥100K over its load size
  (`CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS` cannot go below 100K), never in unattended (`-p`) runs.
- Mods: `$.session.compact()` is refused inside `prompt.submit` and in headless/SDK sessions; from a timer
  it skips all of the calling plugin's hooks (so our digest hook would not run). `http.fetch` sees every
  engine model request and may rewrite its JSON body — the lever used for cold-cache pruning.
- The batching rule ("batch independent calls") was tested in round 8 and rejected: no reliable saving.
