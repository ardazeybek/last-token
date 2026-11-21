# results/ — scored benchmark runs

One JSON per run, written by `bench/score.py <run> --out results/<round>-<cond>.json`.
`python3 bench/score.py --table results/*.json` prints the table used in docs/BENCHMARK.md.

| file | run |
|---|---|
| `r0-{a,b,c}.json` | round 0 baseline (c at pct 35) |
| `r1-{a,b,c}.json` | round 1: clarified recall question, repeat of a/b/c |
| `r2-c.json` | round 2: c at pct 25 (shipped default) |
| `r3-c.json` | round 3: c at pct 20 (rejected) |
| `r4-c.json` | round 4: c at pct 25 with a leaner index (rejected) |
| `r4-d.json` | round 4: ablation d, early compaction only |
