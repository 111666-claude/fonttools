#!/usr/bin/env bash
# Repeatable headless IUP equivalence check + regression suite.
#
# Usage:
#   Tests/varLib/run_iup_equivalence.sh             # CLI corpus + pytest
#   Tests/varLib/run_iup_equivalence.sh --cli-only
#   Tests/varLib/run_iup_equivalence.sh --pytest-only
#
# No font rendering device or optional font backend is required.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
cd "$ROOT"

# Prefer this checkout's Lib over any editable install pointing elsewhere.
export PYTHONPATH="$ROOT/Lib${PYTHONPATH:+:$PYTHONPATH}"

PY="${PYTHON:-python3}"
MODE="${1:-all}"
CASES="$ROOT/Tests/varLib/data/iup_equivalence/cases.json"

echo "== fontTools source =="
"$PY" -c "import fontTools; print(fontTools.__file__)"

if [[ "$MODE" != "--pytest-only" ]]; then
  echo "== equivalence corpus (CLI) =="
  "$PY" Tests/varLib/iup_equivalence.py "$CASES"
fi

if [[ "$MODE" != "--cli-only" ]]; then
  echo "== pytest regression suite =="
  "$PY" -m pytest Tests/varLib/iup_equivalence_test.py Tests/varLib/iup_test.py -v
fi
