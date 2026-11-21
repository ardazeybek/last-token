# Contributing to Last Token

Thanks for helping. You do not need to write code to contribute. These are all useful:

- **Quota reports** — run Last Token for a week and share what the developer pane says (see *For tinkerers* in the README). Real numbers from other plans and models are the most valuable thing you can send.
- **Bug reports** — what you did, what you expected and what happened.
- **Testing** — macOS, WSL, VS Code, JetBrains and unusual setups are especially welcome.
- **Documentation** — fix unclear steps in the README or in a folder's `README.md`.

Bugs and ideas go to [GitHub Issues](https://github.com/ardazeybek/last-token/issues). When reporting a bug, include your operating system, how you run Claude Code (terminal, desktop app, IDE) and the output of `python3 ~/.claude/last-token/ctx.py doctor`.

## Workflow

1. Look through the existing issues first.
2. For a larger change, open an issue and describe your idea before you start.
3. Fork the repository and create a branch, for example `fix/guard-on-windows`.
4. Make your change.
5. Run the checks below.
6. Open a pull request that explains what changed and why.

## Rules of the code

- `system/ctx.py` stays **one file, standard library only**.
- Hooks must never crash a session: on any error they exit with 0.
- The goal is plan **quota**, not raw tokens. A change that saves tokens but adds cache writes is a regression (see [docs/RESEARCH.md](docs/RESEARCH.md)).
- A change to the system is measured with the benchmark ([bench/README.md](bench/README.md)) and the round is added to [docs/BENCHMARK.md](docs/BENCHMARK.md).

## Checks

```bash
python3 -m unittest discover system/tests      # Python tests
claude plugin test system/mod                  # mod tests (needs Claude Code)
```

## Map

[MAP.md](MAP.md) shows how the parts fit together; every folder has a `README.md` with one line per file.
