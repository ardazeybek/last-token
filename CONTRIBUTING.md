# Contributing to Last Token

<p align="center"><a href="https://github.com/ardazeybek/last-token/issues/new/choose"><img src="assets/contrib-ways.png" width="100%" alt="You don't need to write code to help. Most valuable: share your quota numbers after a week of use. Report a bug: what you did, what you expected, what happened. Test your setup: macOS, WSL, VS Code, JetBrains. Fix a word in the docs." /></a></p>

With a bug report, paste the output of:

```bash
python3 ~/.claude/last-token/ctx.py doctor
```

<p align="center"><img src="assets/contrib-flow.png" width="100%" alt="From idea to merged in six steps: look through the issues first, open an issue for a bigger change, fork and create a branch, make your change, run the checks, open a pull request that says what changed and why." /></p>

The checks (step 5):

```bash
python3 -m unittest discover system/tests      # Python tests
claude plugin test system/mod                  # mod tests (needs Claude Code)
```

<p align="center"><img src="assets/contrib-rules.png" width="100%" alt="Four rules every change keeps: system/ctx.py stays one file, standard library only. Hooks never crash, they exit 0 on any error. The goal is plan quota, not tokens: saving tokens while adding cache writes is a regression. Every system change is measured with the benchmark and logged as a round." /></p>

<p align="center"><sub><a href="docs/RESEARCH.md">Why quota, not tokens</a> · <a href="bench/README.md">Run the benchmark</a> · <a href="docs/BENCHMARK.md">All rounds</a> · <a href="MAP.md">How the parts fit</a></sub></p>
