#!/usr/bin/env bash
# Lumicc · multi-target installer (Claude Code / OpenClaw / Hermes / manual)
#
# Usage:
#   ./install.sh                          # interactive, auto-detect target
#   ./install.sh --yes                    # non-interactive
#   ./install.sh --target claude-code     # force target runtime
#   ./install.sh --target openclaw
#   ./install.sh --target hermes
#   ./install.sh --target DIR             # legacy: treat DIR as destination path
#   ./install.sh --dry-run                # show plan, do not write
#
# Reads install.json at repo root for bundle metadata + skill list.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$SCRIPT_DIR/skills"
MANIFEST="$SCRIPT_DIR/install.json"
TARGET_RUNTIME=""
TARGET_DIR=""
ASSUME_YES=0
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y) ASSUME_YES=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --target)
      arg="$2"; shift 2
      case "$arg" in
        claude-code|openclaw|hermes|manual)
          TARGET_RUNTIME="$arg" ;;
        *)
          # Backwards-compat: treat as raw directory path
          TARGET_RUNTIME="manual"
          TARGET_DIR="$arg" ;;
      esac
      ;;
    -h|--help)
      grep -E "^# " "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

VERSION="$(cat "$SCRIPT_DIR/VERSION" 2>/dev/null || echo "?")"
BUNDLE_NAME="lumicc"

# Read bundle name from manifest if available (python stdlib only).
if [[ -f "$MANIFEST" ]] && command -v python3 >/dev/null 2>&1; then
  BUNDLE_NAME="$(python3 -c "import json,sys; print(json.load(open('$MANIFEST')).get('bundle_name','lumicc'))" 2>/dev/null || echo lumicc)"
fi

# Auto-detect target runtime
if [[ -z "$TARGET_RUNTIME" ]]; then
  if [[ -n "${LUMICC_TARGET:-}" ]]; then
    TARGET_RUNTIME="$LUMICC_TARGET"
  elif [[ -d "$HOME/.hermes/skills" ]]; then
    TARGET_RUNTIME="hermes"
  elif [[ -d "$HOME/.openclaw/skills" ]]; then
    TARGET_RUNTIME="openclaw"
  else
    TARGET_RUNTIME="claude-code"
  fi
fi

if [[ -z "$TARGET_DIR" ]]; then
  case "$TARGET_RUNTIME" in
    claude-code) TARGET_DIR="$HOME/.claude/skills" ;;
    openclaw)    TARGET_DIR="$HOME/.openclaw/skills" ;;
    hermes)      TARGET_DIR="$HOME/.hermes/skills" ;;
    manual)      TARGET_DIR="${TARGET_DIR:-$HOME/skills}" ;;
  esac
fi

echo "──────────────────────────────────────────────"
echo "  ${BUNDLE_NAME} v${VERSION} · 跨境电商运营 OS · installer"
echo "──────────────────────────────────────────────"
echo "  Source:  $SOURCE_DIR"
echo "  Target:  $TARGET_RUNTIME  →  $TARGET_DIR"
[[ -f "$MANIFEST" ]] && echo "  Manifest: install.json (v$(python3 -c "import json; print(json.load(open('$MANIFEST'))['manifest_version'])" 2>/dev/null || echo '?'))"
echo

if [[ ! -d "$SOURCE_DIR" ]]; then
  echo "✗ Source skills/ directory not found at $SOURCE_DIR" >&2
  exit 1
fi

# Check python3
if ! command -v python3 >/dev/null 2>&1; then
  echo "✗ python3 not found in PATH. Please install Python 3.10+." >&2
  exit 1
fi
PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "✓ python3 ${PY_VER} found"

# Determine skill list (prefer manifest, fall back to filesystem)
if [[ -f "$MANIFEST" ]]; then
  SKILL_NAMES=$(python3 -c "import json; [print(s['name']) for s in json.load(open('$MANIFEST'))['skills']]")
else
  SKILL_NAMES=$(for d in "$SOURCE_DIR"/*/; do basename "$d"; done)
fi
SKILL_COUNT=$(echo "$SKILL_NAMES" | wc -l | tr -d ' ')

echo "  Will install ${SKILL_COUNT} skill(s):"
while IFS= read -r name; do
  [[ -z "$name" ]] && continue
  status="new"
  if [[ -d "$TARGET_DIR/$name" ]]; then
    status="\033[33moverwrite\033[0m"
  fi
  printf "    • %-22s [%b]\n" "$name" "$status"
done <<< "$SKILL_NAMES"
echo

if [[ $DRY_RUN -eq 1 ]]; then
  echo "[dry-run] would copy $SKILL_COUNT skills from $SOURCE_DIR to $TARGET_DIR"
  echo "[dry-run] no files written."
  exit 0
fi

if [[ $ASSUME_YES -ne 1 ]]; then
  read -r -p "Continue? [y/N] " ans
  case "$ans" in [yY]*) ;; *) echo "Aborted."; exit 0 ;; esac
fi

mkdir -p "$TARGET_DIR"

if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete --exclude='__pycache__' --exclude='*.pyc' --exclude='.DS_Store' \
    "$SOURCE_DIR/" "$TARGET_DIR/"
else
  for d in "$SOURCE_DIR"/*/; do
    name=$(basename "$d")
    rm -rf "$TARGET_DIR/$name"
    cp -R "$d" "$TARGET_DIR/$name"
    find "$TARGET_DIR/$name" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
  done
fi
echo "✓ skills copied to $TARGET_DIR"

# Optionally surface launcher
LAUNCHER="$SCRIPT_DIR/bin/lumicc"
if [[ -x "$LAUNCHER" ]]; then
  echo
  echo "  Launcher: $LAUNCHER"
  echo "  Symlink to PATH if you want it global, e.g.:"
  echo "      ln -sf \"$LAUNCHER\" /usr/local/bin/lumicc"
fi

echo
echo "──────────────────────────────────────────────"
echo "  ✓ ${BUNDLE_NAME} v${VERSION} installed (target: ${TARGET_RUNTIME})."
echo
echo "  Next steps:"
echo "    1) Initialize a store:    ./bin/lumicc init"
echo "    2) Verify everything:     ./bin/lumicc test     (15+ should pass)"
echo "    3) Open the dashboard:    ./bin/lumicc dashboard"
echo "  Or in Claude Code, say: '我开新独立站做宠物用品，给我 30 天计划'"
echo "──────────────────────────────────────────────"
