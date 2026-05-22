#!/usr/bin/env bash
# init.sh — startup + baseline verification for CMP Ensemble HM.
#
# Runs from Git Bash on Windows or any POSIX shell. On native PowerShell,
# run the equivalent commands manually:
#   python -m pip install -e .[dev]
#   pytest -q
#
# This script:
#   1) prints the working directory
#   2) installs Python dependencies in editable mode
#   3) runs the baseline test suite (pytest)
#   4) prints the CLI entry point
#
# If RUN_START_COMMAND=1, the entry point is launched directly.
#
# IMPORTANT: until Feature `scaffold-001` (pyproject.toml + package layout) is
# complete, INSTALL_CMD and VERIFY_CMD will fail. That is the expected state at
# session 0 — fix scaffold-001 first.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# Python-based pipeline; npm equivalents from the template are removed.
INSTALL_CMD=(python -m pip install -e ".[dev]")
VERIFY_CMD=(pytest -q)
START_CMD=(cmp-ensemble --help)

echo "==> Working directory: $PWD"

# Sanity: Python 3.11+ is required by the pipeline. Refuse to proceed otherwise.
PY_VERSION="$(python -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
PY_MAJOR="${PY_VERSION%%.*}"
PY_MINOR="${PY_VERSION##*.}"
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
  echo "ERROR: Python 3.11+ required, found $PY_VERSION." >&2
  exit 1
fi
echo "==> Python version: $PY_VERSION (OK)"

# Sanity: pyproject.toml must exist before we attempt install.
if [ ! -f "pyproject.toml" ]; then
  echo "==> pyproject.toml not found — scaffold-001 has not been completed yet."
  echo "    Skipping install + verification. Implement scaffold-001 first."
  exit 2
fi

echo "==> Syncing dependencies"
"${INSTALL_CMD[@]}"

echo "==> Running baseline verification"
"${VERIFY_CMD[@]}"

echo "==> CLI entry point"
printf '    %q' "${START_CMD[@]}"
printf '\n'

if [ "${RUN_START_COMMAND:-0}" = "1" ]; then
  echo "==> Launching the CLI"
  exec "${START_CMD[@]}"
fi

echo "Set RUN_START_COMMAND=1 if you want init.sh to launch the CLI directly."
