# Install Last Token

> **You (the person):** you just dropped this file into Claude Code. Press **Enter**. That's it.
> **Claude:** the person wants Last Token installed. Do everything below yourself; they don't need to type anything.

Last Token makes the person's Claude plan quota last longer (same work, same quality).
Project page: https://github.com/ardazeybek/last-token

## Steps for Claude
1. Get the code (or update it):
   - If `~/.claude/last-token/src/.git` exists: `git -C ~/.claude/last-token/src pull --ff-only`
   - Otherwise: `git clone --depth 1 https://github.com/ardazeybek/last-token ~/.claude/last-token/src`
2. Open `~/.claude/last-token/src/INSTALL.md` and follow it step by step (requirements, install, verify).
3. Reply in the person's language with the short success message from INSTALL.md.

Updates install themselves in the background from then on; nothing else to do.
