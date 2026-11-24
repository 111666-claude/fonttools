import os
import sys

# Ensure the checkout's local ``Lib`` package takes precedence over any
# globally installed/editable fontTools (which may point at another
# workspace on a shared machine).
_LIB = os.path.join(os.path.dirname(__file__), "Lib")
if os.path.isdir(_LIB) and _LIB not in sys.path:
    sys.path.insert(0, _LIB)
