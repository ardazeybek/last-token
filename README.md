# context-economy

**Keep long Claude Code sessions small, cheap and on-rules — without starting a new chat.**

A tiny add-on for [Claude Code](https://code.claude.com) made of one stdlib Python script,
three hooks and a 15-line protocol block in `CLAUDE.md`. No server, no MCP, no vector DB,
no extra model calls.

- **Stable core** — your rules, the user's decisions and a one-line-per-entry archive index live
  in `CLAUDE.md` + `.ctx/*.md`. Claude Code re-reads them after every compaction, so rule #1
  from turn 1 is still there at turn 100.
- **Deliberate forgetting** — details go to `.ctx/archive/` (agent notes at subtask end + a
  condensed raw log written automatically right before each compaction). The context keeps
  only `id · title · path · one-line summary`; `ctx.py recall <word>` brings a detail back.
- **Early, steered compaction** — native auto-compaction is moved from ~97 % of a 1M window to
  ~25 % of a 200K reference window (≈ 50K tokens), and a `PreCompact` hook tells the summariser what to keep.
- **No bloat at the source** — a `PreToolUse` guard refuses whole-file reads of big files and
  points to `grep -n` + slices or a subagent.

**Measured** on a 32-turn coding task with Claude Haiku 5.5 (details in [BENCHMARK.md](BENCHMARK.md)):

| | no system | new chat at 60 % | **context-economy** |
|---|---|---|---|
| total tokens | 25.7M | 26.8M | **10.9M (−58 % / −59 %)** |
| peak context fill | 83 % | 73 % | **24 %** |
| house rules kept (late turns) | 99 % | 100 % | **99 %** |
| chat-only facts recalled at turn 31 | 100 % | 60 % | **100 %** |

## Install

Requirements: Claude Code ≥ 2.1.221 (for `autoCompactWindow`), `python3` ≥ 3.9.

```bash
git clone https://github.com/<you>/context-economy && ./context-economy/install.sh /path/to/your/project
```

Options: `--pct 25` (compaction trigger, % of window) and `--window 200000`.
Re-running is safe (idempotent). It creates/updates:

| path | what |
|---|---|
| `CLAUDE.md` | protocol block between `context-economy:begin/end` markers (your text is kept) |
| `.claude/settings.json` | `autoCompactWindow`, `env.CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`, `PreCompact` + `PreToolUse` hooks (merged, `.bak` kept) |
| `.claude/skills/context-economy/SKILL.md` | detailed how-to, loaded only when needed |
| `.ctx/` | `ctx.py`, `RULES.md`, `DECISIONS.md`, `INDEX.md`, `archive/` |

Commit `.ctx/` if you want the memory to travel with the repo; add `.ctx/archive/L*-log.md`
to `.gitignore` if conversation logs should stay local.

Uninstall: delete the block from `CLAUDE.md`, the two hooks + two keys from
`.claude/settings.json` (or restore `settings.json.bak`), and `.ctx/`.

## How it works

```
 user rule / decision ──► ctx.py rule|decide ──► .ctx/RULES.md, DECISIONS.md ─┐
 subtask done ─────────► ctx.py note ─────────► .ctx/archive/N00x + INDEX line ─┤  @imported by
 context ≥ 25 % ──► native auto-compaction                                        ├─ CLAUDE.md (core,
     └─ PreCompact hook ─► .ctx/archive/L00x-log.md + INDEX line                  │  ≤ 2.5K tokens)
                        └► summary rules (stdout → summariser)                    │
 after compaction: Claude Code re-reads CLAUDE.md + imports ◄────────────────────┘
 Read/cat of a big file ──► PreToolUse guard ──► denied: "grep -n + Read offset/limit, or a subagent"
```

Commands the agent (or you) can run:

| command | does |
|---|---|
| `python3 .ctx/ctx.py rule "<rule>"` | persist a house rule |
| `python3 .ctx/ctx.py decide "<key>: <value>"` | persist a decision (same key replaces) |
| `python3 .ctx/ctx.py note "<title>" "<summary>" <<'EOF' … EOF` | archive a subtask note |
| `python3 .ctx/ctx.py recall <words>` | grep the archive, print `path:line` hits |
| `python3 .ctx/ctx.py status` / `check` | current context fill / core size vs. budget |

Why this design (and the alternatives we rejected): [DESIGN.md](DESIGN.md).
What Claude Code already does and what other projects do: [RESEARCH.md](RESEARCH.md).

## Benchmark

Same 32 turns, same model and tools, 200K reference window, clean environment. Conditions:
**a** no system, **b** start a new chat with a project brief at 60 % fill (the usual manual
workaround), **c** context-economy, **d** ablation: only the early-compaction setting.

| run | total tokens | peak fill | compactions / new chats | rules (late) | recall | applied |
|---|---|---|---|---|---|---|
| a (r1) | 25,742,822 | 83 % | 4 / 0 | 100 % (99 %) | 100 % | 100 % |
| b (r1) | 26,809,008 | 73 % | 0 / 6 | 100 % (100 %) | 60 % | 43 % |
| c, pct 35 (r1) | 13,585,854 | 32 % | 16 / 0 | 100 % (99 %) | 100 % | 100 % |
| **c, pct 25 (r2, default)** | **10,894,437** | **24 %** | 27 / 0 | **100 % (99 %)** | **100 %** | **100 %** |
| d, pct 25, no system (r4) | 13,804,472 | 23 % | 45 / 0 | 96 % (87 %) | 100 % | 100 % |

What this says, honestly:

- Versus the manual new-chat workaround, c used **55–59 % fewer tokens** and did not lose the
  facts that were only ever said in the chat (b forgot 4 of 10 and applied only 3 of 7).
- Versus one long session, c used **58 % fewer tokens** at a third of the peak fill, with equal
  rule compliance and recall. a did not forget anything either on this task.
- Most of the saving (~80 %) comes from compacting early, which is two settings (run d).
  The rest of the system cuts another **21 %** of tokens and keeps late-turn rule compliance at
  99 % instead of 87 %.
- Four improvement rounds were run; only "compact at 25 % instead of 35 %" helped. 20 % and a
  leaner index did not and were reverted.

Full method, all rounds and raw numbers: [BENCHMARK.md](BENCHMARK.md). Reproduce:

```bash
python3 bench/run.py --cond c --pct 25 --dir /tmp/bench/c && python3 bench/score.py /tmp/bench/c
```

## Limitations

- Measured on **one model (Haiku 5.5), one synthetic task, one run per configuration**
  (noise ≈ ±5 %). Bigger models and real repositories may behave differently.
- On quality, context-economy **ties** a single long session here; its advantage is over
  new-chat workflows (recall) and over plain early compaction (rule compliance).
- After each compaction Claude Code re-attaches recently read files (~25K-token floor), so a
  trigger below ~25 % costs more than it saves.
- Agents under context-economy wrote fewer tests (all passing); test volume was not a target.
- Depends on Claude Code ≥ 2.1.221 settings and hooks (`autoCompactWindow`,
  `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`, `PreCompact`, `PreToolUse`); tested with 2.1.322.
- Not a security boundary: the read guard is a hint to the agent, not a sandbox.

## License

MIT — see [LICENSE](LICENSE).
