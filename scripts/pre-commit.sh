#!/usr/bin/env bash
# pre-commit hook: tracker discipline.
#
# Refuse a commit that touches src/ without also touching one of the
# tracker files (feature_list.json or claude-progress.md). The bypass
# escape hatch is `ALLOW_SRC_ONLY=1 git commit ...`.
#
# The decision is mirrored in src/cmp_ensemble/tracker.py so the rule is
# unit-tested. Install this script with `scripts/install_hooks.sh` or by
# copying it to `.git/hooks/pre-commit` and chmod +x.

set -euo pipefail

if [ "${ALLOW_SRC_ONLY:-0}" = "1" ]; then
  echo "[pre-commit] tracker check bypassed via ALLOW_SRC_ONLY=1" >&2
  exit 0
fi

# List staged files Added / Copied / Modified (skip deletions / renames-only)
files="$(git diff --cached --name-only --diff-filter=ACM || true)"

if [ -z "$files" ]; then
  exit 0
fi

touched_src=0
touched_tracker=0

while IFS= read -r f; do
  case "$f" in
    src/*)
      touched_src=1
      ;;
    feature_list.json|claude-progress.md)
      touched_tracker=1
      ;;
  esac
done <<EOF
$files
EOF

if [ "$touched_src" = "1" ] && [ "$touched_tracker" = "0" ]; then
  cat >&2 <<MSG
[pre-commit] tracker discipline check failed
  Changes under src/ were staged without an accompanying update to
  feature_list.json or claude-progress.md.

  Required actions (one or more):
    • mark the affected feature as 'passing' / 'in_progress' in feature_list.json
    • append a Session N block in claude-progress.md
    • document the change

  To bypass for an emergency commit:
    ALLOW_SRC_ONLY=1 git commit ...
MSG
  exit 1
fi

exit 0
