# bench/ — reproducible 3-way benchmark

Runs the same 32-turn development task (build `ledgerlite`, an order-pricing library, from a
long spec, a legacy module and a 3,000-line log) with headless Claude Code under three conditions:

| cond | meaning |
|---|---|
| a | no system: native defaults, one long session |
| b | no system, but start a **new chat** when context ≥ 60 % and re-explain the project (rules + "look around the repo") |
| c | last-token installed (`system/ctx.py init`) |
| d | ablation: only the two early-compaction settings c writes (`autoCompactWindow`, `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`), nothing else |
| e–j | experiments on top of c (rtk, clip [removed], batching rule, skill cap, no Agent, low effort); see docs/BENCHMARK.md |
| k | c + the mod (`--plugin-dir system/mod`) |
| l | k at a lower trigger |
| m | k + `effortLevel: low` (best measured) |

All conditions: same model, same tools (`Task,Bash,Read,Edit,Write,Skill`), `--autocompact 200000`
(200K reference window), `--setting-sources project` (your user settings/hooks are not loaded),
clean environment, auto-memory off. The run dir must have no `CLAUDE.md` / `.claude/CLAUDE.md` in any
parent directory (anything under `$HOME` picks up `~/.claude/CLAUDE.md`), so use `/tmp`; `run.py` refuses
otherwise. A turn that hits a network error or whose transcript stalls for 6 min is rolled back and retried
(up to 5×); on the usage limit the run stops and prints the `--steps N-32` to resume with.

| file | purpose |
|---|---|
| `fixture.py` | generates the deterministic starting project (spec, legacy code, logs, CSVs) |
| `steps.py` | the 32 user turns, the 10 house rules, recall ground truth, new-chat brief |
| `run.py` | runs one condition; saves `state.json` (per-step context, usage) + transcripts |
| `resume.sh` | wraps `run.py`: after a rate-limit/network stop waits 20 min and resumes with the printed `--steps` |
| `score.py` | scores a run (tokens, peak fill, rules R1–R10, recall, tests); `--table` prints markdown |
| `quota_probe.py` / `usage_window.py` | spend one token type / sum all sessions' usage in a time window: fit the plan quota formula (RESEARCH.md) |
| `probes/probe_compaction.sh` | reproduces the Claude Code behaviours the design relies on |

```bash
python3 bench/run.py --cond a --dir /tmp/bench/r1/a      # also b, c, d (can run in parallel)
python3 bench/score.py /tmp/bench/r1/a --out results/r1-a.json
python3 bench/score.py --table results/*.json
```

Metrics: total tokens = input + output + cache read + cache write from Claude Code's cumulative
per-session `modelUsage` (includes compaction calls and subagents), summed over sessions.
Peak fill = largest main-thread request (input + cache read + cache write) / 200K.
Rules: AST checks of the final code (R1–R8), changelog coverage (R9), vendor untouched (R10).
Recall: `ANSWERS.json` written at step 31 vs. ground truth (6 facts given only in chat, 2 client
overrides of the spec, 2 findings derived from files), plus whether decisions reached the code.
