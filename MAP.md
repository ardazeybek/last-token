# MAP — last-token

## Folders
- `system/` — the installable product: `ctx.py` (single stdlib script) + `skill/SKILL.md` + `mod/` (Claude Code mod, TypeScript).
- `bench/` — reproducible benchmark: fixture generator, 32 steps, runner, scorer, probes.
- `results/` — scored benchmark runs (`<round>-<cond>.json`), referenced by BENCHMARK.md.
- `docs/` — RESEARCH (internals, quota formula), DESIGN (why), BENCHMARK (all rounds), ROADMAP (next levers), AUDIT.
- `assets/` — README images (logo, banner, charts) rendered from `assets/src/*.html`; style in DESIGN.md.
- `.github/` — CI (Python tests), issue and PR templates.
- root — `install.sh`, `get.sh`, `install-last-token.md` (the file users drop into Claude Code; also the release asset behind the README button), README, INSTALL (steps Claude follows), MAP, DESIGN, CONTRIBUTING, SECURITY, CODE_OF_CONDUCT, LICENSE.

## Main flow (installed project)
1. `install.sh <project>` → `ctx.py init`: creates `.ctx/`, protocol block in CLAUDE.md,
   merges `.claude/settings.json` (PreCompact + PreToolUse hooks; trigger only with --window/--pct).
2. During work the agent calls `ctx.py rule|decide|note|recall` (protocol in CLAUDE.md).
3. `PreToolUse(Read|Bash)` → `ctx.py hook-guard` denies whole reads of big files (Bash output clip was
   removed in 0.8: rounds 6-7 failed). `ctx.py audit` = fixed-base breakdown from the newest transcript + skill-listing levers.
4. Context reaches PCT % of the window → native auto-compaction → `PreCompact` →
   `ctx.py hook-precompact` archives `.ctx/archive/L00n-log.md`, adds index line, prints summary rules,
   raises pct in settings if compactions come back-to-back.
5. After compaction Claude Code re-reads CLAUDE.md + `@.ctx/*.md` imports → fresh core.
6. With the mod (`ctx.py mod install` → `CLAUDE_CODE_PLUGIN_DIRS` in ~/.claude/settings.json):
   `session.compact` (default `digest`: no LLM call, cheapest in plan quota) → `ctx.py compact-summary`
   digest is the only message. `summary` = engine summary + `--extra` block (costs +57 % quota).
   `tool.call(Agent)`: look-up subagents (`cheapAgents`) get `model: haiku` (`exploreModel`, "" = off). Lean base levers removed in 0.8.
   `http.fetch` (engine model requests): cold-cache pruning — first request after a gap > cache TTL stubs old
   big tool outputs; stub ids in `$.store` per conversation, re-applied to every request (stable cached prefix).
   `ui.render` folds only our digest rows (DIGEST_HEAD + `.ctx/archive/`). Paused session → native.
7. Savings: `turn.complete` → `ctx.py panel --session` → `savings()` (native-only counterfactual) +
   `quota_report()` (QUOTA_W × MODEL_MUL, main + subagents) → `$.state` → "Quota savings" pane + status line (`/lt-savings`).
8. `~/.claude/last-token/autoinstall.sh` (copy of `system/autoinstall.sh`, user SessionStart):
   installs into code projects under ~/PROJECTS, re-runs `init` when a `.ctx/ctx.py` is outdated (migrates
   settings), `.no-last-token` opts out.

9. Global mode (`install.sh --global` → `ctx.py global on`): flag `~/.claude/last-token/global.json`,
   user hooks with `--global` (`hook-session` injects protocol + memory at SessionStart, `hook-precompact`,
   `hook-guard`); memory per folder in `~/.claude/last-token/store/<slug>/.ctx` (`store_root`);
   a folder under a project `.ctx/` uses that one (`global_turn` skips; also /tmp, /var/tmp, scratch: `TEMP_DIRS`). `--global off` undoes.
10. Self-update: `hook-session` → `update_check()` (every 3 h, only with a `~/.claude/last-token/src` git clone,
   `update.json {"auto": false}` = off, `LT_NO_UPDATE` env skips) → background `ctx.py self-update`: fetch, pull,
   `install.sh --global`, `doctor`; any failure → one `claude -p` repair session per target commit (`repair.log`).
   Release asset `install-last-token.md` must be attached to every GitHub release (README button = releases/latest).

## Benchmark flow
`bench/run.py --cond a..m` (k = c+mod, m = c+mod+effort low; e–j, l experiments; `bench/resume.sh` waits out rate limits) → fresh fixture (`fixture.py`) → 32 × `claude -p` (resume) →
`state.json` + transcripts → `bench/score.py` → `results/*.json` → `score.py --table`.

## Pitfalls
- `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` only lowers the trigger; it is a % of `autoCompactWindow`.
- Goal = plan QUOTA, not raw tokens (real use, 7 days: cache read 42 %, cache write 45 %, output 13 %; subagents 20 %): cache write ≈ output ≈ 30× cache read (docs/RESEARCH.md). Score with
  `score.py` "quota %" column; test on Haiku low effort (`run.py --effort low`).
- 1M-window models compact at ~967K by default; the user level sets `modelSettings.<model>.autoCompactWindow`
  per model from the user's own usage (`ctx.py tune`, re-run daily by `hook-session` in the background):
  trigger = P + 1.5·sqrt(2·(cw/cr)·R·g) (P after-compaction size, R its re-write, g growth/call); Opus ≈ 184K. Never a top-level 200K in a project: it overrode Opus and compacted every ~100K.
- Never `effortLevel: low` by default: it made the model shallower (audit 2026-11-20).
- Desktop starts in `~/.claude/spares/spare-*`: ctx.py and the mod skip it. Some desktop sessions have
  no `python3` on PATH: the mod retries `/usr/bin/python3`.
- Native compaction re-attaches up to 5 recently read files → keep reads small (guard).
- `modelUsage` in `-p` json is cumulative per session (incl. compaction + subagents): take the last step.
- Benchmark runs use `--setting-sources project` + `env -i` so user hooks/CLAUDE.md don't leak in.
- Run dirs must be outside `$HOME`/the repo: Claude Code loads every ancestor `CLAUDE.md` and
  `.claude/CLAUDE.md` (incl. `~/.claude/CLAUDE.md`) despite `--setting-sources project`; run.py refuses.
- Trigger below the fixed base (desktop app ≈ 70K: system prompt + tools + skills) → compaction
  every turn → "Autocompact is thrashing". init floors pct (`safe_pct`), PreCompact hook raises it.
  Never `install.sh .` on this repo itself (that is how the thrash was found).
- Mod compaction must return only NEW messages: kept engine-handle messages stay chained to the
  old history and `--resume` reloads all of it (round 13 bug). Mod deferral needs ToolSearch offered.
- Use `/var/tmp/bench` for long runs: `/tmp` is wiped on reboot (lost a round that way).
- run.py retries a turn on network errors / a stalled transcript (6 min) after rolling it back.
- Desktop/VS Code pass `isExpanded: true` to every UserMessage (no ctrl+o): never use it alone to fold.
- `turn.step` is a streaming event: its hook must be `async function*` with `yield* next(e)`.
- `$.session.surfaces()` is `[]` on desktop too: open the pane anyway (`ui.open` waits for a surface).
- Desktop attaches its surface after `session.start`: the pane opens on the first `turn.complete` refresh that has one (once per session).
- Global mode: `.ctx` paths in the protocol are absolute (`ctx_ref`), the `LT` alias carries `--at <folder>`.
- A plugin cannot compact by itself in practice: `$.session.compact()` is refused in headless/SDK (desktop)
  sessions and inside `prompt.submit`; from a timer it skips the plugin's own `session.compact` hook
  (→ paid summarizer). Hence pruning in `http.fetch`. The engine has its own `idleCompaction` (54 min,
  only ≥100K conversation over the load size).
- Tests: `python3 -m unittest discover system/tests` and `claude plugin test system/mod`.
