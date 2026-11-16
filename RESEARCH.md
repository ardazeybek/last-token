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
