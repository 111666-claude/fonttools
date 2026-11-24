"""Trace per-tuple operations during a full gvar instantiation.

Builds a synthetic glyf+gvar variable font with a configurable number of
variation tuples per glyph, then runs the instancer at a pinned location and
counts the intermediate coordinate-bearing objects created along the way.
"""
import sys

sys.path.insert(0, "/home/real666/feedback/uid41/Lib")

from fontTools import ttLib
from fontTools.ttLib.tables.TupleVariation import TupleVariation
from fontTools.ttLib.tables import _g_l_y_f
from fontTools.varLib import instancer
from fontTools.varLib.instancer import NormalizedAxisLimits, NormalizedAxisTripleAndDistances

NUM_TUPLES = 120
NUM_POINTS = 60  # outline points; +4 phantom points
NUM_GLYPHS = 24
REPEAT = 50


def build_font():
    font = ttLib.TTFont()
    font.setGlyphOrder([".notdef"] + ["g%d" % i for i in range(NUM_GLYPHS - 1)])

    glyf = _g_l_y_f.table__g_l_y_f()
    glyf.glyphs = {}
    glyf.glyphOrder = font.getGlyphOrder()
    for name in font.getGlyphOrder():
        glyph = _g_l_y_f.Glyph()
        glyph.numberOfContours = 1
        glyph.coordinates = _g_l_y_f.GlyphCoordinates(
            [(100 + i, 200 + i) for i in range(NUM_POINTS)]
        )
        glyph.flags = [1] * NUM_POINTS
        glyph.endPtsOfContours = [NUM_POINTS - 1]
        glyph.program = ttLib.tables.ttProgram.Program()
        glyph.program.fromBytecode(b"")
        glyf.glyphs[name] = glyph
    font["glyf"] = glyf

    # minimal head/hmtx/loca/maxp/post needed for coordinate round-trip
    from fontTools.ttLib.tables import _h_e_a_d, _h_m_t_x, _m_a_x_p, _p_o_s_t, _l_o_c_a

    head = _h_e_a_d.table__h_e_a_d()
    head.tableVersion = 0x00010000
    head.fontRevision = 1.0
    head.checkSumAdjustment = 0
    head.magicNumber = 0x5F0F3CF5
    head.flags = 0
    head.unitsPerEm = 1000
    head.created = 0
    head.modified = 0
    head.xMin = 0
    head.yMin = 0
    head.xMax = 500
    head.yMax = 500
    head.macStyle = 0
    head.lowestRecPPEM = 8
    head.fontDirectionHint = 2
    head.indexToLocFormat = 0
    head.glyphDataFormat = 0
    font["head"] = head

    maxp = _m_a_x_p.table__m_a_x_p()
    maxp.tableVersion = 0x00010000
    maxp.numGlyphs = NUM_GLYPHS
    font["maxp"] = maxp

    hmtx = _h_m_t_x.table__h_m_t_x()
    hmtx.metrics = {name: (600, 50) for name in font.getGlyphOrder()}
    font["hmtx"] = hmtx

    post = _p_o_s_t.table__p_o_s_t()
    post.formatType = 3.0
    post.italicAngle = 0
    post.underlinePosition = -100
    post.underlineThickness = 50
    post.isFixedPitch = 0
    post.minMemType42 = 0
    post.maxMemType42 = 0
    post.minMemType1 = 0
    post.maxMemType1 = 0
    font["post"] = post

    loca = _l_o_c_a.table__l_o_c_a()
    font["loca"] = loca

    # gvar with NUM_TUPLES tuples per glyph. Mix sparse (IUP) and dense tuples,
    # positive and negative tents, and fractional scalars at the pin location.
    gvar = ttLib.newTable("gvar")
    gvar.version = 1
    gvar.reserved = 0
    gvar.variations = {}
    for name in font.getGlyphOrder():
        tuples = []
        for t in range(NUM_TUPLES):
            axis = "wght" if t % 2 == 0 else "wdth"
            peak = 0.5 if t % 2 == 0 else -0.5
            tuples.append(
                TupleVariation(
                    {axis: (min(0.0, peak), peak, max(0.0, peak))},
                    [
                        None
                        if (t % 3 == 0 and i % 4 != 0)
                        else (t + i * 0.25, -(t * 0.5) + i)
                        for i in range(NUM_POINTS + 4)
                    ],
                )
            )
        gvar.variations[name] = tuples
    font["gvar"] = gvar

    # fvar with wght + wdth axes
    from fontTools.ttLib.tables import _f_v_a_r

    fvar = _f_v_a_r.table__f_v_a_r()
    fvar.majorVersion = 1
    fvar.minorVersion = 0
    axes = []
    for tag in ("wght", "wdth"):
        ax = _f_v_a_r.Axis()
        ax.axisTag = tag
        ax.axisNameID = 256
        ax.minValue = 0.0
        ax.defaultValue = 0.0
        ax.maxValue = 1.0
        ax.flags = 0
        axes.append(ax)
    fvar.axes = axes
    fvar.instances = []
    font["fvar"] = fvar

    return font


def pinned_limits():
    return NormalizedAxisLimits(
        {
            "wght": NormalizedAxisTripleAndDistances(0.3, 0.3, 0.3),
            "wdth": NormalizedAxisTripleAndDistances(-0.7, -0.7, -0.7),
        }
    )


def main():
    from copy import deepcopy

    base_font = build_font()
    axis_limits = pinned_limits()

    # Instrument allocation hot spots
    orig_new = TupleVariation.__new__
    orig_scale = TupleVariation.scaleDeltas
    orig_iup = TupleVariation.calcInferredDeltas
    new_var_count = [0]
    scale_count = [0]
    iup_count = [0]

    def traced_new(cls, *a, **k):
        new_var_count[0] += 1
        return orig_new(cls)

    def traced_scale(self, scalar):
        scale_count[0] += 1
        return orig_scale(self, scalar)

    def traced_iup(self, *a, **k):
        iup_count[0] += 1
        return orig_iup(self, *a, **k)

    TupleVariation.__new__ = staticmethod(traced_new)
    TupleVariation.scaleDeltas = traced_scale
    TupleVariation.calcInferredDeltas = traced_iup
    try:
        for _ in range(REPEAT):
            f = deepcopy(base_font)
            instancer.instantiateGvar(f, axis_limits, optimize=True)
    finally:
        TupleVariation.__new__ = staticmethod(orig_new)
        TupleVariation.scaleDeltas = orig_scale
        TupleVariation.calcInferredDeltas = orig_iup

    print("TupleVariation.__new__ allocations:", new_var_count[0])
    print("scaleDeltas() calls:", scale_count[0])
    print("calcInferredDeltas() calls:", iup_count[0])
    print("per instantiation: new=%d scale=%d iup=%d" % (
        new_var_count[0] // REPEAT,
        scale_count[0] // REPEAT,
        iup_count[0] // REPEAT,
    ))


if __name__ == "__main__":
    main()
