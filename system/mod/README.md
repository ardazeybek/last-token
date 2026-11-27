# system/mod — last-token mod (Claude Code mods API)

Optional add-on to `ctx.py`. Loaded by Claude Code as a plugin folder (`--plugin-dir`,
`CLAUDE_CODE_PLUGIN_DIRS`, or installed as a plugin). Does nothing in projects without `.ctx/ctx.py`.

| file | purpose |
|---|---|
| `.claude-plugin/plugin.json` | plugin manifest |
| `hooks/hooks.json` | points Claude Code at `register.tsx` |
| `hooks/register.tsx` | the levers below |
| `types/index.d.ts` | state contract: savings + quota figures, digests shown |
| `hooks/digest.test.tsx` | tests: digest row folded on every surface (button on desktop), savings pane, number format |
| `hooks/compact.test.tsx` | tests: summary/digest/native modes, spare folder, pane without a surface, python3 fallback, look-up agents → Haiku |
| `hooks/prune.test.tsx` | tests: cold-cache pruning (only after a cold gap, stable stubs, newest turns whole) |

Levers (each can be overridden per project in `.ctx/mod.json`):

Since 0.8.0 the instruction-cutting levers (shorter tool descriptions, dropped prompt sections,
cut listings, `lean`) are **removed**: they made the model worse, and under the plan-quota formula
they saved almost nothing (they only cut cache *reads*, ~1/30 of a cache write).

1. `tool.describe` — rarely used tools (`deferTools`) wait behind ToolSearch.
2. `tool.call` (Agent) — look-up subagents (`cheapAgents`: Explore, claude-code-guide, statusline-setup)
   run on `exploreModel` (default `"haiku"`, `""` = off) unless the call names a model. A subagent re-writes its ~36K base and all it reads
   into the cache; on an Opus session Haiku makes that ~5× cheaper. Other agent types are untouched.
3. `http.fetch` (engine model requests) — **cold-cache pruning** (`coldPrune`, default on). After a gap
   longer than the cache TTL (`coldSeconds` 3630) the next request re-writes the whole context into the
   cache anyway; on that request old tool outputs (≥ `pruneMinChars` 1500 chars, older than the newest
   `pruneKeepTurns` 3 prompts) become a one-line stub. The stubbed ids are kept in `$.store` per
   conversation and applied to every later request, so the cached prefix stays identical (no new miss).
   The transcript is untouched; the model is told it can re-run the tool. Covers resumed sessions too.
   Why not compact instead: `$.session.compact()` is refused in headless/SDK sessions (desktop) and a
   plugin's own call skips its own `session.compact` hook (so it would run the paid summarizer).
4. `session.compact` — `compact` mode:
   - `"digest"` (default since bench r18–19: −23 % plan quota, quality equal): the deterministic digest only, no model call
     (the summarizer call misses the prompt cache and rewrites the whole context: +57 % quota); falls back to native if ctx.py prints nothing.
   - `"summary"`: the engine's own summary, plus one block from
     `ctx.py compact-summary --extra` with the user's own requests verbatim (also the ones from before
     the previous compaction) and the task list. Nothing the model needs is lost to a short summary.
   - `"native"` (or `false`): Claude Code alone.
   ctx.py runs with `python3`, falling back to `/usr/bin/python3` etc. (some desktop sessions have no PATH).
5. `ui.render` (UserMessage) — the digest is a user-role message, so the transcript would show it
   as if the person typed it; it is drawn as one dim line instead. Terminal: ctrl+o shows it whole.
   Desktop/VS Code/mobile have no ctrl+o (they always pass `isExpanded`), so they get an
   "Show summary" button. The model still gets the full digest.
6. Quota pane (`panel`, `statusLine`) — a "Quota savings" pane opens with each session
   (`/lt-savings` reopens it): plan-quota points (1 point = 1 % of the 5-hour window) this session used
   (main + subagents) and early compaction saved, prompt-cache re-writes by cause (`ctx.py` `cache_report`)
   and the outputs cold pruning dropped, from `ctx.py panel` (`quota_report`). Haiku weights are
   measured; other models are scaled by API price (marked as estimate). Refreshed on `turn.complete`, no timer.
   Band above the prompt (all users): green "Last Token Active −N% quota" (`quota_pct`, vs. no system) and,
   when `new_chat_hint` says a fresh chat is cheaper, a red line telling the user to start a new chat for
   the next task. Status line: plain `Active −N%` (it cannot draw colours).
7. Where it acts — a project with `.ctx/`, or (global mode, `~/.claude/last-token/global.json`)
   any folder, using its store `~/.claude/last-token/store/<slug>/.ctx`. Elsewhere the mod stays
   silent, so the pane showing up means last-token works in this session. The desktop's placeholder
   folder (`~/.claude/spares/spare-*`) is skipped; config is cached per folder, so a later folder
   change is picked up. The pane opens on the first refresh even when `surfaces()` lists none
   (desktop never lists one); `session.attach` refreshes too. `"debug": true` logs to `~/.claude/last-token/mod.log`.
8. Paused sessions (`ctx.py pause [id]`): ctx.py exits 1, the mod falls back to native compaction.
