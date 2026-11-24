import os
import sys

# Ensure the in-tree package (Lib/fontTools) is imported when running the
# tests from a checkout without an editable install or PYTHONPATH set.
_LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Lib")
if os.path.isdir(_LIB) and _LIB not in sys.path:
    sys.path.insert(0, _LIB)
