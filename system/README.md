# system/ — what gets installed into your project

| file | purpose |
|---|---|
| `ctx.py` | the whole system (stdlib Python): install, agent commands (`rule`, `decide`, `note`, `recall`, `status`, `check`) and the two hooks (`hook-precompact`, `hook-guard`) |
| `skill/SKILL.md` | optional skill with the detailed how-to (recall, notes, delegation); copied to `.claude/skills/context-economy/` |

`ctx.py init <project>` creates `.ctx/` (copy of `ctx.py`, `RULES.md`, `DECISIONS.md`, `INDEX.md`,
`archive/`), inserts the protocol block into `CLAUDE.md` (between `context-economy:begin/end`
markers, idempotent) and merges `autoCompactWindow`, `env.CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` and the
hooks into `.claude/settings.json` (a `.bak` copy is kept; your keys and hooks stay).
