"""Tight-tolerance numeric comparison: old pipeline vs fast path, many tuples.

Builds gvar stores with many overlapping tuples (up to 30), fractional deltas
and random pins, and compares the fast path against a faithful emulation of
the OLD rebasing+merge pipeline using the public supportScalar math.
"""
import random
import sys

sys.path.insert(0, "/home/real666/feedback/uid41/Lib")

from fontTools.varLib.iup import iup_delta
from fontTools.varLib.models import supportScalar
from fontTools.ttLib.tables.TupleVariation import TupleVariation
from fontTools.varLib.instancer import (
    NormalizedAxisLimits,
    NormalizedAxisTripleAndDistances,
    instantiateTupleVariationStore,
)

AXIS_TAGS = ["wght", "wdth", "opsz"]


def random_tent(rng):
    peak = rng.choice([-1, 1]) * rng.uniform(0.1, 1.0)
    if peak > 0:
        return (0.0, peak, rng.uniform(peak, min(2.0, peak + 1.0)))
    return (rng.uniform(max(-2.0, peak - 1.0), peak), peak, 0.0)


def old_emulation(variations, location, glyf_coords, end_pts):
    """Faithful emulation of the pre-change pipeline for the full-pin case."""
    # Step 1: per-tuple IUP inference (the old code inferred before merging)
    inferred = []
    for var in variations:
        s = supportScalar(location, var.axes)
        if s == 0.0:
            continue
        coords = var.coordinates
        if None in coords:
            coords = iup_delta(coords, glyf_coords, end_pts)
        # old code rescaled each tuple (scaleDeltas) then merged (__iadd__)
        scaled = [(d[0] * s, d[1] * s) for d in coords]
        inferred.append(scaled)
    if not inferred:
        return []
    # old merge: element-wise addition in tuple encounter order
    acc = list(inferred[0])
    for vec in inferred[1:]:
        for i, d in enumerate(vec):
            a = acc[i]
            acc[i] = (a[0] + d[0], a[1] + d[1])
    return acc


def main():
    rng = random.Random(99)
    worst = 0.0
    failures = 0
    for trial in range(3000):
        n_axes = rng.randint(1, 3)
        tags = rng.sample(AXIS_TAGS, n_axes)
        n_vars = rng.randint(5, 30)
        n_outline = rng.randint(4, 20)
        vec_len = n_outline + 4
        location = {tag: rng.uniform(-1.0, 1.0) for tag in tags}
        limits = NormalizedAxisLimits(
            {
                t: NormalizedAxisTripleAndDistances(v, v, v)
                for t, v in location.items()
            }
        )
        glyf_coords = [
            (rng.uniform(0, 500), rng.uniform(0, 700)) for _ in range(vec_len)
        ]
        end_pts = [n_outline - 1]

        variations = []
        for _ in range(n_vars):
            axes = {
                tag: random_tent(rng)
                for tag in rng.sample(tags, rng.randint(1, n_axes))
            }
            sparse = rng.random() < 0.5
            if sparse:
                coords = [
                    None
                    if rng.random() < 0.4
                    else (rng.uniform(-40, 40), rng.uniform(-40, 40))
                    for _ in range(vec_len)
                ]
                coords[rng.randrange(vec_len)] = (1.0, 1.0)
            else:
                coords = [
                    (rng.uniform(-40, 40), rng.uniform(-40, 40))
                    for _ in range(vec_len)
                ]
            variations.append(TupleVariation(axes, coords))

        ref = old_emulation(
            [TupleVariation(v.axes, list(v.coordinates)) for v in variations],
            location, glyf_coords, end_pts,
        )
        fast = instantiateTupleVariationStore(
            [TupleVariation(v.axes, list(v.coordinates)) for v in variations],
            limits, glyf_coords, end_pts,
        )

        if len(ref) != len(fast):
            failures += 1
            print("LEN", trial)
            continue
        for a, b in zip(ref, fast):
            err = max(abs(a[0] - b[0]), abs(a[1] - b[1]))
            worst = max(worst, err)
            # values reach ~1000; require relative agreement to ~1e-12
            scale = max(1.0, abs(a[0]), abs(a[1]))
            if err / scale > 1e-12:
                failures += 1
                if failures <= 5:
                    print("MISMATCH", trial, a, b, err)
                break
    print(f"trials=3000 failures={failures} worst_abs_error={worst:.3e}")


if __name__ == "__main__":
    main()
