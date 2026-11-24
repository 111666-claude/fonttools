#!/usr/bin/env python3
"""Count-based benchmark / regression for shared composite subgraph traversal.

Composite glyphs that reuse the same component many times (e.g. a binary DAG of
depth *n* where every level references the previous one twice) used to be
walked exponentially: a depth-12 sample performed ``2**13 - 1 == 8191`` glyph
lookups for a single default ``getCompositeMaxpValues()`` or
``recalcBounds()`` call. The per-call memoization cuts that to a few dozen
without changing any computed value.

Wall-clock timings are included but are deliberately secondary: the primary
signal is the number of ``glyfTable[glyphName]`` lookups, which is
deterministic. The script also runs a real-font regression comparing cached
vs. uncached ``maxp``/bounding-box results.

Run directly with a Python that has fontTools' runtime deps available::

    python benchmarks/composite_dag_benchmark.py
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Always test this checkout's Lib/ even if another fontTools is installed
# editable in the ambient interpreter.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "Lib"))

from fontTools.fontBuilder import FontBuilder  # noqa: E402
from fontTools.pens.ttGlyphPen import TTGlyphPen  # noqa: E402
from fontTools.ttLib import TTFont, newTable  # noqa: E402


LOOKUP_BUDGET = 1000
SAMPLE_DEPTH = 12


class CountingGlyphSet(dict):
    """Stand-in for a glyf table that counts ``__getitem__`` lookups."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lookups = 0

    def __getitem__(self, name):
        self.lookups += 1
        return super().__getitem__(name)


def square_glyph():
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((0, 10))
    pen.lineTo((10, 10))
    pen.lineTo((10, 0))
    pen.closePath()
    return pen.glyph()


def build_composite_dag(n):
    """g{k} references g{k-1} twice; g0 is a 4-point square.

    g{k} therefore flattens to ``4 * 2**k`` points and ``2**k`` contours.
    """
    glyf = newTable("glyf")
    glyf.glyphOrder = [".notdef"] + [f"g{k}" for k in range(n + 1)]
    glyf.glyphs = {".notdef": square_glyph(), "g0": square_glyph()}
    for k in range(1, n + 1):
        pen = TTGlyphPen(glyf)
        pen.addComponent(f"g{k - 1}", (1, 0, 0, 1, 0, 0))
        pen.addComponent(f"g{k - 1}", (1, 0, 0, 1, 0, 0))
        glyf.glyphs[f"g{k}"] = pen.glyph()
    return glyf


def measure_lookup_counts():
    print(f"== lookup counts on depth-{SAMPLE_DEPTH} binary-reuse DAG ==")
    naive = 2 ** (SAMPLE_DEPTH + 1) - 1
    print(f"uncached traversal would perform {naive} lookups")
    failures = []

    expected_maxp = (4 * 2**SAMPLE_DEPTH, 2**SAMPLE_DEPTH, SAMPLE_DEPTH)

    # --- maxp path, single default call ---
    gs = CountingGlyphSet(build_composite_dag(SAMPLE_DEPTH).glyphs)
    top = gs[f"g{SAMPLE_DEPTH}"]
    gs.lookups = 0  # only count the traversal itself
    result = top.getCompositeMaxpValues(gs)
    status = "OK " if gs.lookups < LOOKUP_BUDGET else "FAIL"
    print(
        f"[{status}] getCompositeMaxpValues: {gs.lookups:5d} lookups "
        f"(budget < {LOOKUP_BUDGET}), result={tuple(result)}"
    )
    if gs.lookups >= LOOKUP_BUDGET:
        failures.append("maxp lookup budget exceeded")
    if tuple(result) != expected_maxp:
        failures.append(f"maxp result changed: {tuple(result)} != {expected_maxp}")

    # --- bounds path, single default call ---
    gs = CountingGlyphSet(build_composite_dag(SAMPLE_DEPTH).glyphs)
    top = gs[f"g{SAMPLE_DEPTH}"]
    gs.lookups = 0
    top.recalcBounds(gs)
    bounds = (top.xMin, top.yMin, top.xMax, top.yMax)
    status = "OK " if gs.lookups < LOOKUP_BUDGET else "FAIL"
    print(
        f"[{status}] recalcBounds:            {gs.lookups:5d} lookups "
        f"(budget < {LOOKUP_BUDGET}), bounds={bounds}"
    )
    if gs.lookups >= LOOKUP_BUDGET:
        failures.append("bounds lookup budget exceeded")
    if bounds != (0, 0, 10, 10):
        failures.append(f"bounds changed: {bounds} != (0, 0, 10, 10)")

    # --- explicit shared cache across many top-level glyphs ---
    glyf = build_composite_dag(SAMPLE_DEPTH)
    shared = {}
    for name in glyf.glyphOrder:
        g = glyf[name]
        if g.isComposite():
            g.getCompositeMaxpValues(glyf, maxpValuesCache=shared)
    print(f"[OK ] shared maxpValuesCache holds {len(shared)} unique glyph entries")

    return failures


def time_calls(depth, repeats):
    print(f"\n== timing at depth {depth} ({repeats} repeats, best) ==")

    def best(fn):
        best_t = float("inf")
        for _ in range(repeats):
            t0 = time.perf_counter()
            fn()
            best_t = min(best_t, time.perf_counter() - t0)
        return best_t

    glyf = build_composite_dag(depth)
    top_name = f"g{depth}"
    t_maxp = best(lambda: glyf[top_name].getCompositeMaxpValues(glyf))
    print(f"getCompositeMaxpValues g{depth}: {t_maxp * 1000:9.3f} ms/call")

    glyf = build_composite_dag(depth)
    t_bounds = best(lambda: glyf[top_name].recalcBounds(glyf))
    print(f"recalcBounds             g{depth}: {t_bounds * 1000:9.3f} ms/call")


REAL_FONTS = [
    "Tests/ttx/data/TestTTF.ttf",
    "Tests/qu2cu/data/NotoSansArabic-Regular.quadratic.subset.ttf",
    "Tests/subset/data/BungeeColor-Regular.ttx",
    "Tests/varLib/data/MutatorSans_All_Variable.ttx",
    "Tests/varLib/instancer/data/PartialInstancerTest3-VF.ttx",
]


def load_font(rel_path):
    path = REPO_ROOT / rel_path
    if not path.exists():
        return None
    if path.suffix == ".ttx":
        font = TTFont()
        font.importXML(str(path))
        return font
    return TTFont(str(path))


def real_font_regression():
    print("\n== real-font cached-vs-uncached regression ==")
    failures = []
    checked = 0
    for rel in REAL_FONTS:
        font = load_font(rel)
        if font is None:
            print(f"[SKIP] {rel} (not found)")
            continue
        glyf = font["glyf"]
        composites = [n for n in glyf.glyphOrder if glyf[n].isComposite()]
        if not composites:
            print(f"[SKIP] {rel} (no composite glyphs)")
            continue

        for depth in (1, 3):
            expected = {
                n: tuple(glyf[n].getCompositeMaxpValues(glyf, depth))
                for n in composites
            }
            for order in (composites, composites[::-1]):
                cache = {}
                for n in order:
                    got = tuple(
                        glyf[n].getCompositeMaxpValues(
                            glyf, depth, maxpValuesCache=cache
                        )
                    )
                    if got != expected[n]:
                        failures.append(f"{rel}: {n} depth={depth}: {got} != {expected[n]}")

        # End-to-end maxp recalc + glyf compile must succeed and stay stable.
        maxp = font["maxp"]
        maxp.recalc(font)
        first = (
            maxp.maxCompositePoints,
            maxp.maxCompositeContours,
            maxp.maxComponentDepth,
        )
        maxp.recalc(font)
        second = (
            maxp.maxCompositePoints,
            maxp.maxCompositeContours,
            maxp.maxComponentDepth,
        )
        if first != second:
            failures.append(f"{rel}: maxp.recalc not stable {first} vs {second}")
        font["glyf"].compile(font)

        checked += 1
        print(f"[OK ] {rel} ({len(composites)} composites, maxp={first})")
        font.close()

    print(f"real fonts checked: {checked}")
    return failures


def isolation_checks():
    print("\n== cache isolation / mutation checks ==")
    failures = []

    # Two unrelated glyf tables sharing glyph names but different geometry
    # must not influence each other (caches are call-scoped, never global).
    g_a = build_composite_dag(4)
    g_b = build_composite_dag(4)
    # Perturb every leaf of font B by rebuilding its g0 as a bigger square.
    big = square_glyph()
    big.coordinates = type(big.coordinates)(
        [(x * 3, y * 3) for x, y in big.coordinates]
    )
    big.xMin, big.yMin, big.xMax, big.yMax = 0, 0, 30, 30
    g_b.glyphs["g0"] = big

    ra = tuple(g_a["g4"].getCompositeMaxpValues(g_a))
    rb = tuple(g_b["g4"].getCompositeMaxpValues(g_b))
    if ra != (64, 16, 4):
        failures.append(f"unexpected A maxp {ra}")
    if rb[0] != 64:  # point *count* unchanged by scaling, geometry differs in bounds
        failures.append(f"unexpected B maxp {rb}")
    g_b["g4"].recalcBounds(g_b)
    if (g_b["g4"].xMax, g_b["g4"].yMax) != (30, 30):
        failures.append(
            f"font B bounds leaked/wrong: "
            f"{(g_b['g4'].xMin, g_b['g4'].yMin, g_b['g4'].xMax, g_b['g4'].yMax)}"
        )
    g_a["g4"].recalcBounds(g_a)
    if (g_a["g4"].xMax, g_a["g4"].yMax) != (10, 10):
        failures.append("font A bounds contaminated by font B")
    print("[OK ] unrelated fonts do not share cached state")

    # Mutating a glyph must be observed by the next default call because no
    # cache is persisted on the glyph/table.
    glyf = build_composite_dag(2)
    before = tuple(glyf["g2"].getCompositeMaxpValues(glyf))
    leaf = glyf["g0"]
    leaf.coordinates = type(leaf.coordinates)([(0, 0), (1, 0), (0, 1)])
    leaf.endPtsOfContours = [2]
    after = tuple(glyf["g2"].getCompositeMaxpValues(glyf))
    if before == after or after[0] != 12:  # 3 pts * 2**2 leaves
        failures.append(f"mutation not observed: before={before} after={after}")
    else:
        print(f"[OK ] modified glyph picked up on next call: {before} -> {after}")

    # A fresh default bounds call must recompute after the base outline changes.
    glyf = build_composite_dag(1)
    glyf["g1"].recalcBounds(glyf)
    assert (glyf["g1"].xMin, glyf["g1"].xMax) == (0, 10)
    wide = square_glyph()
    wide.coordinates = type(wide.coordinates)(
        [(-50, -50), (-50, 50), (50, 50), (50, -50)]
    )
    glyf.glyphs["g0"] = wide
    glyf["g1"].recalcBounds(glyf)
    if (glyf["g1"].xMin, glyf["g1"].xMax) != (-50, 50):
        failures.append("bounds cache leaked across a glyph modification")
    else:
        print("[OK ] bounds recomputed after base glyph modification")

    return failures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--depth", type=int, default=18, help="timing DAG depth")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--no-timing", action="store_true")
    args = parser.parse_args()

    failures = []
    failures += measure_lookup_counts()
    failures += isolation_checks()
    failures += real_font_regression()
    if not args.no_timing:
        time_calls(args.depth, args.repeats)

    print()
    if failures:
        print("BENCHMARK/REGRESSION FAILED:")
        for f in failures:
            print(" -", f)
        return 1
    print("ALL COUNT BUDGETS AND REGRESSION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
