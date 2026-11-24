import sys
from pathlib import Path

# Allow running the tests against this checkout's Lib/ sources without an
# editable install pointing at this worktree.
_LIB = Path(__file__).resolve().parent / "Lib"
if _LIB.is_dir() and str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))
