import sys
from pathlib import Path

# Ensure the in-tree Lib/ package is preferred over any stale editable install.
_LIB = Path(__file__).resolve().parent / "Lib"
if _LIB.is_dir() and str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))
