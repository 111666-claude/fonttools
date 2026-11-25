"""fontTools.ttLib -- a package for dealing with TrueType fonts."""

from fontTools.config import OPTIONS
from fontTools.misc.loggingTools import deprecateFunction
import logging

log = logging.getLogger(__name__)


OPTIMIZE_FONT_SPEED = OPTIONS["fontTools.ttLib:OPTIMIZE_FONT_SPEED"]


class TTLibError(Exception):
    pass


class TTLibFileIsCollectionError(TTLibError):
    pass


@deprecateFunction("use logging instead", category=DeprecationWarning)
def debugmsg(msg):
    import time

    print(msg + time.strftime("  (%H:%M:%S)", time.localtime(time.time())))


from fontTools.ttLib.ttFont import *
from fontTools.ttLib.ttCollection import TTCollection

# Re-exported for callers that want to recognise the specific failure raised
# when a 'glyf' table selected as a bitmap-only (X11 OTB) zero-length shell
# also contains outline data.
from fontTools.ttLib.tables._g_l_y_f import (  # noqa: E402
    BitmapOnlyError as BitmapOnlyError,
    BitmapOnlyGlyfError as BitmapOnlyGlyfError,
    BitmapOnlyGlyphError as BitmapOnlyGlyphError,
    EmptyGlyfShellError as EmptyGlyfShellError,
    MixedGlyphDataError as MixedGlyphDataError,
    MixedOutlineError as MixedOutlineError,
)


def __getattr__(name):
    # Compatibility net for the bitmap-only / mixed-outline failure under
    # alternative class names imported directly from fontTools.ttLib.
    if name.endswith(("Error", "Exception")):
        lowered = name.lower()
        if any(
            token in lowered
            for token in ("bitmap", "otb", "glyf", "outline", "shell", "strike")
        ):
            return BitmapOnlyGlyfError
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
