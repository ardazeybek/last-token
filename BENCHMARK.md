# BENCHMARK — context-economy

All numbers below come from `results/*.json`, produced by `bench/score.py` from real headless
Claude Code runs (`bench/run.py`). Nothing is estimated or hand-edited.

## 1. Method

**Task.** One 32-turn development session: build `ledgerlite`, an order-pricing library, from a
long spec (`docs/SPEC.md`, 23 sections), a quirky legacy module (`vendor/legacy_pricing.py`), a
3,000-line application log and two CSV files. The fixture is generated deterministically by
`bench/fixture.py`. Turns (`bench/steps.py`) mix implementation, refactoring, log forensics,
a performance check and documentation, and are sent one by one with `claude -p --resume`.

Along the way the "client" gives information that exists **only in the chat**:

| kind | facts (turn introduced) |
|---|---|
| chat facts | contact person (1), dev-server port (3), vendor auth header (9), CLI name (10), release codename (15), report sort order (20) |
| client overrides of the spec | banker's rounding instead of HALF_UP (6), refund window 45 days instead of 30 (12) |
| derived from files | failing currency found in the log (7), legacy discount quirk for exactly 13 units (4) |

and 10 house rules (R1–R10) are given once, in turn 1.

**Conditions.**

| cond | setup |
|---|---|
| a | no system: native defaults, one long session, rules only in the first prompt |
| b | no system, but a **new chat** is started whenever the last request was ≥ 60 % of the window; the new chat gets a brief (rules + "look around the repo") — the common manual workaround |
| c | context-economy installed with `ctx.py init --pct N` |
| d | ablation (added in round 4): only the two settings c uses for early compaction (`autoCompactWindow` 200K + `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`), no hooks, no protocol, no guard |

**Constant across conditions.** Model `haiku` (Claude Haiku 5.5), tools
`Task,Bash,Read,Edit,Write,Skill`, `--autocompact 200000` (200K reference window),
`--setting-sources project` and a clean `env -i` environment (no user `CLAUDE.md`, hooks or
plugins leak in), auto-memory off, bypass-permissions mode, step timeout 25 min.

**Metrics** (`bench/score.py`).

- *Total tokens*: input + output + cache read + cache write, from Claude Code's cumulative
  `modelUsage` of each session (includes compaction calls and subagents), summed over sessions.
  This is the main efficiency metric: it is what every turn re-sends.
- *Cost $*: `total_cost_usd` as reported by Claude Code. Shown for reference only: it does not
  scale linearly with tokens (cache pricing and request size both matter), so conclusions are
  drawn from tokens.
- *Peak fill*: largest main-thread request (input + cache read + cache write) / 200K.
  *Step ≥ 60 %*: first turn whose request crossed 60 % of the window.
- *Rules*: AST checks of the final code for R1–R8, changelog coverage for R9, `vendor/` hash
  for R10. *Late rules*: R1–R8 measured only on modules written in turns 17–32, i.e. long after
  the rules were given.
- *Recall*: turn 31 asks for `ANSWERS.json` with the 10 facts above; compared with ground truth.
  *Applied*: whether 7 of those decisions actually reached the code / docs (rounding mode,
  45-day window, header name, port, CLI name, codename and contact in the release notes).
- *Tests*: the project's own unittest suite at the end (count and pass/fail).

## 2. Rounds

Rounds 1–4 are the improvement loop of the brief (at most 5 rounds, stop when the last two
bring no meaningful gain). Run-to-run noise, measured by repeating a/b/c with the same system
(r0 vs r1), is about ±5 % on total tokens, so "meaningful" below means > 7 %.

### All runs

| run | cond | total tokens | cost $ | peak fill | step ≥60% | mean ctx/call | calls | compactions | new chats | rules | late rules | recall | applied | tests |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| r0/a | a | 26,894,936 | 2.00 | 83% | 4 | 106,038 | 245 | 3 | 0 | 99% | 97% | 100% | 100% | 392 ok |
| r0/b | b | 24,234,779 | 1.44 | 69% | 4 | 80,074 | 297 | 0 | 7 | 100% | 100% | 50% | 43% | 489 ok |
| r0/c | c (pct 35) | 14,241,399 | 0.51 | 32% | — | 43,181 | 295 | 16 | 0 | 100% | 98% | 90% | 100% | 444 ok |
| r1/a | a | 25,742,822 | 2.18 | 83% | 5 | 99,244 | 248 | 4 | 0 | 100% | 99% | 100% | 100% | 412 ok |
| r1/b | b | 26,809,008 | 1.77 | 73% | 4 | 78,754 | 334 | 0 | 6 | 100% | 100% | 60% | 43% | 429 ok |
| r1/c | c (pct 35) | 13,585,854 | 0.51 | 32% | — | 43,687 | 279 | 16 | 0 | 100% | 99% | 100% | 100% | 398 ok |
| **r2/c** | **c (pct 25)** | **10,894,437** | **0.51** | **24%** | — | **33,664** | 275 | 27 | 0 | **100%** | **99%** | **100%** | **100%** | 333 ok |
| r3/c | c (pct 20) | 12,070,577 | 0.57 | 19% | — | 28,035 | 355 | 46 | 0 | 96% | 93% | 90% | 100% | 350 ok |
| r4/c | c (pct 25, lean index) | 11,333,273 | 0.45 | 23% | — | 31,969 | 312 | 22 | 0 | 99% | 94% | 100% | 100% | 335 ok |
| r4/d | d (pct 25, ablation) | 13,804,472 | 0.84 | 23% | — | 35,490 | 310 | 45 | 0 | 96% | 87% | 100% | 100% | 546 ok |

### Round 0 — baseline (a, b, c at pct 35)

c used 47 % fewer tokens than a and 41 % fewer than b, peaked at 32 % instead of 83 % / 69 %,
and never crossed 60 %. b (manual new chats) lost half of the chat-only facts: each new chat
starts from the repo, and facts that were never written to a file are gone (recall 50 %,
applied 43 %). c's one recall miss (`dozen_discount_pct`) was a scoring artefact: the agent had
the right value (1.3 %) in its archived note but read the question as "our project's default,
0". The question in `steps.py` was made explicit for all later rounds. `score.py` also had an R8
bug (calls to `_fail()` helpers counted as raises); fixed and r0 re-scored.

### Round 1 — clarified question, same system (repeat of a, b, c)

Purpose: confirm the r0 picture and measure noise. Totals moved by −4 % (a), +11 % (b) and
−5 % (c). c recall went to 100 %. b still lost the same chat-only facts (60 % / 43 %).

### Round 2 — compaction trigger 35 % → 25 %

After a compaction Claude Code restarts at ~22–30K tokens (12.6K fixed system prompt + tools +
core, the summary, and up to 5 recently read files that it re-attaches; this is not
configurable). At 35 % (70K) each segment ran from ~30K to 70K; at 25 % (50K) the average
request shrinks. Result: **−20 % tokens vs r1/c** (10.9M), peak 24 %, rules and recall
unchanged at 100 %. **Kept** (new default `DEFAULT_PCT = 25`).

### Round 3 — compaction trigger 25 % → 20 %

The gap between the post-compaction floor (~25K) and the trigger (40K) becomes too small:
46 compactions instead of 27, more calls (355), and each compaction is itself a full-context
call. **+11 % tokens vs r2**, rules 96 %, late rules 93 %, recall 90 % (missed the failing
currency found in the log). **Rejected.**

### Round 4 — leaner index (pct 25) + ablation d

Change: index summaries cut from 200 to 120 chars, at most 30 lines instead of 40, and no
index line for compaction logs that contain no user prompt. The core is only ~2.2K tokens, so
the expected saving was ~2–3 %. Result: **+4 % tokens vs r2** (inside noise), cost −12 %, late
rules 94 %. No meaningful gain → **rejected**; the shipped code is the r2 code.

Run alongside: **d**, the ablation that keeps only c's two early-compaction settings. It
answers "isn't this just a lower compaction threshold?":

| | c (r2) | d (r4) | c vs d |
|---|---|---|---|
| total tokens | 10.9M | 13.8M | −21 % |
| compactions | 27 | 45 | −40 % |
| late rules (R1–R8, turns 17–32) | 99 % | 87 % | +12 pt |
| all rules | 100 % | 96 % | +4 pt |
| recall / applied | 100 / 100 % | 100 / 100 % | equal |

So about 80 % of c's saving over a (a ≈ 26M → d 13.8M → c 10.9M) comes from compacting early,
which anyone can do with two settings. The rest of the system buys another ~21 % (fewer, cheaper compactions —
the read guard keeps big files out of context) and keeps rules from turn 1 enforced to the
end: without the stable core, native summaries gradually dropped R6 (no magic numbers, 50 %),
R8 (own exceptions only, 67 %) and R2 (docstrings, 80 %) in late modules. In this one run the
native summaries kept all 10 chat facts, so a recall advantage of c over d was **not** shown.

### Stop

Rounds 3 and 4 both failed to beat round 2 → the loop stopped after 4 rounds (limit 5).

### Run hygiene

The first attempts of r3/c, r4/c and r4/d were discarded and re-run from scratch: they were
started from a directory under `$HOME`, and Claude Code loaded `~/.claude/CLAUDE.md` as an
ancestor-directory memory file despite `--setting-sources project` (the agent started answering
in another language). `run.py` now refuses such directories. The same attempts also hit a
network outage; `run.py` now rolls back and retries a turn on network errors or a transcript
that stalls for 6 minutes. All runs in the table ran in `/tmp` with no leaked memory (checked
in the transcripts).

## 3. Success criteria

| criterion (from the brief) | result | verdict |
|---|---|---|
| c total tokens clearly below b | r2/c 10.9M vs b 24.2M / 26.8M (−55 % / −59 %); at pct 35: −41 % / −49 % | **met** |
| c peak fill clearly below a | 24 % vs 83 % (a crossed 60 % at turn 4–5; c never) | **met** |
| c rule compliance not worse than a | rules 100 % vs 99–100 %, late rules 99 % vs 97–99 % | **met** |
| c recall not worse than a | 100 % vs 100 % (r1, r2); 90 % in r0 (ambiguous question, see above) | **met** (no margin: a never forgot either) |

Honest reading:

- The token and fill gains are large and consistent across 4 c runs (−41 % to −59 % vs b).
- On quality c only **ties** a. a (one long session, native compaction at ~97 %) only compacted
  3–4 times on this task, so it had little chance to forget. The case where c matters is b
  (the usual manual workaround), which lost 40–50 % of chat-only facts, and d (early
  compaction without the core), which lost rule compliance in late modules.
- c's final test suites were the smallest (333–444 tests vs 392–546). All passed and R7 (a test
  file per module) held, but the agent wrote fewer tests per module when its context was
  small. Test count was not a criterion; we report it because it is a plausible side effect.

## 4. Limitations

- **One model, one task, few runs.** Haiku 5.5 only; one synthetic 32-turn task; 1 run per
  configuration (2 for a/b/c at pct 35). Run-to-run noise is ~±5 % on tokens (up to 11 % for b);
  differences below ~7 % should be read as ties. Sonnet / Opus and real repositories may differ.
- **200K reference window.** Runs used `--autocompact 200000`. With a 1M window and default
  settings, a would compact far later and use even more tokens; we did not measure that.
- **Cost.** `$` is what Claude Code reports; it is not proportional to tokens (cache writes,
  request size). We draw conclusions from tokens only.
- **Baselines a/b had rules only in the chat**, not in a `CLAUDE.md`. A user who already keeps
  rules in `CLAUDE.md` would get part of c's rule benefit for free; d (no rules file) does not
  isolate that.
- **Recall vs d not shown.** In one run, native early compaction kept all 10 facts too.
- **Post-compaction floor.** Claude Code re-attaches up to 5 recently read files after a
  compaction (~5K tokens here); this cannot be turned off, which is why a trigger below ~25 %
  backfires (round 3).
- **Headless mode.** All turns were `claude -p --resume`. Interactive sessions use the same
  compaction path, but this was not benchmarked.
- **Version dependence.** Relies on `autoCompactWindow` (Claude Code ≥ 2.1.221),
  `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` and the `PreCompact` / `PreToolUse` hooks; runs used
  Claude Code 2.1.322.

## 5. Reproduce

```bash
python3 bench/run.py --cond a --dir /tmp/bench/r1/a            # also b, c, d; can run in parallel
python3 bench/run.py --cond c --dir /tmp/bench/r2/c --pct 25
python3 bench/score.py /tmp/bench/r1/a --out results/r1-a.json
python3 bench/score.py --table results/*.json
```

A full run takes 35–45 minutes. If the account usage limit is hit, `run.py` stops cleanly and
prints the `--steps N-32` to resume with (the partial turn is rolled back first).
