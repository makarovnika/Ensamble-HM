#!/usr/bin/env bash
# Install the project's git hooks into .git/hooks/.
# Re-run this after every fresh clone — git does not version-control hooks.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK_SRC="$ROOT/scripts/pre-commit.sh"
HOOK_DST="$ROOT/.git/hooks/pre-commit"

if [ ! -d "$ROOT/.git" ]; then
  echo "ERROR: $ROOT is not a git repository." >&2
  exit 1
fi
if [ ! -f "$HOOK_SRC" ]; then
  echo "ERROR: hook source $HOOK_SRC not found." >&2
  exit 1
fi

mkdir -p "$ROOT/.git/hooks"
cp "$HOOK_SRC" "$HOOK_DST"
chmod +x "$HOOK_DST" 2>/dev/null || true   # Windows git ignores chmod

echo "✓ Installed pre-commit hook → $HOOK_DST"
echo "  Bypass with ALLOW_SRC_ONLY=1 git commit ..."
