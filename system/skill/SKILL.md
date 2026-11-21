---
name: last-token
description: Recall archived project details, write subtask notes, or check context/core size. Use when you need an earlier decision, finding or value that is no longer visible in context, when a subtask is finished, or when the user asks about context usage.
---

# Last Token — details

The always-on part of the protocol is the block in `CLAUDE.md`. This skill holds the how-to.

## Recall a forgotten detail
1. Look at `### Decisions` and `### Archive index` in CLAUDE.md (already in context).
2. `python3 .ctx/ctx.py recall <keyword> [keyword…]` → prints `path:line: text` hits.
3. Read only around the hit: `Read <path>` with `offset=<line-20>` `limit=60`.
4. Use the value. Do not paste the archived text back into the chat; write results to files.

## Write a note when a subtask is done
```bash
python3 .ctx/ctx.py note "Pricing port" "bulk tiers 50/250/1000; HALF_EVEN rounding" <<'EOF'
Decisions: ...
Files: src/pricing.py, tests/test_pricing.py
Open: currency minor units for JPY not handled yet
EOF
```
Keep the one-line summary dense with the values someone would grep for.

## Decisions and rules
- `python3 .ctx/ctx.py decide "refund window: 45 days (overrides spec 30)"` — same key replaces the old value.
- `python3 .ctx/ctx.py rule "Every function has a docstring"`.

## Heavy reading
Delegate to a subagent (Task tool, `subagent_type: Explore`) when a question needs more than two
files, more than ~400 lines, or long logs/test output. Ask for at most 15 lines with
`file:line` references. Whole-file reads of big files are blocked by the guard hook; use
`grep -n` + `Read offset/limit` instead.

## Clipped command output (only if CTX_CLIP=on)
Long Bash output is then saved whole to `.ctx/out/<time>.log`; you see the first 25 lines, the
error/warn lines from the middle and the last 35. Need more? `grep -n` the saved log — do not re-run.

## Fixed base
`python3 .ctx/ctx.py audit` — what every request carries before the conversation (system prompt,
tool schemas, skill listing, memory files) and the levers to shrink it.

## Status
`python3 .ctx/ctx.py status` — current context tokens (newest transcript) and core size.
`python3 .ctx/ctx.py check` — core size vs. the 2,500-token budget.
