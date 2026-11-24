"""Property check: full-pin fast path math == old rebase pipeline output.

Compares the accumulated default delta produced by the current
instantiateTupleVariationStore() against direct supportScalar()-based
accumulation, over random tents/pins in 1-3 axes, for both gvar-style
(x,y incl. phantom points) and cvar-style (scalar, None) coordinates.
"""
import random
import sys

sys.path.insert(0, "/home/real666/feedback/uid41/Lib")

from fontTools.varLib.models import supportScalar
from fontTools.varLib.instancer import (
    NormalizedAxisLimits,
    NormalizedAxisTripleAndDistances,
    instantiateTupleVariationStore,
)
from fontTools.ttLib.tables.TupleVariation import TupleVariation

AXIS_TAGS = ["wght", "wdth", "opsz"]


def random_tent(rng):
    peak = rng.choice([-1, 1]) * rng.uniform(0.1, 1.0)
    if peak > 0:
        return (0.0, peak, rng.uniform(peak, min(2.0, peak + 1.0)))
    return (rng.uniform(max(-2.0, peak - 1.0), peak), peak, 0.0)


def clone(variations):
    return [TupleVariation(v.axes, list(v.coordinates)) for v in variations]


def main():
    rng = random.Random(41)
    failures = 0
    checked = 0
    for trial in range(5000):
        n_axes = rng.randint(1, 3)
        tags = rng.sample(AXIS_TAGS, n_axes)
        n_vars = rng.randint(1, 6)
        n_points = rng.randint(1, 12)
        width2 = rng.random() < 0.7
        vec_len = n_points + 4 if width2 else n_points

        limits = {}
        location = {}
        for tag in tags:
            pin = rng.uniform(-1.0, 1.0)
            location[tag] = pin
            limits[tag] = NormalizedAxisTripleAndDistances(pin, pin, pin)
        axis_limits = NormalizedAxisLimits(limits)

        variations = []
        for v in range(n_vars):
            axes = {
                tag: random_tent(rng)
                for tag in rng.sample(tags, rng.randint(1, n_axes))
            }
            if width2:
                coords = [
                    None
                    if rng.random() < 0.3
                    else (rng.uniform(-50, 50), rng.uniform(-50, 50))
                    for _ in range(vec_len)
                ]
            else:
                coords = [
                    None if rng.random() < 0.3 else rng.uniform(-50, 50)
                    for _ in range(vec_len)
                ]
            variations.append(TupleVariation(axes, coords))

        if width2:
            glyf_coords = [(float(i), float(i + 1)) for i in range(vec_len)]
            end_pts = [n_points - 1]
            ref = instantiateTupleVariationStore(
                clone(variations), axis_limits, glyf_coords, end_pts
            )
            acc = None
            for fv in clone(variations):
                s = supportScalar(location, fv.axes)
                if s == 0.0:
                    continue
                fv.calcInferredDeltas(glyf_coords, end_pts)
                if acc is None:
                    acc = [
                        None if d is None else (d[0] * s, d[1] * s)
                        for d in fv.coordinates
                    ]
                else:
                    for i, d in enumerate(fv.coordinates):
                        a = acc[i]
                        acc[i] = (a[0] + d[0] * s, a[1] + d[1] * s)
            fast = acc if acc is not None else []
        else:
            ref = instantiateTupleVariationStore(clone(variations), axis_limits)
            acc = None
            for vv in clone(variations):
                s = supportScalar(location, vv.axes)
                if s == 0.0:
                    continue
                if acc is None:
                    acc = [None if d is None else d * s for d in vv.coordinates]
                else:
                    for i, d in enumerate(vv.coordinates):
                        if d is None:
                            continue
                        acc[i] = s * d if acc[i] is None else acc[i] + s * d
            fast = acc if acc is not None else []

        checked += 1
        if len(ref) != len(fast):
            failures += 1
            print("LEN MISMATCH", trial, len(ref), len(fast))
            continue
        bad = False
        for a, b in zip(ref, fast):
            if a is None or b is None:
                if a != b:
                    bad = True
                    break
            elif width2:
                if abs(a[0] - b[0]) > 1e-9 or abs(a[1] - b[1]) > 1e-9:
                    bad = True
                    break
            else:
                if abs(a - b) > 1e-9:
                    bad = True
                    break
        if bad:
            failures += 1
            if failures <= 5:
                print("MISMATCH trial", trial, "\n ref ", ref, "\n fast", fast)
    print(f"checked={checked} failures={failures}")


if __name__ == "__main__":
    main()
