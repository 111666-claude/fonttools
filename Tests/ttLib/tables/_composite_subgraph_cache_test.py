"""Count-based and real-font regressions for shared composite subgraph caching.

The maxp profile calculation and the TrueType bounding-box recalculation both
walk composite glyph component graphs.  When the same component is reused many
times (a DAG rather than a tree), a naive recursive walk is exponential.
These tests pin:

* a deterministic *lookup count* budget (no wall-clock flakiness),
* value/bounds equivalence with the uncached computation,
* cache isolation between fonts and across glyph modification,
* the existing handling of cycles, point-limit overflow and non-translate
  transforms,
* equivalence on a set of real bundled fonts.
"""

from pathlib import Path

import pytest

from fontTools.misc.roundTools import otRound
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, TTLibError, newTable
from fontTools.ttLib.tables._g_l_y_f import Glyph

REPO_ROOT = Path(__file__).resolve().parents[3]


def _square():
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((0, 10))
    pen.lineTo((10, 10))
    pen.lineTo((10, 0))
    pen.closePath()
    return pen.glyph()


def build_composite_dag(n):
    """g{k} uses g{k-1} twice; g0 is a 4-point square.

    g{k} flattens to ``4 * 2**k`` points and ``2**k`` contours.
    """
    glyf = newTable("glyf")
    glyf.glyphOrder = [".notdef"] + [f"g{k}" for k in range(n + 1)]
    glyf.glyphs = {".notdef": _square(), "g0": _square()}
    for k in range(1, n + 1):
        pen = TTGlyphPen(glyf)
        pen.addComponent(f"g{k - 1}", (1, 0, 0, 1, 0, 0))
        pen.addComponent(f"g{k - 1}", (1, 0, 0, 1, 0, 0))
        glyf.glyphs[f"g{k}"] = pen.glyph()
    return glyf


class BoundedGlyphSet(dict):
    """glyfTable stand-in that bounds the number of glyph lookups."""

    budget = 1000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lookups = 0

    def __getitem__(self, name):
        self.lookups += 1
        # Count-based guard: independent of machine/load timing.
        assert self.lookups <= self.budget, "excessive component traversal"
        return super().__getitem__(name)


@pytest.mark.parametrize("method", ["getCompositeMaxpValues", "recalcBounds"])
def test_depth12_dag_default_call_is_memoized(method):
    glyf = BoundedGlyphSet(build_composite_dag(12).glyphs)
    glyph = glyf["g12"]  # one lookup, as a caller would do
    getattr(glyph, method)(glyf)
    # 1 top fetch + at most two component lookups per unique g1..g12 node
    assert glyf.lookups < 1000


def test_depth12_dag_results_unchanged():
    glyf = build_composite_dag(12)
    assert tuple(glyf["g12"].getCompositeMaxpValues(glyf)) == (16384, 4096, 12)
    glyf["g12"].recalcBounds(glyf)
    assert (glyf["g12"].xMin, glyf["g12"].yMin, glyf["g12"].xMax, glyf["g12"].yMax) == (
        0,
        0,
        10,
        10,
    )


def test_explicit_shared_cache_matches_default_across_depths_and_orders():
    glyf = build_composite_dag(12)
    composites = [n for n in glyf.glyphOrder if glyf[n].isComposite()]
    for depth in (1, 2, 3, 5):
        expected = {
            n: tuple(glyf[n].getCompositeMaxpValues(glyf, depth)) for n in composites
        }
        for order in (composites, composites[::-1]):
            cache = {}
            for n in order:
                got = tuple(
                    glyf[n].getCompositeMaxpValues(glyf, depth, maxpValuesCache=cache)
                )
                assert got == expected[n]


def test_cache_does_not_leak_between_unrelated_fonts():
    first = build_composite_dag(5)
    second = build_composite_dag(5)
    # Give the second font a differently-sized leaf.
    wide = _square()
    wide.coordinates = type(wide.coordinates)(
        [(-50, -50), (-50, 50), (50, 50), (50, -50)]
    )
    second.glyphs["g0"] = wide

    first["g5"].recalcBounds(first)
    second["g5"].recalcBounds(second)
    assert (first["g5"].xMin, first["g5"].xMax) == (0, 10)
    assert (second["g5"].xMin, second["g5"].xMax) == (-50, 50)

    # maxp point *counts* are independent too.
    assert tuple(first["g5"].getCompositeMaxpValues(first))[:2] == (128, 32)


def test_modified_glyph_is_recomputed_with_default_call_scoped_cache():
    glyf = build_composite_dag(2)
    assert tuple(glyf["g2"].getCompositeMaxpValues(glyf))[:2] == (16, 4)

    # Replace the leaf with a triangle (3 points, 1 contour).
    leaf = glyf["g0"]
    leaf.coordinates = type(leaf.coordinates)([(0, 0), (1, 0), (0, 1)])
    leaf.endPtsOfContours = [2]
    assert tuple(glyf["g2"].getCompositeMaxpValues(glyf))[:2] == (12, 4)

    # Bounds likewise recompute after the leaf outline changes.
    glyf = build_composite_dag(1)
    glyf["g1"].recalcBounds(glyf)
    assert (glyf["g1"].xMin, glyf["g1"].xMax) == (0, 10)
    wide = _square()
    wide.coordinates = type(wide.coordinates)(
        [(-50, -50), (-50, 50), (50, 50), (50, -50)]
    )
    glyf.glyphs["g0"] = wide
    glyf["g1"].recalcBounds(glyf)
    assert (glyf["g1"].xMin, glyf["g1"].xMax) == (-50, 50)


def test_recursive_components_still_raise_ttLibError():
    from fontTools.ttLib.tables._g_l_y_f import GlyphComponent

    glyf = newTable("glyf")
    glyf.glyphOrder = ["A"]
    a = Glyph()
    a.numberOfContours = -1
    c = GlyphComponent()
    c.glyphName = "A"
    c.flags = 0x2  # ARGS_ARE_XY_VALUES
    c.x = c.y = 5
    a.components = [c]
    glyf.glyphs = {"A": a}
    with pytest.raises(TTLibError, match="recursive component reference"):
        a.recalcBounds(glyf)
    with pytest.raises(TTLibError, match="recursive component reference"):
        a.recalcBounds(glyf, boundsDone=set())


def test_non_translate_transform_bounds_still_correct_with_reuse():
    glyf = newTable("glyf")
    glyf.glyphOrder = ["sq", "scaled_twice", "root"]
    glyf.glyphs = {"sq": _square()}

    pen = TTGlyphPen(glyf)
    pen.addComponent("sq", (2, 0, 0, 2, 0, 0))
    pen.addComponent("sq", (2, 0, 0, 2, 100, 0))
    glyf.glyphs["scaled_twice"] = pen.glyph()

    pen = TTGlyphPen(glyf)
    pen.addComponent("scaled_twice", (1, 0, 0, 1, 0, 0))
    glyf.glyphs["root"] = pen.glyph()

    root = glyf["root"]
    # The composite must not be eligible for the integer-translate fast path.
    assert not all(
        c._hasOnlyIntegerTranslate() for c in glyf["scaled_twice"].components
    )
    root.recalcBounds(glyf)
    # Two scaled squares: [0,20] and translated-by-100 then scaled -> [100,120]
    assert (root.xMin, root.yMin, root.xMax, root.yMax) == (0, 0, 120, 20)

    # And it agrees with the flattened-coordinate bounds (slow path).
    coords, _end, _flags = root.getCoordinates(glyf, round=otRound)
    assert coords.calcIntBounds() == (root.xMin, root.yMin, root.xMax, root.yMax)


def test_dag_beyond_composite_point_limit_raises():
    glyf = build_composite_dag(14)  # 4 * 2**14 == 65536 flattened points
    with pytest.raises(TTLibError, match="more than 65535 points"):
        glyf["g14"].getCoordinates(glyf)


REAL_FONTS = [
    "Tests/ttx/data/TestTTF.ttf",
    "Tests/qu2cu/data/NotoSansArabic-Regular.quadratic.subset.ttf",
    "Tests/subset/data/BungeeColor-Regular.ttx",
    "Tests/varLib/data/MutatorSans_All_Variable.ttx",
    "Tests/varLib/instancer/data/PartialInstancerTest3-VF.ttx",
]


@pytest.mark.parametrize("rel_path", REAL_FONTS)
def test_real_font_cached_maxp_matches_default(rel_path):
    path = REPO_ROOT / rel_path
    if not path.exists():
        pytest.skip(f"{rel_path} not available")
    if path.suffix == ".ttx":
        font = TTFont()
        font.importXML(str(path))
    else:
        font = TTFont(str(path))
    try:
        glyf = font["glyf"]
    except KeyError:
        pytest.skip(f"{rel_path} has no glyf table")

    composites = [n for n in glyf.glyphOrder if glyf[n].isComposite()]
    assert composites, f"{rel_path} unexpectedly has no composite glyphs"

    for depth in (1, 3):
        expected = {
            n: tuple(glyf[n].getCompositeMaxpValues(glyf, depth)) for n in composites
        }
        cache = {}
        for n in composites[::-1]:
            assert (
                tuple(
                    glyf[n].getCompositeMaxpValues(
                        glyf, depth, maxpValuesCache=cache
                    )
                )
                == expected[n]
            )

    # End-to-end maxp recalculation is stable and glyf compiles.
    font["maxp"].recalc(font)
    profile = (
        font["maxp"].maxCompositePoints,
        font["maxp"].maxCompositeContours,
        font["maxp"].maxComponentDepth,
    )
    font["maxp"].recalc(font)
    again = (
        font["maxp"].maxCompositePoints,
        font["maxp"].maxCompositeContours,
        font["maxp"].maxComponentDepth,
    )
    assert profile == again
    font["glyf"].compile(font)
    font.close()
