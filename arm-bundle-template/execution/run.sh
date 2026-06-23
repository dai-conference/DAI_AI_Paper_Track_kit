#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PYTHON_BIN="${PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]] || ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
  PYTHON_BIN=""
  for candidate in python python3; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
      PYTHON_BIN="$candidate"
      break
    fi
  done
fi

if [[ -z "$PYTHON_BIN" ]]; then
  echo "FAIL: Python 3.10 or newer is required." >&2
  exit 1
fi

"$PYTHON_BIN" "$ROOT_DIR/execution/src/verify_headline_result.py" \
  --expected "$ROOT_DIR/execution/expected_outputs/headline_result.json"
