import os
import sys

# The library lives in ./Lib (src-layout without a src/ directory). Prepend it
# so a source checkout is tested even when another fontTools install is present
# in the ambient environment.
_LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Lib")
if os.path.isdir(_LIB) and _LIB not in sys.path:
    sys.path.insert(0, _LIB)
