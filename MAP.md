# MAP — context-economy

## Folders
- `system/` — the installable product: `ctx.py` (single stdlib script) + `skill/SKILL.md`.
- `bench/` — reproducible benchmark: fixture generator, 32 steps, runner, scorer, probes.
- `results/` — scored benchmark runs (`<round>-<cond>.json`), referenced by BENCHMARK.md.
- root — `install.sh`, docs (README, RESEARCH, DESIGN, BENCHMARK), LICENSE.

## Main flow (installed project)
1. `install.sh <project>` → `ctx.py init`: creates `.ctx/`, protocol block in CLAUDE.md,
   merges `.claude/settings.json` (autoCompactWindow, PCT env, PreCompact + PreToolUse hooks).
2. During work the agent calls `ctx.py rule|decide|note|recall` (protocol in CLAUDE.md).
3. `PreToolUse(Read|Bash)` → `ctx.py hook-guard` denies whole reads of big files.
4. Context reaches PCT % of the window → native auto-compaction → `PreCompact` →
   `ctx.py hook-precompact` archives `.ctx/archive/L00n-log.md`, adds index line, prints summary rules.
5. After compaction Claude Code re-reads CLAUDE.md + `@.ctx/*.md` imports → fresh core.

## Benchmark flow
`bench/run.py --cond a|b|c|d` → fresh fixture (`fixture.py`) → 32 × `claude -p` (resume) →
`state.json` + transcripts → `bench/score.py` → `results/*.json` → `score.py --table`.

## Pitfalls
- `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` only lowers the trigger; it is a % of `autoCompactWindow`.
- 1M-window models compact at ~967K by default; init sets `autoCompactWindow` 200K.
- Native compaction re-attaches up to 5 recently read files → keep reads small (guard).
- `modelUsage` in `-p` json is cumulative per session (incl. compaction + subagents): take the last step.
- Benchmark runs use `--setting-sources project` + `env -i` so user hooks/CLAUDE.md don't leak in.
- Run dirs must be outside `$HOME`/the repo: Claude Code loads every ancestor `CLAUDE.md` and
  `.claude/CLAUDE.md` (incl. `~/.claude/CLAUDE.md`) despite `--setting-sources project`; run.py refuses.
- run.py retries a turn on network errors / a stalled transcript (6 min) after rolling it back.
