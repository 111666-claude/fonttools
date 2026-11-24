# IUP equivalence regression corpus

Machine-readable cases for `Tests/varLib/iup_equivalence.py` and
`Tests/varLib/iup_equivalence_test.py`.

The checker compares the **full delta vector** against the deltas
reconstructed from the **IUP-sparse representation** at four levels:

1. `float_delta` — original deltas vs interpolated deltas before rounding;
2. `float_position` — same comparison on fractional point positions;
3. `rounded_delta` — after OpenType-rounding coordinates and retained deltas
   (`otRound = floor(v + 0.5)`, ties towards positive infinity), re-running
   IUP on the integer arrays;
4. `position_round` / `rounded_position` — final glyph grid positions from
   the direct and serialized rounding pipelines.

Exact positive/negative half-value boundaries (`k + 0.5`) are recorded
separately. Note the asymmetric tie rule: `otRound(+0.5) == 1` but
`otRound(-0.5) == 0` (and `otRound(-1.5) == -1`).

## Running

```sh
# everything (CLI corpus report + pytest suite), headless
Tests/varLib/run_iup_equivalence.sh

# CLI only, emit a machine report too
PYTHONPATH=Lib python3 Tests/varLib/iup_equivalence.py \
    Tests/varLib/data/iup_equivalence/cases.json \
    --json /tmp/iup-report.json

# pytest only
python3 -m pytest Tests/varLib/iup_equivalence_test.py -v
```

A root `conftest.py` front-loads this checkout's `Lib`, so plain `pytest`
also tests this tree even if another worktree is registered as an editable
install.

## Case schema

```jsonc
{
  "id": "unique id",
  "axis_location": {"wght": 650},   // reported on every violation
  "tolerance": 0.0,                  // optimizer / float-stage tolerance
  "rounded_tolerance": 0.0,          // strict rounded-pipeline threshold
  "expect": "clean",                 // or "alarm"
  "must_include": [ ... ],           // predicates an alarm report must match
  "contours": [
    {
      "closed": true,                // circular IUP vs open polyline
      "coords": [[x, y], ...],
      "deltas": [[dx, dy], ...],
      "sparse": [[dx, dy], null, ...] // optional frozen/baseline encoding
    }
  ]
}
```

`must_include` predicates may match any `Violation` field (`stage`,
`contour`, `point`, `component`, ...) and support `deviation`,
`deviation_atol`, `deviation_min`, `deviation_max`.

## Corpus contents

* **clean normal samples** — linear, uniform, diamond and two real glyph
  contours already used by `Tests/varLib/iup_test.py`, fractional
  rounding-stable cases, and open polylines;
* **no-optimizable-points** — `dense-all-forced-3pt` (forced set
  `{0,1,2}`, optimizer retains every delta) and all-explicit/all-zero
  inputs;
* **half boundaries** — positive and negative `k + 0.5` probes, including
  the non-alarming `-0.5` tie;
* **old-baseline counterexamples** — frozen pre-fix sparse encodings from:
  * [fonttools#3636](https://github.com/fonttools/fonttools/issues/3636) /
    [#3634](https://github.com/fonttools/fonttools/issues/3634) fractional
    rounding cases and the
    [#4382](https://github.com/fonttools/fonttools/pull/4382) four-point
    rotations and `+0.5` zero-fast-path cases;
  * [fonttools#3703](https://github.com/fonttools/fonttools/issues/3703)
    tolerance-boundary case in both its pure-Python and old Cython
    baseline encodings;
* **controlled errors** — hand-mutated anchor encodings and 0.01
  boundary-cross perturbations that flip a rounded grid point, proving the
  checker alarms with axis/contour/point/deviation details.

The historical `axis_location` values are representative variation-tuple
positions where the upstream record does not preserve the exact tuple;
they exist so reports demonstrate axis-location attribution.
