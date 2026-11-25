"""Build the ``VARC`` table from glyphs made of variable components.

Variable components are produced by pens implementing
``addVarComponent`` (e.g. :class:`fontTools.pens.ttGlyphPen.TTGlyphPen`).
Such pens attach a list of
:class:`fontTools.ttLib.tables.otTables.VarComponent` objects to the
returned glyf glyph through its ``varComponents`` attribute. The glyf
records themselves stay empty; this module collects the components,
resolves their (axis tag -> location) mappings against the font's
``fvar`` axes and writes the shared ``VARC`` table.

See also https://github.com/harfbuzz/boring-expansion-spec/blob/main/VARC.md
"""

import math

from fontTools.misc.fixedTools import floatToFixed as fl2fi
from fontTools.pens.basePen import PenError
from fontTools.ttLib import newTable
from fontTools.ttLib.tables import otTables
from fontTools.ttLib.tables.otTables import (
    NO_VARIATION_INDEX,
    VAR_TRANSFORM_MAPPING,
    VarComponentFlags,
)

__all__ = ["buildVARC", "buildVarComponent", "VAR_AXIS_VALUE_FRACTIONAL_BITS"]

# Axis values in a VarComponent are stored as F2Dot14 packed deltas.
VAR_AXIS_VALUE_FRACTIONAL_BITS = 14


def buildVarComponent(
    glyphName,
    transformation,
    location,
    axisTagToIndex,
    axisIndicesList,
    axisIndicesCache,
    *,
    resetUnspecifiedAxes=False,
):
    """Create a compile-ready :class:`VarComponent`.

    ``location`` maps fvar axis tags to normalized axis values. The
    referenced axis tuple is interned into ``axisIndicesList`` (a list of
    lists of fvar axis indices), reusing an identical tuple through
    ``axisIndicesCache``.
    """
    component = otTables.VarComponent()
    component.glyphName = glyphName
    if resetUnspecifiedAxes:
        component.flags |= VarComponentFlags.RESET_UNSPECIFIED_AXES
    component.transform = transformation
    component.axisValuesVarIndex = NO_VARIATION_INDEX
    component.transformVarIndex = NO_VARIATION_INDEX

    if location:
        axisIndices = []
        axisValues = []
        for axisTag, axisValue in location.items():
            if axisTag not in axisTagToIndex:
                raise PenError(
                    f"Variable component of '{glyphName}' references unknown "
                    f"axis {axisTag!r}"
                )
            if isinstance(axisValue, bool) or not isinstance(
                axisValue, (int, float)
            ):
                raise PenError(
                    f"Variable component location for axis {axisTag!r} must be "
                    f"a number, got {type(axisValue).__name__}"
                )
            if not math.isfinite(axisValue):
                raise PenError(
                    f"Variable component location for axis {axisTag!r} must be "
                    "finite"
                )
            fixed = fl2fi(axisValue, VAR_AXIS_VALUE_FRACTIONAL_BITS)
            if not (-0x8000 <= fixed <= 0x7FFF):
                raise PenError(
                    f"Variable component location for axis {axisTag!r} value "
                    f"{axisValue} cannot be encoded as F2Dot14"
                )
            axisIndices.append(axisTagToIndex[axisTag])
            axisValues.append(axisValue)

        key = tuple(axisIndices)
        axisIndicesIndex = axisIndicesCache.get(key)
        if axisIndicesIndex is None:
            axisIndicesIndex = len(axisIndicesList)
            axisIndicesCache[key] = axisIndicesIndex
            axisIndicesList.append(list(key))
        component.axisIndicesIndex = axisIndicesIndex
        component.axisValues = tuple(axisValues)
    else:
        component.axisIndicesIndex = None
        component.axisValues = ()

    _syncTransformFlags(component)
    return component


def _syncTransformFlags(component):
    """Set the HAVE_* transform flags for every transform field that
    differs from its VARC default, mirroring what the binary compiler
    expects."""
    flags = component.flags
    transform = component.transform
    for attr_name, mapping in VAR_TRANSFORM_MAPPING.items():
        if getattr(transform, attr_name) != mapping.defaultValue:
            flags |= mapping.flag
        else:
            flags &= ~mapping.flag
    component.flags = flags


def buildVARC(varFont, glyphNames=None):
    """Build (or replace) the ``VARC`` table of ``varFont``.

    The table is populated from the ``varComponents`` attributes of the
    font's glyf glyphs. Glyphs without variable components are ignored.

    Args:
        varFont: a :class:`~fontTools.ttLib.TTFont` containing an
            ``fvar`` table and glyf glyphs possibly carrying
            ``varComponents``.
        glyphNames: optional iterable of glyph names to consider. By
            default every glyph of the font is considered.

    Returns:
        The newly created ``VARC`` table object (also assigned to
        ``varFont["VARC"]``).
    """
    if "fvar" not in varFont:
        raise PenError(
            "VARC variable components require an fvar table defining the "
            "variation axes"
        )
    axisTagToIndex = {axis.axisTag: i for i, axis in enumerate(varFont["fvar"].axes)}

    glyf = varFont["glyf"]
    if glyphNames is None:
        glyphNames = varFont.getGlyphOrder()
    glyphOrder = set(varFont.getGlyphOrder())

    coverage = []
    varCompositeGlyphs = []
    axisIndicesList = []
    axisIndicesCache = {}

    for glyphName in glyphNames:
        glyph = glyf[glyphName]
        varComponents = getattr(glyph, "varComponents", None)
        if not varComponents:
            continue

        compiledComponents = []
        for component in varComponents:
            if component.glyphName not in glyphOrder:
                raise PenError(
                    f"Variable component of glyph '{glyphName}' references "
                    f"unknown glyph '{component.glyphName}'"
                )
            location = getattr(component, "location", None)
            if location is None:
                # Already fully resolved (e.g. re-built from an existing
                # VARC table): keep axis indices/values as-is.
                compiled = component
                _syncTransformFlags(compiled)
            else:
                reset = bool(
                    component.flags & VarComponentFlags.RESET_UNSPECIFIED_AXES
                )
                compiled = buildVarComponent(
                    component.glyphName,
                    component.transform,
                    location,
                    axisTagToIndex,
                    axisIndicesList,
                    axisIndicesCache,
                    resetUnspecifiedAxes=reset,
                )
            compiledComponents.append(compiled)

        coverage.append(glyphName)
        varCompositeGlyphs.append(
            otTables.VarCompositeGlyph(compiledComponents)
        )

    if not coverage:
        raise PenError("No glyphs with variable components found")

    varcTable = newTable("VARC")
    table = otTables.VARC()
    varcTable.table = table

    table.Version = 0x00010000
    table.Coverage = otTables.Coverage()
    table.Coverage.glyphs = coverage
    # Static variable components carry no deltas; the optional stores are
    # left NULL as permitted by the specification.
    table.MultiVarStore = None
    table.ConditionList = None
    if axisIndicesList:
        table.AxisIndicesList = otTables.AxisIndicesList()
        table.AxisIndicesList.Item = axisIndicesList
    else:
        table.AxisIndicesList = None
    table.VarCompositeGlyphs = otTables.VarCompositeGlyphs()
    table.VarCompositeGlyphs.VarCompositeGlyph = varCompositeGlyphs

    varFont["VARC"] = varcTable
    return varcTable
