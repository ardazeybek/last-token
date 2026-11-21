# system/ — what gets installed into your project

| file | purpose |
|---|---|
| `ctx.py` | the whole system (stdlib Python): install, agent commands (`rule`, `decide`, `note`, `recall`, `status`, `check`, `audit`, `savings`, `panel`, `tune`: per-model compaction window from your usage, `mod`, `compact-summary`) the hooks (`hook-precompact`, `hook-guard`: read guard, `hook-session`: global-mode memory injection) and `global on|off` |
| `autoinstall.sh` | optional user `SessionStart` hook (copied to `~/.claude/last-token/`): installs into code projects under `~/PROJECTS/` (git repo or a project file), refreshes their `.ctx/ctx.py` copy and (global mode) `~/.claude/last-token/ctx.py`, skips projects with `.no-last-token`, logs to `~/.claude/last-token/autoinstall.log` |
| `tests/test_ctx.py` | unit tests: digest content, task-list replay, Turkish decisions, savings, global mode (`python3 -m unittest discover system/tests`) |
| `tests/test_fixes.py` | regression tests, one per finding of docs/AUDIT-2026-11-20.md |
| `tests/test_cache.py` | prompt-cache report: re-write causes (gap, prefix, model), compactions after a cold gap |
| `mod/` | optional Claude Code mod (0.8.0): no-LLM digest compaction, Explore → Haiku, plan-quota pane; see `mod/README.md`. Installed per user with `ctx.py mod install` |
| `skill/SKILL.md` | optional skill with the detailed how-to (recall, notes, delegation); copied to `.claude/skills/last-token/` |

`ctx.py init <project>` creates `.ctx/` (copy of `ctx.py`, `RULES.md`, `DECISIONS.md`, `INDEX.md`,
`archive/`), inserts the protocol block into `CLAUDE.md` (between `last-token:begin/end`
markers, idempotent) and merges `autoCompactWindow`, `env.CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` and the
hooks into `.claude/settings.json` (a `.bak` copy is kept; your keys and hooks stay).

Trigger safety: `init` raises `--pct` so the trigger leaves `MIN_WORK` (38K) tokens above the fixed
base (measured from `~/.claude/projects/<slug>/*.jsonl`, `--base N`, or 75K fallback). The
`PreCompact` hook raises it again if a compaction follows the previous one within 6 calls.

Deterministic compaction (with the mod): `ctx.py compact-summary` archives the segment, copies
decision-like sentences of the user's prompts (English and Turkish) into `DECISIONS.md` (`auto_capture`) and prints the
digest the mod installs instead of a model summary: a mid-turn state line, the latest request, the
task list, the agent's last remarks, last images, older actions, then the newest steps verbatim.

Global mode: `ctx.py global on` (or `install.sh --global`) puts the hooks in
`~/.claude/settings.json` with `--global`; every folder without a project `.ctx/` gets a store in
`~/.claude/last-token/store/<slug>/.ctx`, and `hook-session` adds the protocol + memory to the
session's first message. `global off` removes the hooks, the env keys and the flag (store is kept).

`ctx.py savings` estimates the input tokens early compaction kept out of a session, against native
compaction alone (docs/DESIGN.md §2.9). `init --effort low` still exists but nothing passes it any more
(0.7.0: it made the model shallower in real work; init removes an old `effortLevel: low`).

Trigger (0.7.0): the user level holds it — `modelSettings.<1M model>.autoCompactWindow = 400000`
and pct 80 (`global on` / `trigger`); `init` writes a project window/pct only with `--window/--pct`
and removes the old 200K/54-58 % values that compacted Opus every ~100K.
`pause [session]` / `resume [session]` switch last-token off/on for one session (`~/.claude/last-token/paused.json`).
`init` refuses `$HOME`, `/` and desktop placeholder folders.
