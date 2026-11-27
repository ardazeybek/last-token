<div align="center">
  <img src="assets/logo.svg" alt="Last Token logo" width="104" />
  <h1>Last Token</h1>
  <p><strong>Make your Claude Code plan last longer: −68 % plan quota on the same work.</strong></p>
  <p>A drop-in add-on for Claude Code that spends your quota where it is cheap. Same work, same quality, nothing forgotten.</p>

  <p>
    <img src="https://img.shields.io/badge/Claude%20Code-terminal%20%7C%20desktop%20%7C%20IDE-D97757" alt="Works in the Claude Code terminal, desktop app and IDEs" />
    <img src="https://img.shields.io/badge/plans-Pro%20%7C%20Max-141413" alt="For Claude Pro and Max plans" />
    <img src="https://img.shields.io/badge/python-3.9%2B%20%C2%B7%20stdlib%20only-3D3D3A" alt="Python 3.9+, standard library only" />
  </p>
  <p>
    <a href="https://github.com/ardazeybek/last-token/actions/workflows/ci.yml"><img src="https://github.com/ardazeybek/last-token/actions/workflows/ci.yml/badge.svg?branch=master" alt="Test status" /></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-B9B6AB" alt="MIT license" /></a>
    <img src="https://img.shields.io/badge/telemetry-none-788C5D" alt="No telemetry" />
    <img src="https://img.shields.io/badge/price-free-E8E6DC" alt="Free" />
  </p>

  <p>
    <a href="https://github.com/ardazeybek/last-token/releases/latest/download/install-last-token.md"><img src="assets/install-button.svg" alt="Download the installer" height="56" /></a>
  </p>

  <p>
    <b>① Click the button</b> &nbsp;→&nbsp; <b>② Drag the downloaded file into Claude Code, press Enter</b> &nbsp;→&nbsp; <b>③ Done.</b><br />
    <sub>Nothing to type. Claude installs it, tunes it to your usage and keeps it updated by itself.</sub>
  </p>

  <p>
    <a href="#-install-in-30-seconds">Install</a> ·
    <a href="#-the-discovery-the-quota-formula">Quota formula</a> ·
    <a href="#-the-token-trap-why-most-token-savers-backfire">Token trap</a> ·
    <a href="#%EF%B8%8F-how-it-works">How it works</a> ·
    <a href="#-the-benchmark">Benchmark</a> ·
    <a href="CONTRIBUTING.md">Contribute</a>
  </p>
</div>

<p align="center">
  <img src="assets/banner.png" alt="Last Token: get more out of your Claude plan. −68 % plan quota per task, one file to install, zero settings." width="100%" />
</p>

---

## 👀 See it working

You keep working like always. Last Token works in the background and shows you what it saved.

<p align="center">
  <img src="assets/real-session.png" width="100%" alt="One long coding session of 412 requests: 68 % less plan quota and 61.4 million tokens that were never sent again. The terminal shows the real /lt-savings output." />
</p>

<p align="center"><sub>Type <code>/lt-savings</code> to see yours.</sub></p>

---

## 🚦 It tells you when to start fresh

<p align="center"><img src="assets/whats-new.png" width="100%" alt="A live line above your prompt. Green: Last Token Active −68% quota. Red when it pays off: This chat is long. Starting a new chat for your next task uses about 47% less quota per message. Also new: new-chat hint, cold digest after an hour away, code map that jumps to a function, terse mode with no preambles or recaps." /></p>

## ✨ Why Last Token?

<p align="center">
  <img src="assets/highlights.png" width="100%" alt="Lasts longer: the same task takes 68 % less of your 5-hour window. Same quality: rules kept, facts recalled, tests passing. Stays local: one Python file, no server, no account, no telemetry. No setup: drop one file into Claude Code." />
</p>

---

<p align="center"><a href="https://github.com/ardazeybek/last-token/releases/latest/download/install-last-token.md"><img src="assets/warning.png" width="100%" alt="Read this first. Most token savers make your limit run out faster. Your plan is not billed in tokens: a token written into the prompt cache costs about 30 times more quota than one read from it. Our own early version: tokens -34 %, quota +69 %. Download the installer and drop it into Claude Code." /></a></p>

---

## ⚡ Install in 30 seconds

<p align="center"><a href="https://github.com/ardazeybek/last-token/releases/latest/download/install-last-token.md"><img src="assets/install.png" width="100%" alt="1 download the installer, 2 drop it into Claude Code and press Enter, 3 open a new chat" /></a></p>

<p align="center"><b><a href="https://github.com/ardazeybek/last-token/releases/latest/download/install-last-token.md">⬇ Download the installer</a></b> (1 KB) · works in the terminal, desktop app, VS Code and JetBrains</p>

### 🔄 Updates itself

<p align="center"><img src="assets/updates.png" width="100%" alt="Updates itself: you open Claude Code, it checks GitHub quietly in the background at most every 3 hours, installs the new version and runs a full self-check. If something broke, one background session fixes it for you. To turn it off: echo {auto: false} into ~/.claude/last-token/update.json" /></p>

<sub>Log: <code>~/.claude/last-token/update.log</code> · Update by hand: <code>python3 ~/.claude/last-token/ctx.py self-update</code></sub>

<details>
<summary><b>Rather paste a sentence?</b></summary>

```text
Install Last Token for me: clone https://github.com/ardazeybek/last-token into ~/.claude/last-token/src, then read INSTALL.md there and follow it step by step.
```
</details>

<details>
<summary><b>Prefer the terminal? One line.</b></summary>

```bash
curl -fsSL https://raw.githubusercontent.com/ardazeybek/last-token/master/get.sh | bash
```

Needs `git` and `python3` (3.9+). macOS, Linux and Windows through WSL.
</details>

<details>
<summary><b>Uninstall (one line, restores your previous settings)</b></summary>

```bash
python3 ~/.claude/last-token/ctx.py global off && python3 ~/.claude/last-token/ctx.py mod uninstall
```

A backup of your `~/.claude/settings.json` is also written on every install (`settings.json.bak-ctx-*`).
</details>

---

## 🔬 The discovery: the quota formula

<img src="assets/quota-formula.png" alt="cache write 4.6 points, output 3-7 points, cache read 0.15 points per million tokens" width="100%">

<p align="center"><img src="assets/plain-words.png" width="100%" alt="So in plain words: context that just sits there is almost free. Every time the cache is written again (a summary compaction, a long break, a changed system prompt, a fresh subagent) costs about 30 times more. The API price list says 10 times; on plan quota it is about 30 times." /></p>

<p align="center"><img src="assets/quota-share.png" width="100%" alt="Where the quota went in 7 days of real use: reading the cached chat 36-42 %, writing the cache 26-34 %, subagents 20-24 %, output 8-13 %." /></p>

---

## 🪤 The token trap: why most token savers backfire

<img src="assets/token-trap.png" alt="Fewer tokens, bigger bill: -34% tokens, +69% cost" width="100%">


### What this means for popular token tools

<p align="center"><img src="assets/tools.png" width="100%" alt="Popular token tools through the formula. rtk: -1.2 % tokens, within noise. caveman: right target, but output is only 8-13 % of quota. context-mode: keeps big outputs out, can help. claudectx: saves cheap cached reads, cutting instructions can hurt. Compressors: each rewrite moves the cached prefix, pruning a warm cache cost +92 %. Rule of thumb: a tool that changes your context mid-session is likely costing you quota." /></p>

<p align="center"><sub><a href="https://github.com/rtk-ai/rtk">rtk</a> · <a href="https://github.com/JuliusBrussee/caveman">caveman</a> · <a href="https://github.com/mksglu/context-mode">context-mode</a> · <a href="https://github.com/horilla/claudectx">claudectx</a></sub></p>

---

## ⚙️ How it works

<img src="assets/how-it-works.png" alt="Six levers" width="100%">

<p align="center"><img src="assets/never.png" width="100%" alt="What it never does: lower Claude's effort, cut Claude's instructions or tool descriptions, touch your context while the cache is warm. Under the hood: one Python file, standard library only, three Claude Code hooks and one small mod, no server, no account, no telemetry." /></p>

---

## 📊 The benchmark

<img src="assets/benchmark.png" alt="Same work, 68 % less plan quota. Plain Claude Code = 100, Last Token 1.7 = 32, LLM-summary compaction = 157. Rules, recall and tests stay the same." width="100%">

<p align="center"><sub>20+ rounds, every failed idea included: <a href="docs/BENCHMARK.md">BENCHMARK.md</a> · raw runs: <a href="results/">results/</a> · run it yourself: <a href="bench/README.md">bench/</a></sub></p>

---

## ❓ FAQ

<p align="center"><img src="assets/faq.png" width="100%" alt="Questions people ask. Will Claude get worse? No, rules and memory stay as good or better. Do I need to work differently? No. Pro or Max? Both. Which models? All. Does it send my data? No telemetry, only the update check talks to GitHub. Can I turn it off for one project? Yes, add an empty file named .no-last-token." /></p>

Another question? [Ask in Discussions](https://github.com/ardazeybek/last-token/discussions).

---

## 🧰 For tinkerers

```bash
python3 ~/.claude/last-token/ctx.py doctor          # check every part
python3 ~/.claude/last-token/ctx.py audit           # what your fixed per-request context is made of
python3 ~/.claude/last-token/ctx.py tune            # re-compute per-model compaction points now
python3 ~/.claude/last-token/ctx.py recall <word>   # find an archived detail
python3 ~/.claude/last-token/ctx.py show <name>     # code map: one function's code (also where, uses, outline, map)
```

Per-project install instead of global: `./install.sh <project-dir>`. Developer quota pane:
`{"panel": true}` in `~/.claude/last-token/mod.json`, then `/lt-savings`.
Internals: [docs/DESIGN.md](docs/DESIGN.md) · [docs/RESEARCH.md](docs/RESEARCH.md) · [MAP.md](MAP.md).

---

## 🤝 Contributing

<p align="center">
  <a href="CONTRIBUTING.md"><img src="assets/contribute.png" width="100%" alt="Help Last Token get better. You do not need to write code. 1 share your /lt-savings numbers, 2 try it on your setup, 3 fix a word in the docs. Click to read the contributing guide." /></a>
</p>

<p align="center"><sub>Please follow the <a href="CODE_OF_CONDUCT.md">code of conduct</a>.</sub></p>

## 💬 Support

<p align="center">
  <a href="https://github.com/ardazeybek/last-token/issues/new/choose"><img src="assets/support-issues.png" width="32%" alt="Found a bug? Open a GitHub Issue" /></a>
  <a href="https://github.com/ardazeybek/last-token/discussions"><img src="assets/support-discussions.png" width="32%" alt="Ideas and questions: GitHub Discussions" /></a>
  <a href="mailto:quantastudio.dev@gmail.com"><img src="assets/support-mail.png" width="32%" alt="Anything else: send an email" /></a>
</p>

## 📜 License

<p align="center">
  <a href="LICENSE"><img src="assets/license.png" width="100%" alt="MIT license. Free, yours to use: use it, change it, share it. No account, no telemetry. Copyright Arda Zeybek. An independent project, not affiliated with or endorsed by Anthropic. Claude and Claude Code are trademarks of Anthropic. Did Last Token give you back some hours of Claude? A star helps other people find it: press Star at the top of this page." /></a>
</p>

