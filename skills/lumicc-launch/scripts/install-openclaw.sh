#!/usr/bin/env bash
# Install lumicc-launch into an OpenClaw workspace.
# Adds:
#   1) Skill files copied to workspace/skills/lumicc-launch
#   2) Cron entry for daily 09:00 "today's tasks" push to HEARTBEAT.md
#
# Usage:
#   bash install-openclaw.sh
#   bash install-openclaw.sh --workspace ~/.openclaw/workspace-store
#   bash install-openclaw.sh --no-cron
#   bash install-openclaw.sh --notify-channel feishu --notify-target group:跨境运营组

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

WORKSPACE=""
INSTALL_CRON=1
NOTIFY_CHANNEL=""
NOTIFY_TARGET=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace) WORKSPACE="$2"; shift 2 ;;
    --no-cron)   INSTALL_CRON=0; shift ;;
    --notify-channel) NOTIFY_CHANNEL="$2"; shift 2 ;;
    --notify-target)  NOTIFY_TARGET="$2"; shift 2 ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) echo "Unknown arg: $1"; exit 2 ;;
  esac
done

if [[ -z "$WORKSPACE" ]]; then
  WORKSPACE="$(ls -d "$HOME"/.openclaw/workspace-* 2>/dev/null | head -1 || true)"
  if [[ -z "$WORKSPACE" || ! -d "$WORKSPACE" ]]; then
    echo "Could not auto-detect OpenClaw workspace. Pass --workspace PATH" >&2
    exit 2
  fi
  echo "Using workspace: $WORKSPACE"
fi
[[ -d "$WORKSPACE" ]] || { echo "Workspace not found: $WORKSPACE"; exit 2; }

mkdir -p "$WORKSPACE/skills"
TARGET="$WORKSPACE/skills/lumicc-launch"
if [[ -e "$TARGET" ]]; then
  rm -rf "$TARGET"
fi
cp -R "$SKILL_ROOT" "$TARGET"
echo "✓ Skill copied to $TARGET"

if [[ "$INSTALL_CRON" -eq 1 ]]; then
  HEARTBEAT="$WORKSPACE/HEARTBEAT.md"
  START="<!-- BEGIN lumicc-launch cron (auto-managed) -->"
  END="<!-- END lumicc-launch cron -->"

  EXTRA_NOTIFY=""
  if [[ -n "$NOTIFY_CHANNEL" ]]; then
    EXTRA_NOTIFY=" --notify-channel ${NOTIFY_CHANNEL} --notify-target \"${NOTIFY_TARGET:-}\""
  fi

  BLOCK=$(cat <<EOF
${START}

## lumicc-launch (cron)

- \`0 9 * * *\` → \`python3 ${TARGET}/scripts/day_advance.py --all-stores${EXTRA_NOTIFY} --quiet-stdout\`
  - Push today's cold-start tasks every morning at 09:00
  - Marks campaigns complete once Day 30 is passed

${END}
EOF
)

  if [[ -f "$HEARTBEAT" ]] && grep -q "$START" "$HEARTBEAT"; then
    python3 - "$HEARTBEAT" "$START" "$END" <<'PY' >"$HEARTBEAT.tmp"
import sys, re, pathlib
path, start, end = sys.argv[1], sys.argv[2], sys.argv[3]
text = pathlib.Path(path).read_text(encoding="utf-8")
new = sys.stdin.read().strip()
text = re.compile(re.escape(start) + ".*?" + re.escape(end), re.DOTALL).sub(new, text)
sys.stdout.write(text)
PY
    mv "$HEARTBEAT.tmp" "$HEARTBEAT"
  else
    [[ -f "$HEARTBEAT" ]] || echo "# Heartbeat schedule" > "$HEARTBEAT"
    printf "\n%s\n" "$BLOCK" >> "$HEARTBEAT"
  fi
  echo "✓ Cron block written to $HEARTBEAT"
fi

cat <<EOF

----------------------------------------------------------------------
lumicc-launch installed for OpenClaw.

Workspace: $WORKSPACE
Skill:     $TARGET
Cron:      $([[ $INSTALL_CRON -eq 1 ]] && echo "daily 09:00 (today's tasks)" || echo "skipped")

Next steps:
  1) Start a campaign:
       python3 ${TARGET}/scripts/plan.py --store-id <YOUR_STORE_ID>
  2) Restart your OpenClaw agent to load the new HEARTBEAT.md.
----------------------------------------------------------------------
EOF
