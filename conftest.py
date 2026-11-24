"""Pytest bootstrap for running IUP equivalence checks from a source checkout.

Inserts this checkout's ``Lib`` directory at the front of ``sys.path`` so the
tests exercise *this* tree's ``fontTools`` even when another worktree is
registered through an editable install.  In a correctly installed checkout
this is a no-op apart from front-loading the same path.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
_LIB = os.path.join(_ROOT, "Lib")
if os.path.isdir(os.path.join(_LIB, "fontTools")) and _LIB not in sys.path:
    sys.path.insert(0, _LIB)
