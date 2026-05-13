#!/usr/bin/env bash
# Install lumicc-watch into an OpenClaw workspace.
# Adds:
#   1) Symlink/copy of this skill into workspace/skills/lumicc-watch
#   2) Cron entries to workspace HEARTBEAT.md (default: 09:00 and 21:00 daily)
#
# Usage:
#   bash install-openclaw.sh                        # auto-detect default workspace
#   bash install-openclaw.sh --workspace ~/.openclaw/workspace-pets
#   bash install-openclaw.sh --no-cron              # install skill only, skip cron edits
#   bash install-openclaw.sh --notify-channel feishu --notify-target group:跨境运营组

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"  # skill directory

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
    -h|--help)
      sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "Unknown arg: $1"; exit 2 ;;
  esac
done

# Detect workspace if not provided
if [[ -z "$WORKSPACE" ]]; then
  if [[ -d "$HOME/.openclaw" ]]; then
    # Pick first workspace-* directory
    WORKSPACE="$(ls -d "$HOME"/.openclaw/workspace-* 2>/dev/null | head -1)"
  fi
  if [[ -z "$WORKSPACE" || ! -d "$WORKSPACE" ]]; then
    echo "Could not auto-detect OpenClaw workspace. Pass --workspace PATH" >&2
    exit 2
  fi
  echo "Using workspace: $WORKSPACE"
fi

[[ -d "$WORKSPACE" ]] || { echo "Workspace not found: $WORKSPACE"; exit 2; }

# 1) Install skill into workspace/skills/lumicc-watch
mkdir -p "$WORKSPACE/skills"
TARGET_SKILL_DIR="$WORKSPACE/skills/lumicc-watch"
if [[ -e "$TARGET_SKILL_DIR" ]]; then
  echo "Skill already installed at $TARGET_SKILL_DIR — refreshing"
  rm -rf "$TARGET_SKILL_DIR"
fi
cp -R "$SKILL_ROOT" "$TARGET_SKILL_DIR"
echo "✓ Skill copied to $TARGET_SKILL_DIR"

# 2) Cron entries in HEARTBEAT.md
if [[ "$INSTALL_CRON" -eq 1 ]]; then
  HEARTBEAT="$WORKSPACE/HEARTBEAT.md"
  CRON_BLOCK_START="<!-- BEGIN lumicc-watch cron (auto-managed; do not edit between markers) -->"
  CRON_BLOCK_END="<!-- END lumicc-watch cron -->"

  EXTRA_NOTIFY=""
  if [[ -n "$NOTIFY_CHANNEL" ]]; then
    EXTRA_NOTIFY=" --notify-channel ${NOTIFY_CHANNEL} --notify-target \"${NOTIFY_TARGET:-}\""
  fi

  BLOCK=$(cat <<EOF
${CRON_BLOCK_START}

## lumicc-watch (cron)

- \`0 9,21 * * *\` → \`python3 ${TARGET_SKILL_DIR}/scripts/run.py --all-stores${EXTRA_NOTIFY} --quiet-stdout\`
  - Daily competitor watchtower snapshots (morning + evening).
  - Output to ~/.commerce-os/runs/<id>/report.md
  - Notifications via ~/.commerce-os/outbox/*.json (OpenClaw gateway delivers)

${CRON_BLOCK_END}
EOF
)

  if [[ -f "$HEARTBEAT" ]]; then
    # Replace existing block if present
    if grep -q "$CRON_BLOCK_START" "$HEARTBEAT"; then
      python3 - "$HEARTBEAT" "$CRON_BLOCK_START" "$CRON_BLOCK_END" <<'PY' >"$HEARTBEAT.tmp"
import sys, re
path, start, end = sys.argv[1], sys.argv[2], sys.argv[3]
import pathlib
text = pathlib.Path(path).read_text(encoding="utf-8")
new_block = sys.stdin.read()
pattern = re.compile(re.escape(start) + ".*?" + re.escape(end), re.DOTALL)
text = pattern.sub(new_block.strip(), text)
sys.stdout.write(text)
PY
      mv "$HEARTBEAT.tmp" "$HEARTBEAT"
    else
      printf "\n%s\n" "$BLOCK" >> "$HEARTBEAT"
    fi
  else
    cat > "$HEARTBEAT" <<EOF
# Heartbeat schedule

${BLOCK}
EOF
  fi
  echo "✓ Cron block written to $HEARTBEAT"
else
  echo "ℹ Skipped cron installation (--no-cron)"
fi

# 3) Print user-facing summary
cat <<EOF

----------------------------------------------------------------------
lumicc-watch installed for OpenClaw workspace.

Workspace: $WORKSPACE
Skill:     $TARGET_SKILL_DIR
Cron:      $([[ $INSTALL_CRON -eq 1 ]] && echo "daily 09:00 + 21:00 in $WORKSPACE/HEARTBEAT.md" || echo "skipped")

Next steps:
  1) Add your competitor URLs:
       python3 ${TARGET_SKILL_DIR}/../lumicc/scripts/memory.py log \\
         --category preference \\
         --content '{"watchtower_targets": ["https://shop1.com", "https://shop2.com"]}'
     (or insert directly into the preferences table; see references/required-skills.md)

  2) Restart your OpenClaw agent so it picks up the new HEARTBEAT.md.

  3) Test manually:
       python3 ${TARGET_SKILL_DIR}/scripts/run.py --target https://shop1.com

----------------------------------------------------------------------
EOF
