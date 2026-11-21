@MAP.md

# Working on this repo
- `system/ctx.py` must stay stdlib-only and hooks must never crash (return 0 on error).
- After changing the system, re-run the benchmark (bench/README.md) and record the round in docs/BENCHMARK.md.
