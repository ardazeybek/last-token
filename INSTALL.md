# INSTALL.md — instructions for Claude Code (the agent doing the install)

The person asked you to install Last Token. It makes their Claude plan quota last longer. Follow these
steps in order, then report in the person's language. Keep your messages short and friendly; they may not be technical.

## 1. Check the requirements
Run: `command -v git python3 && python3 -c 'import sys; print(sys.version_info >= (3, 9))'`
- Both must exist and the last line must be `True`. If not, tell the person what is missing
  (git, or Python 3.9+) and how to get it on their OS, then stop.
- Native Windows without WSL: tell them to use WSL (Claude Code inside WSL), then stop.

## 2. Get the code (or update it)
- If `~/.claude/last-token/src/.git` exists: `git -C ~/.claude/last-token/src pull --ff-only`
- Otherwise: `git clone --depth 1 https://github.com/ardazeybek/last-token ~/.claude/last-token/src`

## 3. Install for every Claude Code session
Run: `bash ~/.claude/last-token/src/install.sh --global`

What it does (tell the person in one or two lines, no more):
- backs up `~/.claude/settings.json` (`settings.json.bak-ctx-<time>`), then adds three hooks
  (memory loader, archive before compaction, big-file guard) and the Last Token mod;
- measures the person's own usage and sets the best compaction point for each Claude model.

## 4. Verify
Run: `python3 ~/.claude/last-token/ctx.py doctor`
- Exit code 0 and every line ✅ → success.
- Any ❌ → run step 3 once more and verify again. Still ❌ → show the person the doctor output and stop.

## 5. Tell the person (success)
Show the doctor output in a code block, then say, in their language, roughly:
> ✅ Last Token is installed. Open a **new** Claude Code session: you'll see `last-token ✓` at the
> bottom. From now on it works by itself in every project. Your limit will last longer, and
> rules/decisions you give me survive compactions. New versions install themselves in the background. To uninstall: `python3 ~/.claude/last-token/ctx.py global off && python3 ~/.claude/last-token/ctx.py mod uninstall`

Do not change anything else in the person's settings or projects.
