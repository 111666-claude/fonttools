"""Equivalence oracle and diagnostics for IUP sparse-delta optimization.

The IUP optimizer (:func:`fontTools.varLib.iup.iup_delta_optimize`) drops
deltas that can allegedly be reconstructed by interpolation.  Two failure
modes are easy to miss with plain ``assert`` statements:

* fractional coordinates/deltas make the reconstructed value differ slightly
  from the original (or sit exactly on an OpenType rounding boundary);
* after deltas *and* coordinates are rounded to integers for serialization,
  the interpolation fraction can change, so the inferred delta no longer
  matches the rounded full delta -- even when the pre-rounding check passed.

This module compares, for every point of every contour:

1. the original full deltas against the deltas reconstructed from the
   optimized sparse representation (pre-rounding float equivalence);
2. the resulting point positions before rounding;
3. the serialized pipeline: OpenType-round the coordinates and the retained
   deltas, re-run IUP, and compare against the rounded full deltas;
4. the final grid positions after OpenType rounding;
5. positive/negative half-value (``k + 0.5``) rounding boundaries.

Every discrepancy is reported as a structured :class:`Violation` carrying
the axis location, contour number, closed/open flag, point index, the
interpolating anchor span and the deviation.  The module is pure Python and
needs no font rendering device.

Run the regression corpus directly::

    python3 Tests/varLib/iup_equivalence.py Tests/varLib/data/iup_equivalence/cases.json

or through pytest::

    PYTHONPATH=Lib python3 -m pytest Tests/varLib/iup_equivalence_test.py -v
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Allow running this file directly from a source checkout without an editable
# install pointing at another worktree.  When imported by pytest, fontTools is
# already importable and this simply leaves sys.path alone.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_LIB = os.path.join(_REPO_ROOT, "Lib")
if os.path.isdir(_LIB) and _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from fontTools.misc.roundTools import otRound  # noqa: E402
from fontTools.varLib import iup  # noqa: E402

Point = Tuple[float, float]

# Stages at which a discrepancy can be reported.
STAGE_FLOAT_DELTA = "float_delta"
STAGE_FLOAT_POSITION = "float_position"
STAGE_POSITION_ROUND = "position_round"
STAGE_ROUNDED_DELTA = "rounded_delta"
STAGE_ROUNDED_POSITION = "rounded_position"
STAGE_HALF_BOUNDARY = "half_boundary"

DEFAULT_FLOAT_EPS = 1e-9
# Exact-boundary test uses an absolute tolerance that absorbs representation
# noise such as 0.5000000000000001.
BOUNDARY_EPS = 1e-9


# ---------------------------------------------------------------------------
# Half-boundary helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HalfBoundary:
    """Description of a value relative to an OpenType rounding boundary.

    :ivar value: inspected value
    :ivar boundary: nearest ``k + 0.5`` decision boundary
    :ivar distance: distance to that boundary
    :ivar at_boundary: whether ``value`` sits exactly (within ``eps``) on it
    :ivar rounded: result of :func:`otRound`

    Note the asymmetric tie rule of OpenType rounding (``floor(v + 0.5)``,
    i.e. ties go towards positive infinity): ``+0.5 -> 1`` but
    ``-0.5 -> 0`` and ``-1.5 -> -1``.
    """

    value: float
    boundary: float
    distance: float
    at_boundary: bool
    rounded: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def half_boundary_info(value: float, eps: float = BOUNDARY_EPS) -> HalfBoundary:
    """Return the nearest half-integer rounding boundary for ``value``."""
    floored = math.floor(value)
    fraction = value - floored  # in [0, 1) even for negative values
    if fraction <= 0.5:
        boundary = floored + 0.5
        distance = 0.5 - fraction
    else:
        boundary = floored + 1.5
        distance = fraction - 0.5
    return HalfBoundary(
        value=value,
        boundary=boundary,
        distance=abs(distance),
        at_boundary=abs(distance) <= eps,
        rounded=otRound(value),
    )


# ---------------------------------------------------------------------------
# Structured reports
# ---------------------------------------------------------------------------


@dataclass
class Violation:
    """One point/component where full and optimized pipelines disagree."""

    sample_id: str
    axis_location: Any
    contour: int
    contour_closed: bool
    point: int
    global_point: int
    stage: str
    component: str  # "x" or "y"
    expected: float
    actual: float
    deviation: float
    tolerance: float
    anchor_span: Optional[Tuple[int, ...]]
    wraps: bool
    at_half_boundary: bool
    message: str

    def format_oneline(self) -> str:
        axis = _format_axis(self.axis_location)
        kind = "closed" if self.contour_closed else "open"
        anchors = _format_anchors(self.anchor_span, self.wraps)
        half = " HALF-BOUNDARY" if self.at_half_boundary else ""
        return (
            f"[{self.stage}{half}] sample={self.sample_id!r} axis={axis} "
            f"contour={self.contour}({kind}) point={self.point} "
            f"global_point={self.global_point} component={self.component} "
            f"expected={_fmt_num(self.expected)} actual={_fmt_num(self.actual)} "
            f"deviation={self.deviation:.6g} tol={self.tolerance:g} "
            f"anchors={anchors} -- {self.message}"
        )

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["axis_location"] = _axis_to_jsonable(self.axis_location)
        return d


@dataclass
class BoundaryNote:
    sample_id: str
    axis_location: Any
    contour: int
    contour_closed: bool
    point: int
    global_point: int
    pipeline: str  # which compared quantity: "reconstructed_delta" etc.
    component: str
    info: HalfBoundary

    def format_oneline(self) -> str:
        axis = _format_axis(self.axis_location)
        kind = "closed" if self.contour_closed else "open"
        return (
            f"[half-boundary:{self.pipeline}] sample={self.sample_id!r} "
            f"axis={axis} contour={self.contour}({kind}) point={self.point} "
            f"component={self.component} value={_fmt_num(self.info.value)} "
            f"tie={_fmt_num(self.info.boundary)} otRound={self.info.rounded}"
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "axis_location": _axis_to_jsonable(self.axis_location),
            "contour": self.contour,
            "contour_closed": self.contour_closed,
            "point": self.point,
            "global_point": self.global_point,
            "pipeline": self.pipeline,
            "component": self.component,
            "info": self.info.to_dict(),
        }


@dataclass
class ContourReport:
    contour: int
    closed: bool
    n_points: int
    sparse: List[Any]
    reconstructed: List[Point]
    rounded_pipeline: List[Point]
    violations: List[Violation] = field(default_factory=list)
    boundary_notes: List[BoundaryNote] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations


@dataclass
class SampleReport:
    sample_id: str
    axis_location: Any
    contours: List[ContourReport]
    expectation: str = "clean"
    tags: List[str] = field(default_factory=list)
    expectation_errors: List[str] = field(default_factory=list)

    @property
    def violations(self) -> List[Violation]:
        out: List[Violation] = []
        for c in self.contours:
            out.extend(c.violations)
        return out

    @property
    def boundary_notes(self) -> List[BoundaryNote]:
        out: List[BoundaryNote] = []
        for c in self.contours:
            out.extend(c.boundary_notes)
        return out

    @property
    def checker_ok(self) -> bool:
        """No equivalence violations were found."""
        return not self.violations

    @property
    def ok(self) -> bool:
        """The report matches the sample's stated expectation."""
        return not self.expectation_errors

    def format(self, include_boundaries: bool = True) -> str:
        lines: List[str] = []
        axis = _format_axis(self.axis_location)
        lines.append(
            f"=== sample {self.sample_id!r} axis={axis} "
            f"expect={self.expectation} tags={','.join(self.tags) or '-'}"
        )
        for v in self.violations:
            lines.append("  VIOLATION " + v.format_oneline())
        if include_boundaries:
            for b in self.boundary_notes:
                lines.append("  BOUNDARY  " + b.format_oneline())
        if self.expectation_errors:
            for e in self.expectation_errors:
                lines.append("  EXPECTATION-MISMATCH " + e)
        if self.ok:
            if self.expectation == "alarm":
                lines.append(
                    f"  OK: checker raised {len(self.violations)} violation(s) "
                    "matching the expected signature(s)"
                )
            else:
                lines.append(
                    f"  OK: equivalent across all stages "
                    f"({len(self.boundary_notes)} exact half-boundary value(s) observed)"
                )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _fmt_num(x: float) -> str:
    if isinstance(x, float):
        if x == int(x) and abs(x) < 1e15:
            return f"{x:.1f}"
        return f"{x:.12g}"
    return repr(x)


def _format_axis(axis: Any) -> str:
    if axis is None:
        return "<unspecified>"
    if isinstance(axis, dict):
        return "{" + ", ".join(f"{k}={v}" for k, v in axis.items()) + "}"
    return repr(axis)


def _axis_to_jsonable(axis: Any) -> Any:
    if isinstance(axis, dict):
        return {str(k): _axis_to_jsonable(v) for k, v in axis.items()}
    if isinstance(axis, (list, tuple)):
        return [_axis_to_jsonable(v) for v in axis]
    return axis


def _format_anchors(span: Optional[Tuple[int, ...]], wraps: bool) -> str:
    if span is None:
        return "no explicit anchors (all-zero fast path)"
    if len(span) == 0:
        return "no explicit anchors (all-zero fast path)"
    if len(span) == 1:
        return f"explicit@{span[0]}"
    a, b = span[0], span[1]
    wrap = " (wraps contour end)" if wraps else ""
    return f"interpolated from {a}->{b}{wrap}"


# ---------------------------------------------------------------------------
# Open-contour optimization / reconstruction
# ---------------------------------------------------------------------------


def optimize_open_contour(
    deltas: Sequence[Point], coords: Sequence[Point], tolerance: float = 0.0
) -> List[Optional[Point]]:
    """Minimal anchor DP for an *open* polyline (no wrap-around segment).

    Endpoints are always explicit.  Uses the same
    :func:`iup.can_iup_in_between` acceptance test as the closed-contour DP,
    so semantics match one non-wrapping IUP span chain.
    """
    n = len(deltas)
    if n == 0:
        return []
    if n == 1:
        return [deltas[0]]

    best = [math.inf] * n
    chain = [-1] * n
    best[0] = 1
    for i in range(1, n):
        # Fallback: point i-1 is an explicit anchor.
        best[i] = best[i - 1] + 1
        chain[i] = i - 1
        for j in range(0, i - 1):
            if best[j] + 1 >= best[i]:
                continue
            if iup.can_iup_in_between(deltas, coords, j, i, tolerance):
                best[i] = best[j] + 1
                chain[i] = j

    sparse: List[Optional[Point]] = [None] * n
    i = n - 1
    while True:
        sparse[i] = deltas[i]
        if i == 0:
            break
        i = chain[i]
    return sparse


def reconstruct_open_contour(
    sparse: Sequence[Optional[Point]], coords: Sequence[Point]
) -> List[Point]:
    """Reconstruct an open polyline from explicit anchors via IUP spans."""
    n = len(sparse)
    out: List[Optional[Point]] = [None] * n
    anchors = [k for k, d in enumerate(sparse) if d is not None]
    if not anchors:
        return [(0.0, 0.0)] * n  # pragma: no cover - defensive
    if anchors[0] != 0 or anchors[-1] != n - 1:
        raise ValueError("open contour reconstruction requires explicit endpoints")
    for a, b in zip(anchors, anchors[1:]):
        out[a] = sparse[a]
        out[b] = sparse[b]
        if b - a > 1:
            values = list(
                iup.iup_segment(
                    coords[a + 1 : b],
                    coords[a],
                    sparse[a],
                    coords[b],
                    sparse[b],
                )
            )
            for offset, k in enumerate(range(a + 1, b)):
                out[k] = values[offset]
    return out  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Anchor-span lookup (which delta group fills a point)
# ---------------------------------------------------------------------------


def anchor_span_for_point(
    sparse: Sequence[Optional[Point]], k: int, closed: bool
) -> Tuple[Optional[Tuple[int, ...]], bool]:
    """Return ``(anchor_indices, wraps)`` describing the source of point ``k``."""
    n = len(sparse)
    if sparse[k] is not None:
        return (k,), False

    explicit = [i for i, d in enumerate(sparse) if d is not None]
    if not explicit:
        return (), False

    prev_idx: Optional[int] = None
    next_idx: Optional[int] = None
    for step in range(1, n + 1):
        j = (k - step) % n if closed else k - step
        if j < 0:
            break
        if sparse[j] is not None:
            prev_idx = j
            break
    for step in range(1, n + 1):
        j = (k + step) % n if closed else k + step
        if j >= n:
            break
        if sparse[j] is not None:
            next_idx = j
            break

    if prev_idx is None or next_idx is None:
        return None, False

    wraps = closed and (prev_idx >= k or next_idx <= k) and prev_idx != next_idx
    return (prev_idx, next_idx), wraps


# ---------------------------------------------------------------------------
# Core contour check
# ---------------------------------------------------------------------------


def check_contour(
    coords: Sequence[Point],
    deltas: Sequence[Point],
    *,
    closed: bool = True,
    contour: int = 0,
    global_offset: int = 0,
    sample_id: str = "<case>",
    axis_location: Any = None,
    tolerance: float = 0.0,
    rounded_tolerance: float = 0.0,
    float_epsilon: float = DEFAULT_FLOAT_EPS,
    sparse: Optional[Sequence[Optional[Point]]] = None,
    strict_half_boundary: bool = False,
    boundary_band: float = 0.0,
) -> ContourReport:
    """Compare full ``deltas`` against optimized interpolation for one contour.

    :param coords: base coordinates (may be fractional)
    :param deltas: full explicit deltas, same length as ``coords``
    :param closed: closed (circular IUP) or open (endpoint-anchored polyline)
    :param tolerance: tolerance used by the optimizer; float-stage deviations
        up to ``tolerance + float_epsilon`` are accepted
    :param rounded_tolerance: accepted deviation in the rounded-coordinate /
        rounded-delta serialization pipeline (strict ``0`` by default)
    :param sparse: optional pre-computed/baseline sparse representation to
        verify instead of running the optimizer
    :param strict_half_boundary: turn exact half-boundary observations into
        violations even when both pipelines happen to round to the same grid
        point
    :param boundary_band: additionally record boundary notes for values within
        this distance of a ``k + 0.5`` boundary (``0`` = exact ties only)
    """
    coords = [tuple(p) for p in coords]  # type: ignore[assignment]
    deltas = [tuple(d) for d in deltas]  # type: ignore[assignment]
    n = len(coords)
    if len(deltas) != n:
        raise ValueError(
            f"contour {contour}: len(deltas)={len(deltas)} != len(coords)={n}"
        )

    if sparse is None:
        if closed:
            sparse = iup.iup_contour_optimize(deltas, coords, tolerance)
        else:
            sparse = optimize_open_contour(deltas, coords, tolerance)
    sparse = list(sparse)
    if len(sparse) != n:
        raise ValueError(
            f"contour {contour}: sparse length {len(sparse)} != coords {n}"
        )

    if closed:
        reconstructed = list(iup.iup_contour(sparse, coords))
    else:
        reconstructed = reconstruct_open_contour(sparse, coords)

    # --- serialized pipeline: round coords + retained deltas to integers ---
    rounded_coords = [(otRound(x), otRound(y)) for x, y in coords]
    encoded: List[Optional[Point]] = [
        None if d is None else (otRound(d[0]), otRound(d[1])) for d in sparse
    ]
    if closed:
        rounded_pipeline = list(iup.iup_contour(encoded, rounded_coords))
    else:
        rounded_pipeline = reconstruct_open_contour(encoded, rounded_coords)

    rounded_full = [(otRound(dx), otRound(dy)) for dx, dy in deltas]

    report = ContourReport(
        contour=contour,
        closed=closed,
        n_points=n,
        sparse=list(sparse),
        reconstructed=reconstructed,
        rounded_pipeline=rounded_pipeline,
    )

    comp_names = ("x", "y")

    def add_violation(
        k: int,
        stage: str,
        comp: int,
        expected: float,
        actual: float,
        tol: float,
        message: str,
        at_half: Optional[bool] = None,
    ) -> None:
        deviation = abs(expected - actual)
        span, wraps = anchor_span_for_point(sparse, k, closed)
        if at_half is None:
            at_half = (
                half_boundary_info(actual).at_boundary
                or half_boundary_info(expected).at_boundary
            )
        report.violations.append(
            Violation(
                sample_id=sample_id,
                axis_location=axis_location,
                contour=contour,
                contour_closed=closed,
                point=k,
                global_point=global_offset + k,
                stage=stage,
                component=comp_names[comp],
                expected=expected,
                actual=actual,
                deviation=deviation,
                tolerance=tol,
                anchor_span=span,
                wraps=wraps,
                at_half_boundary=bool(at_half),
                message=message,
            )
        )

    for k in range(n):
        span, wraps = anchor_span_for_point(sparse, k, closed)

        for j in range(2):
            full_d = float(deltas[k][j])
            recon_d = float(reconstructed[k][j])
            rf_d = float(rounded_full[k][j])
            pipe_d = float(rounded_pipeline[k][j])

            # A point/component is "boundary exposed" if any stage value sits
            # exactly on a positive/negative k+0.5 rounding boundary.
            half_here = any(
                half_boundary_info(v).at_boundary
                for v in (full_d, recon_d, rf_d, pipe_d)
            )

            # Stage 1: pre-rounding delta equivalence.
            if abs(full_d - recon_d) > tolerance + float_epsilon:
                add_violation(
                    k,
                    STAGE_FLOAT_DELTA,
                    j,
                    full_d,
                    recon_d,
                    tolerance,
                    "reconstructed delta deviates beyond optimizer tolerance",
                    at_half=half_here,
                )

            # Stage 2: pre-rounding point positions (same deviation, explicit
            # stage so reports can be filtered by what moved the glyph).
            full_pos = float(coords[k][j]) + full_d
            recon_pos = float(coords[k][j]) + recon_d
            if abs(full_pos - recon_pos) > tolerance + float_epsilon:
                add_violation(
                    k,
                    STAGE_FLOAT_POSITION,
                    j,
                    full_pos,
                    recon_pos,
                    tolerance,
                    "fractional point position differs before rounding",
                    at_half=half_here,
                )

            # Stage 3: rounded-coordinate / rounded-delta IUP pipeline.
            if abs(rf_d - pipe_d) > rounded_tolerance + float_epsilon:
                add_violation(
                    k,
                    STAGE_ROUNDED_DELTA,
                    j,
                    rf_d,
                    pipe_d,
                    rounded_tolerance,
                    "inferred delta after OpenType rounding does not match "
                    "rounded full delta (interpolation fraction changed)",
                    at_half=half_here,
                )

            # Stage 4a: round the direct float positions on both sides.
            truth_grid = otRound(float(coords[k][j]) + full_d)
            direct_grid = otRound(float(coords[k][j]) + recon_d)
            if truth_grid != direct_grid:
                add_violation(
                    k,
                    STAGE_POSITION_ROUND,
                    j,
                    float(truth_grid),
                    float(direct_grid),
                    0.0,
                    "final rounded point moves (direct float pipeline)",
                    at_half=half_here,
                )

            # Stage 4b: serialize rounded coords/deltas, infer, then place.
            serialized_truth = rounded_coords[k][j] + rounded_full[k][j]
            serialized_actual = otRound(
                rounded_coords[k][j] + float(rounded_pipeline[k][j])
            )
            if serialized_truth != serialized_actual:
                add_violation(
                    k,
                    STAGE_ROUNDED_POSITION,
                    j,
                    float(serialized_truth),
                    float(serialized_actual),
                    0.0,
                    "final rounded point moves (serialized integer pipeline)",
                    at_half=half_here,
                )

            # Half-boundary bookkeeping on every reconstructed quantity.
            for pipeline_name, value in (
                ("full_delta", full_d),
                ("reconstructed_delta", recon_d),
                ("rounded_pipeline_delta", pipe_d),
                ("full_final_position", full_pos),
                ("optimized_final_position", recon_pos),
            ):
                info = half_boundary_info(value)
                record = info.at_boundary or (
                    boundary_band > 0 and info.distance <= boundary_band
                )
                if record:
                    report.boundary_notes.append(
                        BoundaryNote(
                            sample_id=sample_id,
                            axis_location=axis_location,
                            contour=contour,
                            contour_closed=closed,
                            point=k,
                            global_point=global_offset + k,
                            pipeline=pipeline_name,
                            component=comp_names[j],
                            info=info,
                        )
                    )
                    if strict_half_boundary and info.at_boundary:
                        # Strict mode treats an exact tie in the optimized
                        # pipeline as a reportable risk unless the original
                        # full delta sits on the same tie.
                        full_info = half_boundary_info(full_d)
                        if not full_info.at_boundary:
                            add_violation(
                                k,
                                STAGE_HALF_BOUNDARY,
                                j,
                                full_d,
                                value,
                                0.0,
                                "optimized interpolation lands exactly on a "
                                "positive/negative half-value boundary",
                            )

    return report


# ---------------------------------------------------------------------------
# Sample / corpus evaluation
# ---------------------------------------------------------------------------


def evaluate_sample(sample: Dict[str, Any]) -> SampleReport:
    """Run the checker over one JSON sample definition."""
    sample_id = sample["id"]
    axis = sample.get("axis_location")
    tolerance = float(sample.get("tolerance", 0.0))
    rounded_tolerance = float(sample.get("rounded_tolerance", 0.0))
    float_epsilon = float(sample.get("float_epsilon", DEFAULT_FLOAT_EPS))
    strict_half = bool(sample.get("strict_half_boundary", False))
    boundary_band = float(sample.get("boundary_band", 0.0))
    expectation = sample.get("expect", "clean")

    contours_out: List[ContourReport] = []
    offset = 0
    for ci, cdef in enumerate(sample["contours"]):
        closed = bool(cdef.get("closed", True))
        sparse = cdef.get("sparse")
        if sparse is not None:
            sparse = [None if d is None else tuple(d) for d in sparse]
        rep = check_contour(
            [tuple(p) for p in cdef["coords"]],
            [tuple(d) for d in cdef["deltas"]],
            closed=closed,
            contour=ci,
            global_offset=offset,
            sample_id=sample_id,
            axis_location=axis,
            tolerance=tolerance,
            rounded_tolerance=rounded_tolerance,
            float_epsilon=float_epsilon,
            sparse=sparse,
            strict_half_boundary=strict_half,
            boundary_band=boundary_band,
        )
        contours_out.append(rep)
        offset += rep.n_points

    srep = SampleReport(
        sample_id=sample_id,
        axis_location=axis,
        contours=contours_out,
        expectation=expectation,
        tags=list(sample.get("tags", [])),
    )
    _check_expectation(srep, sample.get("must_include", []))
    return srep


def _check_expectation(srep: SampleReport, must_include: List[Dict[str, Any]]) -> None:
    if srep.expectation == "clean":
        if srep.violations:
            srep.expectation_errors.append(
                f"expected clean equivalence but found {len(srep.violations)} "
                "violation(s)"
            )
        return

    if srep.expectation == "alarm":
        if not srep.violations:
            srep.expectation_errors.append(
                "expected the checker to alarm but no violations were reported"
            )
        for predicate in must_include:
            match = _predicate_matches(srep.violations, predicate)
            if not match:
                srep.expectation_errors.append(
                    "no violation matches expected signature "
                    + json.dumps(predicate, sort_keys=True)
                )
        return

    srep.expectation_errors.append(f"unknown expectation {srep.expectation!r}")


def _predicate_matches(
    violations: Sequence[Violation], predicate: Dict[str, Any]
) -> bool:
    reserved = {"deviation_atol"}
    for v in violations:
        ok = True
        for key, wanted in predicate.items():
            if key in reserved:
                continue
            if key == "deviation_min":
                if v.deviation + 1e-9 < float(wanted):
                    ok = False
                    break
            elif key == "deviation_max":
                if v.deviation - 1e-9 > float(wanted):
                    ok = False
                    break
            elif key == "deviation":
                atol = float(predicate.get("deviation_atol", 1e-6))
                if abs(v.deviation - float(wanted)) > atol:
                    ok = False
                    break
            elif key == "axis_location":
                if v.axis_location != wanted:
                    ok = False
                    break
            else:
                if not hasattr(v, key) or getattr(v, key) != wanted:
                    ok = False
                    break
        if ok:
            return True
    return False


def run_cases(cases_data: Dict[str, Any]) -> List[SampleReport]:
    return [evaluate_sample(c) for c in cases_data.get("cases", [])]


def load_cases(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Outline-level helper exercising the public ends + phantom-points API
# ---------------------------------------------------------------------------


def check_closed_outline(
    contours: Sequence[Dict[str, Any]],
    *,
    sample_id: str = "<outline>",
    axis_location: Any = None,
    tolerance: float = 0.0,
) -> Tuple[Any, List[Violation]]:
    """Run the public ``iup_delta_optimize``/``iup_delta`` path.

    ``contours`` is a list of ``{"coords": [...], "deltas": [...]}``.
    Four zero phantom points are appended, as required by the ``ends``
    contract.  Returns ``(outline_report_dict, violations)`` where violations
    are discrepancies between the public API reconstruction and the full
    deltas.
    """
    coords: List[Point] = []
    deltas: List[Point] = []
    ends: List[int] = []
    for cdef in contours:
        c = [tuple(p) for p in cdef["coords"]]
        d = [tuple(x) for x in cdef["deltas"]]
        if len(c) != len(d):
            raise ValueError("coord/delta length mismatch in outline contour")
        coords.extend(c)
        deltas.extend(d)
        ends.append(len(coords) - 1)

    coords.extend([(0, 0)] * 4)
    deltas.extend([(0, 0)] * 4)

    sparse = iup.iup_delta_optimize(deltas, coords, ends, tolerance)
    reconstructed = iup.iup_delta(list(sparse), coords, ends)

    violations: List[Violation] = []
    start = 0
    for ci, end in enumerate(ends):
        for k in range(start, end + 1):
            for j, comp in enumerate(("x", "y")):
                if (
                    abs(deltas[k][j] - reconstructed[k][j])
                    > tolerance + DEFAULT_FLOAT_EPS
                ):
                    local = k - start
                    span, wraps = anchor_span_for_point(
                        sparse[start : end + 1], local, True
                    )
                    violations.append(
                        Violation(
                            sample_id=sample_id,
                            axis_location=axis_location,
                            contour=ci,
                            contour_closed=True,
                            point=local,
                            global_point=k,
                            stage=STAGE_FLOAT_DELTA,
                            component=comp,
                            expected=deltas[k][j],
                            actual=reconstructed[k][j],
                            deviation=abs(deltas[k][j] - reconstructed[k][j]),
                            tolerance=tolerance,
                            anchor_span=span,
                            wraps=wraps,
                            at_half_boundary=False,
                            message="public iup_delta outline reconstruction mismatch",
                        )
                    )
        start = end + 1
    return (
        {
            "ends": ends,
            "sparse": [None if d is None else list(d) for d in sparse],
            "reconstructed": [list(p) for p in reconstructed],
        },
        violations,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _default_cases_path() -> str:
    return os.path.join(
        os.path.dirname(__file__), "data", "iup_equivalence", "cases.json"
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run IUP full-delta vs optimized-interpolation equivalence checks."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="case JSON files (default: bundled regression corpus)",
    )
    parser.add_argument("--json", dest="json_out", help="write machine report to JSON")
    parser.add_argument(
        "--boundaries",
        action="store_true",
        help="print all exact half-boundary observations (default)",
    )
    parser.add_argument(
        "--quiet-boundaries",
        action="store_true",
        help="do not print half-boundary notes",
    )
    args = parser.parse_args(argv)

    paths = list(args.paths) or [_default_cases_path()]
    all_reports: List[SampleReport] = []
    load_errors: List[str] = []
    for path in paths:
        try:
            data = load_cases(path)
        except (OSError, json.JSONDecodeError) as e:
            load_errors.append(f"{path}: cannot load cases: {e}")
            continue
        print(f"# {path}")
        reports = run_cases(data)
        all_reports.extend(reports)
        for rep in reports:
            print(rep.format(include_boundaries=not args.quiet_boundaries))
            print()

    n_cases = len(all_reports)
    n_bad = sum(1 for r in all_reports if not r.ok)
    n_violations = sum(len(r.violations) for r in all_reports)
    expected_alarms = sum(1 for r in all_reports if r.expectation == "alarm")
    print(
        f"summary: {n_cases} case(s), {expected_alarms} expected-alarm, "
        f"{n_violations} raw violation record(s), "
        f"{n_bad} expectation failure(s), {len(load_errors)} load error(s)"
    )
    for e in load_errors:
        print("LOAD-ERROR", e)

    if args.json_out:
        payload = {
            "cases": [
                {
                    "sample_id": r.sample_id,
                    "axis_location": _axis_to_jsonable(r.axis_location),
                    "expectation": r.expectation,
                    "ok": r.ok,
                    "expectation_errors": r.expectation_errors,
                    "violations": [v.to_dict() for v in r.violations],
                    "boundary_notes": [b.to_dict() for b in r.boundary_notes],
                    "sparse": [
                        [None if d is None else list(d) for d in c.sparse]
                        for c in r.contours
                    ],
                }
                for r in all_reports
            ],
            "load_errors": load_errors,
        }
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
        print(f"machine report written to {args.json_out}")

    return 1 if n_bad or load_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
