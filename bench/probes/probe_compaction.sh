#!/usr/bin/env bash
# probe_compaction.sh — reproduce the Claude Code behaviours last-token relies on:
#  1) CLAUDE_AUTOCOMPACT_PCT_OVERRIDE set via settings.json "env" moves the auto-compaction trigger
#  2) PreCompact hook stdout is used as summarisation instructions
#  3) CLAUDE.md @imports are re-read from disk after compaction
# usage: bash probe_compaction.sh [workdir]   (costs a few cents with haiku)
set -euo pipefail
W="${1:-$(mktemp -d)}"; mkdir -p "$W/.claude" "$W/.ctx"; cd "$W"
python3 - <<'EOF'
import random
random.seed(1); w = "alpha beta gamma delta epsilon zeta theta kappa lambda sigma omega river stone cloud".split()
for i in range(1, 4):
    open(f"big{i}.txt", "w").write("".join(f"{i}-{n}: " + " ".join(random.choice(w) for _ in range(8)) + "\n" for n in range(1, 1900)))
EOF
printf '# Probe\n@.ctx/INDEX.md\n' > CLAUDE.md; echo "INDEX version: v1" > .ctx/INDEX.md
cat > .claude/settings.json <<'EOF'
{"env":{"CLAUDE_AUTOCOMPACT_PCT_OVERRIDE":"50"},
 "hooks":{"PreCompact":[{"hooks":[{"type":"command","command":"echo 'INDEX version: v2' > .ctx/INDEX.md; echo 'Summary rule: the summary MUST contain the literal token BANANA-SUMMARY on its first line.'"}]}]}}
EOF
SID=$(python3 -c "import uuid;print(uuid.uuid4())")
C=(env -i HOME="$HOME" PATH="$PATH" USER="$USER" LANG=C.UTF-8 CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 claude -p --model haiku
   --setting-sources project --strict-mcp-config --output-format json --autocompact 100000 --permission-mode bypassPermissions --tools Bash,Read)
"${C[@]}" --session-id "$SID" "Read big1.txt lines 1-900 with Read and tell me line 900." </dev/null >/dev/null
for i in 2 3; do "${C[@]}" --resume "$SID" "Read big$i.txt lines 1-900 with Read and tell me line 900." </dev/null >/dev/null; done
"${C[@]}" --resume "$SID" "Quote exactly the INDEX version line in your context. Nothing else." </dev/null | python3 -c "import json,sys;print('import after compaction ->',json.load(sys.stdin)['result'])"
T=$(ls ~/.claude/projects/*/"$SID".jsonl | head -1)
python3 - "$T" <<'EOF'
import json, sys
for l in open(sys.argv[1]):
    d = json.loads(l)
    if d.get("subtype") == "compact_boundary":
        m = d["compactMetadata"]; print(f"compaction: preTokens={m['preTokens']} postTokens={m['postTokens']} (window 100000, pct 50)")
    if d.get("isCompactSummary"):
        c = d["message"]["content"]; s = c if isinstance(c, str) else c[0].get("text", "")
        print("PreCompact instruction obeyed:", "BANANA-SUMMARY" in s)
EOF
