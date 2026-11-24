"""Pointwise correctness comparison for the pinned-instance fast path.

Runs unchanged against old and new code (select via PYTHONPATH). Writes a JSON
snapshot covering:

  1. fractional deltas / fractional pin scalars
  2. sparse IUP tuples (mixed None/explicit points)
  3. composite glyphs (the test TTX contains a composite glyph)
  4. phantom points (advance width / sidebearing metrics)
  5. length-mismatch error behavior (gvar and cvar)
  6. cvar width-1 tuples with None values
"""
import json
import os
import sys

sys.path.insert(0, "/home/real666/feedback/uid41/Lib")

from fontTools import ttLib
from fontTools.ttLib.tables.TupleVariation import TupleVariation
from fontTools.ttLib.tables import _g_l_y_f
from fontTools.varLib import instancer
from fontTools.varLib.instancer import (
    NormalizedAxisLimits,
    NormalizedAxisTripleAndDistances,
    instantiateTupleVariationStore,
)

TESTDATA = "/home/real666/feedback/uid41/Tests/varLib/instancer/data"


def limits(pins):
    return NormalizedAxisLimits(
        {
            tag: NormalizedAxisTripleAndDistances(v, v, v)
            for tag, v in pins.items()
        }
    )


def snapshot_font(font):
    glyf = font["glyf"]
    out = {}
    for name in glyf.glyphOrder:
        g = glyf[name]
        entry = {"numberOfContours": g.numberOfContours}
        if g.isComposite():
            entry["components"] = [
                (c.glyphName, getattr(c, "x", 0), getattr(c, "y", 0), c.flags)
                for c in g.components
            ]
        if g.numberOfContours != 0:
            coords, ctrl = glyf._getCoordinatesAndControls(
                name, font["hmtx"].metrics,
                getattr(font.get("vmtx"), "metrics", None),
            )
            entry["coordinates"] = [tuple(p) for p in coords]
            entry["endPts"] = list(ctrl.endPts)
            entry["bounds"] = [g.xMin, g.yMin, g.xMax, g.yMax]
        entry["hmtx"] = font["hmtx"].metrics.get(name)
        out[name] = entry
    out["__gvar_keys__"] = sorted(font.get("gvar", {}).variations)
    return out


def font_snapshots():
    """Full instantiation of the real test font (simple + composite glyphs)."""
    results = {}
    for ttx, pins in (
        ("PartialInstancerTest-VF.ttx", {"wght": 0.3, "wdth": -0.7}),
        # second location, including fractional scalars away from peaks
        ("PartialInstancerTest-VF.ttx", {"wght": 0.625, "wdth": 0.25}),
        ("PartialInstancerTest2-VF.ttx", {"wght": 0.5, "wdth": -0.5}),
    ):
        f = ttLib.TTFont()
        f.importXML(os.path.join(TESTDATA, ttx))
        instancer.instantiateVariableFont(f, pins)
        results[f"{ttx}:{pins}"] = snapshot_font(f)
    return results


def synthetic_fractional_and_sparse():
    """Direct API: fractional scalars, sparse IUP, phantom points, zero impact."""
    n = 8  # 4 outline points + 4 phantom points
    orig = _g_l_y_f.GlyphCoordinates(
        [(float(i), float(2 * i + 1)) for i in range(n)]
    )
    end_pts = [3]

    dense = TupleVariation(
        {"wght": (0.0, 0.5, 1.0)},
        [(0.5 * i + 0.25, -0.25 * i + 0.75) for i in range(n)],
    )
    sparse = TupleVariation(
        {"wdth": (-1.0, -0.5, 0.0)},
        [
            None,
            None,
            (10.5, -20.25),
            None,
            (-7.75, 3.5),  # phantom point delta
            None,
            None,
            (1.125, -2.625),
        ],
    )
    no_impact = TupleVariation(
        {"wght": (0.0, 0.9, 1.0)},
        [(100.0, 100.0) for _ in range(n)],
    )
    variations = [dense, sparse, no_impact]
    deltas = instantiateTupleVariationStore(
        variations, limits({"wght": 0.3, "wdth": -0.7}), orig, end_pts
    )
    return {"deltas": deltas, "store_cleared": list(variations)}


def error_behavior():
    results = {}

    # gvar sparse tuple length mismatch
    var = TupleVariation(
        {"wght": (0.0, 0.5, 1.0)},
        [None, (1.0, 2.0), None, (3.0, 4.0)],
    )
    orig = _g_l_y_f.GlyphCoordinates([(0.0, 0.0), (1.0, 1.0)])
    try:
        instantiateTupleVariationStore([var], limits({"wght": 0.3}), orig, [1])
        results["gvar_length_mismatch"] = "NO ERROR"
    except ValueError as e:
        results["gvar_length_mismatch"] = str(e)

    # cvar tuples with different lengths cannot be summed
    v1 = TupleVariation({"wght": (0.0, 0.5, 1.0)}, [1.0, 2.0, 3.0])
    v2 = TupleVariation({"wght": (0.0, 1.0, 1.0)}, [4.0, 5.0])
    try:
        instantiateTupleVariationStore([v1, v2], limits({"wght": 0.3}))
        results["cvar_length_mismatch"] = "NO ERROR"
    except ValueError as e:
        results["cvar_length_mismatch"] = str(e)

    return results


def cvar_none_behavior():
    v1 = TupleVariation({"wght": (0.0, 0.5, 1.0)}, [1.5, None, 3.0, None])
    v2 = TupleVariation({"wdth": (-1.0, -0.5, 0.0)}, [None, 2.25, None, -1.125])
    variations = [v1, v2]
    deltas = instantiateTupleVariationStore(
        variations, limits({"wght": 0.3, "wdth": -0.7})
    )
    return {"deltas": deltas, "store_cleared": list(variations)}


def main():
    out_path = sys.argv[1]
    payload = {
        "fonts": font_snapshots(),
        "synthetic": synthetic_fractional_and_sparse(),
        "errors": error_behavior(),
        "cvar": cvar_none_behavior(),
    }
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2, sort_keys=True, default=float)
    print("wrote", out_path)


if __name__ == "__main__":
    main()
