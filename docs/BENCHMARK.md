# BENCHMARK — last-token

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
| c | last-token installed with `ctx.py init --pct N` |
| d | ablation (added in round 4): only the two settings c uses for early compaction (`autoCompactWindow` 200K + `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`), no hooks, no protocol, no guard |
| e / f / g | c + rtk / c + output clip / c + batching rule (rounds 6–8, rejected) |
| h | c + skill descriptions capped at 100 chars (round 9) |
| i | h + Agent tool denied (round 9) |
| j | h + `effortLevel: low` (round 9) |
| k | c + the **mod** (`system/mod`): slim tool descriptions, trimmed system prompt sections and listings, deterministic compaction (round 10) |
| l | k at trigger 15 % (round 10) |
| m | k + `effortLevel: low` (round 11) |

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
| r5/c | c (pct 25, repeat of r2, 0.2.1) | 10,994,537 | 0.48 | 24% | — | 32,741 | 289 | 26 | 0 | 100% | 100% | 100% | 100% | 339 ok |
| r6/e | e (c + rtk 1.2.0, + protocol rule 6) | 10,813,160 | 0.45 | 24% | — | 32,912 | 279 | 24 | 0 | 95% | 96% | 100% | 100% | 347 ok |
| r6/f | f (c + output clip, + protocol rule 6) | 10,198,479 | 0.46 | 23% | — | 32,942 | 258 | 23 | 0 | 99% | 96% | 100% | 100% | 332 ok |
| r7/f1 | f (c + output clip) | 10,769,041 | 0.45 | 23% | — | 32,090 | 291 | 24 | 0 | 100% | 98% | 100% | 100% | 377 ok |
| r7/f2 | f (c + output clip) | 11,126,972 | 0.44 | 24% | — | 33,050 | 295 | 23 | 0 | 95% | 90% | 90% | 86% | 354 ok |
| r8/g1 | g (c + batching rule 6) | 10,211,422 | 0.45 | 23% | — | 33,174 | 259 | 24 | 0 | 98% | 98% | 100% | 100% | 320 ok |
| r8/g2 | g (c + batching rule 6) | 12,071,047 | 0.49 | 36% | — | 36,366 | 291 | 23 | 0 | 99% | 98% | 100% | 100% | 366 ok |
| **s1/a** | **a, Sonnet 5.5** | 10,511,983 | 3.55 | 81% | 18 | 78,929 | 129 | 1 | 0 | 100% | 100% | 100% | 100% | 224 ok |
| **s1/c** | **c, Sonnet 5.5** | **5,092,327** | **3.09** | **23%** | — | 29,476 | 156 | 8 | 0 | 100% | 98% | 100% | 100% | 190 ok |
| run | cond | total tokens | cost $ | peak fill | step ≥60% | mean ctx/call | calls | compactions | new chats | rules | late rules | recall | applied | tests |
| r9/c | c | 11,330,257 | 0.4436 | 24% | — | 33,007 | 291 | 21 | 0 | 96% | 93% | 100% | 100% | 341 ok |
| r9/h | h | 9,401,541 | 0.4019 | 24% | — | 31,041 | 263 | 20 | 0 | 100% | 100% | 100% | 100% | 324 ok |
| r9/i | i | 11,617,255 | 0.4746 | 23% | — | 31,062 | 329 | 23 | 0 | 95% | 91% | 100% | 100% | 370 ok |
| r9/j | j | 7,494,897 | 0.2836 | 22% | — | 29,917 | 223 | 13 | 0 | 98% | 92% | 100% | 100% | 279 ok |
| r10/k | k | 9,752,118 | 0.5029 | 31% | — | 27,362 | 321 | 22 | 0 | 100% | 100% | 100% | 100% | 403 ok |
| r10/l | l | 9,473,941 | 0.8439 | 69% | 10 | 26,870 | 325 | 26 | 0 | 100% | 99% | 100% | 100% | 367 ok |
| r11/j | j | 7,893,334 | 0.268 | 23% | — | 30,929 | 231 | 12 | 0 | 92% | 89% | 100% | 100% | 244 FAIL |
| r11/k | k | 9,274,943 | 0.4773 | 42% | — | 27,611 | 321 | 22 | 0 | 96% | 92% | 100% | 100% | 430 ok |
| r11/m | m | 6,510,808 | 0.2711 | 30% | — | 26,920 | 227 | 13 | 0 | 100% | 100% | 100% | 100% | 259 ok |
| r12/a | a | 21,107,667 | 1.7016 | 83% | 7 | 93,270 | 217 | 3 | 0 | 98% | 94% | 100% | 100% | 429 ok |
| r12/m2 | m | 6,754,614 | 0.4294 | 52% | — | 26,550 | 237 | 17 | 0 | 98% | 95% | 100% | 100% | 309 ok |
| r12/m3 | m | 6,442,259 | 0.3178 | 42% | — | 28,293 | 220 | 15 | 0 | 99% | 97% | 90% | 86% | 271 ok |
| r13/m4 | m | 6,122,696 | 0.2603 | 34% | — | 27,444 | 216 | 12 | 0 | 100% | 100% | 100% | 100% | 252 ok |
| r13/m5 | m | 6,105,434 | 0.29 | 36% | — | 26,720 | 218 | 13 | 0 | 99% | 98% | 100% | 100% | 259 ok |
| r14/k3 | k | 10,687,057 | 0.4514 | 24% | — | 28,431 | 361 | 20 | 0 | 99% | 99% | 100% | 100% | 381 ok |
| r14/m6 | m | 6,818,413 | 0.2665 | 24% | — | 27,817 | 237 | 11 | 0 | 99% | 96% | 100% | 100% | 284 ok |
| r14/m7 | m | 6,666,471 | 0.2724 | 23% | — | 29,065 | 215 | 11 | 0 | 99% | 95% | 100% | 100% | 265 ok |
| r15/m1 | m | 6,891,585 | 0.2718 | 22% | — | 28,756 | 232 | 12 | 0 | 99% | 97% | 100% | 100% | 281 ok |
| r15/m2 | m | 6,253,276 | 0.2614 | 24% | — | 28,167 | 214 | 11 | 0 | 100% | 100% | 100% | 100% | 309 ok |

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

### Round 5 — repeat of r2 (0.2.1: trigger floor + thrash guard)

Same settings as r2 (the floor does not change pct 25 at a 12K base). Total tokens 10.99M vs
10.89M (+0.9 %), all rules/recall 100 %: the r2 result reproduces, so run-to-run noise on this
benchmark is ~1 % for c — smaller than the ±5 % assumed before.

### Round 6 — output reduction: rtk (e) vs built-in clip (f)

Both add protocol rule 6 ("batch independent commands; do not re-read a file you just wrote").
vs. the c mean of r2/r5 (10.94M):

| | e (rtk) | f (clip) |
|---|---|---|
| total tokens | −1.2 % (≈ noise) | **−6.8 %** |
| late rules | 96 % (R6 83 %, R8 87 %) | 96 % (R6 67 %) |
| recall / applied | 100 / 100 % | 100 / 100 % |

f clipped 6 outputs. Both lost R6 (magic numbers → constants.py), which c never lost; the
shared change is rule 6, so round 7 repeats f twice without it.

### Round 7 — clip without rule 6, two repeats

Tokens −1.6 % and +1.7 % vs the c mean (noise); late R6 83 % and 50 %, and f2 also lost recall
(90 %) and applied facts (86 %). Over three runs the clip never matched c on rules, and its
token effect is within noise → **rejected**: the clip stays in ctx.py as opt-in (`CTX_CLIP=on`),
rule 6 is dropped, rtk is not recommended on the strength of this benchmark. The product stays
at the r2/r5 configuration (c). A likely reason: clipped test/linter output hides the
details the agent uses to fix rule violations, so saving output tokens costs quality.

### Round 8 — batching rule alone (g), two repeats

Mean 11.14M tokens vs c 10.94M (+1.8 %, g2 alone +10 %), late R6 83 % in both → **rejected**.
r6/f's low total was not caused by rule 6. Over rounds 6–8, every addition that changes how the
agent works (condensed output, batching instruction) cost R6 compliance and saved nothing reliable.

### Sonnet 5.5 — a vs c (one run each)

| | a (no system) | c (last-token) | change |
|---|---|---|---|
| total tokens | 10.51M | 5.09M | **−52 %** |
| cost (list price, Claude Code's own figure) | $3.55 | $3.09 | **−13 %** |
| peak context fill | 81 % | 23 % | −58 pts |
| rules / late rules | 100 / 100 % | 100 / 98 % (R6 83 %) | −2 pts late |
| recall / applied | 100 / 100 % | 100 / 100 % | equal |

Why the cost falls far less than the tokens: on Sonnet most of a's cost is cheap cache reads,
while each of c's 8 compactions writes a fresh cache prefix (cache writes 323K vs 220K) and runs a
summary call. On Haiku the same mechanism costs less relative to the saved reads (−76 % cost).
So for Sonnet the product mainly buys **context headroom** (23 % vs 81 % fill), not a lower bill.

### Round 9 — where the tokens go, and a leaner fixed base (h, i, j + control c)

Transcript analysis of r8/g1 (8.9M main-thread tokens): **the fixed base (system prompt + tools +
listings + core, 12.4K) is 36 % of all tokens**, because every one of ~280 calls re-sends it; tool
outputs were only ~1 %. After each compaction the context restarted at ~25K (base + native summary
+ preserved tail + ~3 re-attached files ≈ 3.5K), and each of the ~24 compactions was itself a
~46K-token summarizer call (~13 % of the total). Probes with `claude -p` measured what each lever
removes from the base (11.2K in the bench environment): skill descriptions capped −2.0K, Agent tool
denied −2.0K, Skill tool denied −3.1K.

Same-day control c: 11.33M (r2/r5: 10.89M / 10.99M). Against it: h −17 % (quality 100 %),
i +3 % (more calls without subagents → rejected), j −34 % but late rules 92 %.

### Round 10 — the mod (k) and a lower trigger (l)

Competitor study (9 repos, see RESEARCH.md §5) pointed to Claude Code's mods API. The mod
(`system/mod/hooks/register.tsx`) uses four official hooks: `tool.describe` (short descriptions for
Bash/Read/Agent/Skill; big rarely used tools behind ToolSearch), `prompt.compose` (drops 5
system-prompt sections that do not help coding; safety, privacy and pronoun sections kept),
`prompt.attachment` (drops account/attribution context, cuts listing lines to 90 chars) and
`session.compact` (deterministic compaction: `ctx.py compact-summary` archives the segment and
returns a digest of verbatim user prompts, changed files, recent tool actions — **no summarizer
call**, 0.2 s instead of ~5 s). Bench base 12.3K → 6.8K; post-compaction floor ~25K → ~8.5K.

k: 9.75M (−14 % vs control), mean context per call 27.4K vs 33.0K, but 321 calls vs 291: the
slim Bash text had lost "cd persists", and 154 commands started with `cd <dir> &&`. l (trigger
15 %): 9.47M with a 69 % peak and doubled cache writes → not better than k, rejected.

### Round 11 — fixed tool texts; mod + low effort (m); repeats

k2 9.27M (−18 %), quality 96/92 %. **m (k + effortLevel low) 6.51M (−43 % vs control), rules,
recall, tests all 100 %**, 227 calls. j2 (low effort without the mod) 7.89M but rules 92 %, late
R6 33 % and a failing test suite — low effort alone is not safe on this task.

### Round 12–13 — repeats of m, fresh baseline a, automatic decision capture

m2 6.75M, m3 6.44M; m3 missed one chat-only fact (CLI name `llite`: the agent never ran
`ctx.py decide`, and the deterministic digest only carries the current segment's prompts). Fix:
at every compaction `ctx.py` copies decision-like sentences of the segment's user prompts
("we agreed", "instead of", "client decision", port/header/codename …) into `.ctx/DECISIONS.md`
unless already covered (`auto_capture`). m4 6.12M, m5 6.11M, both recall/applied 100 %.
Fresh a: 21.1M (r0/r1: 26.9M / 25.7M).

Means (Haiku 5.5):

| group | runs | total tokens | cost $ | calls | mean ctx/call | rules | late rules | recall | applied |
|---|---|---|---|---|---|---|---|---|---|
| a (no system) | 3 | 24.58M | 1.96 | 237 | 99.5K | 99.0 % | 96.8 % | 100 % | 100 % |
| c (0.3.0) | 3 | 11.07M (−55 %) | 0.48 | 285 | 33.1K | 98.5 % | 97.0 % | 100 % | 100 % |
| k (mod) | 2 | 9.51M (−61 %) | 0.49 | 321 | 27.5K | 98.2 % | 95.8 % | 100 % | 100 % |
| m (mod + low effort) | 5 | **6.39M (−74 %)** | **0.31 (−84 %)** | 224 | 27.2K | 99.2 % | 98.0 % | 98 % | 97 % |

Found afterwards: in m runs the first call of some steps jumped back to 50–100K (peak fill up to
52 %). The mod had kept the newest messages verbatim after its digest; those rows stayed chained
to the old history, and `claude -p --resume` (each bench step) re-loaded that whole chain. Fix in
round 14: the digest carries the newest steps as text and the mod keeps no old message.

### Round 14 — resume fix (0.4.0 as shipped)

m6 6.82M, m7 6.67M with peak fill back at 23–24 % (no more jumps after `--resume`), rules 99 %,
recall/applied 100 %. k3 (mod, normal effort) 10.69M with 361 calls: with the mod alone the agent
makes more calls, so k's gain over c is small and noisy (−11 % over 3 runs); low effort is what
cuts the call count, and with the mod's lean context it did not cost quality in 7 runs
(without the mod it did, r11/j).

**Final means, Haiku 5.5:**

| setup | runs | total tokens | vs a | cost $ | calls | peak fill | rules / late | recall / applied |
|---|---|---|---|---|---|---|---|---|
| a — no system | 3 | 24.58M | — | 1.96 | 237 | 83 % | 99.0 / 96.8 % | 100 / 100 % |
| c — 0.3.0 | 3 | 11.07M | −55 % | 0.48 | 285 | 24 % | 98.5 / 97.0 % | 100 / 100 % |
| k — 0.4.0 + mod | 3 | 9.90M | −60 % | 0.48 | 334 | ≤41 % | 98.6 / 96.9 % | 100 / 100 % |
| **m — 0.4.0 + mod + low effort (`--max`)** | 7 | **6.49M** | **−74 %** | **0.30 (−85 %)** | 224 | ≤24 % (r14) | 99.1 / 97.2 % | 99 / 98 % |

Real-setup check (not a benchmark): the author's CLI first request 39.1K tokens → 13.3K with the
mod (Artifact, ScheduleWakeup, ReportFindings, ListAgents deferred behind ToolSearch; a deferred
tool still loaded on request).

### Round 15 — 0.5.0 digest (task list, mid-turn state, findings, images) + savings pane
Two repeats of m with the new digest and the mod's pane/status hooks (`/var/tmp/bench/r15`).
Tokens: 6.89M and 6.25M (mean 6.57M) vs r14 6.74M and r11–14 mean 6.49M → within noise; the
richer digest costs nothing measurable. Quality: rules 99–100 %, late rules 97 / 100 % (r14: 96 / 95 %),
recall and applied 100 %. `ctx.py savings` on these transcripts says 71 % of input kept out
(16.1M / 14.9M saved); measured against condition a it is −74 %, so the estimate is slightly conservative.
Kept.

### Round 16–17 — 0.7.0 (quality-first) on Haiku, and Opus 5.5 low effort (a vs k)
`bench/run.py --effort` added (same effort for every condition). Results: `results/r16-k.json`,
`results/r17-opus-{a,k}.json`.
- r16 Haiku k: 11.8M tokens, rules 99 %, late rules 98 %, recall/applied 100 % (r14 k3: 10.7M, 99/99 %).
- r17 Opus 5.5 low effort:

| | a (no system) | k (0.7.0 + mod) |
|---|---|---|
| total tokens | 12.59M | **8.29M (−34 %)** |
| cost (API list price) | **$8.72** | $14.71 (+69 %) |
| cache write | 0.35M | 1.31M |
| compactions | 1 | 12 |
| rules / late rules | 100 / 100 % | 99 / 96 % (R6 "no magic numbers": 0.91 / 0.67) |
| recall / applied / tests | 100 / 100 % / ok | 100 / 100 % / ok |

Findings: the bench trigger (window 200K × pct 35 ≈ 70K) compacts Opus every ~2-3 steps; each
compaction rewrites the prompt cache, and cache writes cost 12.5× cache reads, so fewer tokens
became a higher bill. One style rule slipped after compactions. The installed 0.7.0 trigger is
much later (400K × 80 % = 320K), so this round over-states the compaction cost; it still shows that
on Opus, frequent compaction is not free. Next: rerun k on Opus with the real trigger.

### Round 18–19 — plan quota as the metric (Haiku, `--effort low` for every condition)
Quota % = estimated share of the Pro 5-hour window (`score.py`, weights in RESEARCH.md).
| run | quota % | rules | late rules | recall | compactions |
|---|---|---|---|---|---|
| r18 a (no system) | 4.99 | 98 % | 94 % | 100 % | 2 |
| r18 k summary (0.7.0) | 7.84 | 97 % | 94 % | 100 % | 11 |
| r18 k digest | 4.11 | 94 % | 99 % | 100 % | 6 |
| r18 k digest + lean | 3.96 | 96 % | 89 % | 100 % | 6 |
| r19 k digest + rule fix (×2) | 3.99 / 3.64 | 99 / 99 % | 97 / 94 % | 100 % | 7 / 6 |
| r19 k digest, pct 20 | 4.73 | 100 % | 98 % | 100 % | 21 |
The summarizer call misses the cache and rewrites the context (+57 %); the digest writes a few K
(−23 % vs a, quality equal). r18 digest lost R9: `rule` cut a 10-rule list at 300 chars → fixed
(numbered lists split into one rule each). Earlier trigger = more compactions = more cache writes.
Shipped: digest default, 1M-model trigger = base + 100K. Results `results/r18-*.json`, `results/r19-*.json`.

### 0.8.0 cleanup (2026-11-21) — no new round
Removed Bash output clip and the lean base levers (both off by default, both failed), added Explore → Haiku
(mod `tool.call`) and the quota pane. Nothing here changes what a bench run does (clip/lean were off,
the bench model is already Haiku and spawns no Explore agents), so no round was spent; the r19 figures stand.
Real-use data (transcripts, 7 days, quota-weighted): main cache read 36 %, main cache write 34 %,
subagents 20 %, output 13 %; one Opus audit session spent 46 % of its quota in 19 subagents.

### Round 20 — 0.9.0 cache-aware levers (Haiku, `--effort low`)
| run | quota % | rules | late rules | recall | tests |
|---|---|---|---|---|---|
| r18 a (no system) | 4.99 | 98 % | 94 % | 100 % | ok |
| r20 k (0.9.0 as shipped) | 3.60 | 98 % | 95 % | 100 % | ok |
| r20 p (stress: cold pruning on EVERY step, `coldSeconds` 1) | 6.91 | 99 % | 98 % | 100 % | 1 error |
k: −28 % quota vs a, quality equal (pruning never fires in a bench: steps are minutes apart, cache warm).
p is a quality stress test, not a quota test: pruning while the cache is warm moves the prefix and re-writes
the cache every step (+92 %), which is exactly why the shipped lever prunes only after a gap > TTL.
Quality held under that worst case (rules 99 %, recall 100 %); one integration test error (r19 d1 had one too).
Real cold-gap check (`/var/tmp/lt-idle`, Haiku): context 121K → 19K on the first request after the gap,
the model re-read the file it needed, kept the code word; the next requests hit the cache (35 tokens written).
Results `results/r20-*.json`.

### 0.9.1 per-model window (2026-11-21) — no new round
`ctx.py tune` sets each model's trigger from the user's transcripts (DESIGN 2.13). It changes nothing a bench
run does (run.py passes `--autocompact` itself), and on Opus it lands at ~184K, the base+100K that r19 chose,
so no round was spent. Subagent audit (7 days): 90 % of subagent quota = 62 general-purpose Opus agents doing
real work (bug hunts, fixes, app builds); moving them to a cheaper model would cost intelligence, so it stays off.

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
