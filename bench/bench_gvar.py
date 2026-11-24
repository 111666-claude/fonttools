"""Replayable benchmark for full gvar glyph instantiation.

Builds a synthetic glyf+gvar variable font whose glyphs each carry
NUM_TUPLES variation tuples, then times instantiateGvar() at a fully pinned
location REPEAT times. Reports per-run wall-clock median and tracemalloc
peak allocations. Run with the repo on PYTHONPATH, e.g.:

    PYTHONPATH=Lib python3 -I bench/bench_gvar.py
"""
import gc
import statistics
import sys
import time
import tracemalloc

sys.path.insert(0, "/home/real666/feedback/uid41/Lib")

from copy import deepcopy

from fontTools import ttLib
from fontTools.ttLib.tables.TupleVariation import TupleVariation
from fontTools.ttLib.tables import _g_l_y_f
from fontTools.varLib import instancer
from fontTools.varLib.instancer import (
    NormalizedAxisLimits,
    NormalizedAxisTripleAndDistances,
)

NUM_TUPLES = 120
NUM_POINTS = 60
NUM_GLYPHS = 24
REPEAT = 50
WARMUP = 5


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
    font["loca"] = _l_o_c_a.table__l_o_c_a()

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


def snapshot(font):
    """Per-glyph point coordinates + metrics, for pointwise comparison."""
    glyf = font["glyf"]
    result = {}
    for name in glyf.glyphOrder:
        g = glyf[name]
        if g.numberOfContours == 0:
            result[name] = (g.numberOfContours, font["hmtx"].metrics.get(name))
            continue
        coords, _ = glyf._getCoordinatesAndControls(
            name, font["hmtx"].metrics,
            getattr(font.get("vmtx"), "metrics", None),
        )
        result[name] = (
            [tuple(p) for p in coords],
            (g.xMin, g.yMin, g.xMax, g.yMax),
            font["hmtx"].metrics.get(name),
        )
    return result


def run_once(base, limits):
    f = deepcopy(base)
    instancer.instantiateGvar(f, limits, optimize=True)
    return f


def main():
    base = build_font()
    limits = pinned_limits()
    expected = snapshot(run_once(base, limits))

    # correctness guard: every repeat must produce the same snapshot
    for _ in range(3):
        assert snapshot(run_once(base, limits)) == expected

    # allocation counters on the hot path (one instantiation)
    from fontTools.ttLib.tables.TupleVariation import TupleVariation

    orig_new = TupleVariation.__new__
    orig_scale = TupleVariation.scaleDeltas
    counts = {"new": 0, "scale": 0}

    def traced_new(cls, *a, **k):
        counts["new"] += 1
        return orig_new(cls)

    def traced_scale(self, scalar):
        counts["scale"] += 1
        return orig_scale(self, scalar)

    TupleVariation.__new__ = staticmethod(traced_new)
    TupleVariation.scaleDeltas = traced_scale
    try:
        f = deepcopy(base)  # allocations here are outside the measured hot path
        counts["new"] = 0
        counts["scale"] = 0
        instancer.instantiateGvar(f, limits, optimize=True)
    finally:
        TupleVariation.__new__ = staticmethod(orig_new)
        TupleVariation.scaleDeltas = orig_scale

    # timed phase excludes deepcopy, matching "instantiation cost" in isolation;
    # pre-built copies keep the hot path measurement free of copy noise.
    copies = [deepcopy(base) for _ in range(REPEAT + WARMUP)]
    gc.collect()
    gc.disable()
    try:
        times = []
        for i, f in enumerate(copies):
            t0 = time.perf_counter()
            instancer.instantiateGvar(f, limits, optimize=True)
            dt = time.perf_counter() - t0
            if i >= WARMUP:
                times.append(dt)
    finally:
        gc.enable()

    # allocation phase: one instantiation under tracemalloc (excludes deepcopy)
    tracemalloc.start()
    f = deepcopy(base)
    gc.collect()
    tracemalloc.reset_peak()
    instancer.instantiateGvar(f, limits, optimize=True)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print(f"tuples/glyph={NUM_TUPLES} glyphs={NUM_GLYPHS} repeats={REPEAT}")
    print(
        "hot-path allocations per instantiation: "
        f"TupleVariation.__new__={counts['new']} scaleDeltas={counts['scale']}"
    )
    print("instantiate-only wall time (ms):")
    print("  median = %.3f" % (statistics.median(times) * 1000))
    print("  min    = %.3f" % (min(times) * 1000))
    print("  max    = %.3f" % (max(times) * 1000))
    print("  mean   = %.3f" % (statistics.mean(times) * 1000))
    print(
        "tracemalloc peak (instantiate only, no deepcopy) = %.1f KiB"
        % (peak / 1024)
    )


if __name__ == "__main__":
    main()
