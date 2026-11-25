"""Single-axis reverse lookup of ``avar`` v1 segment mappings.

The forward direction maps a normalized design coordinate through the
piecewise-linear ``avar`` segments.  This module answers the inverse
question: given the *mapped* (output) value a designer picked, which
normalized (or user-space) input coordinates produce it?

Only ``avar`` version 1 segment maps can be inverted this way.  An
``avar`` version 2 table additionally applies VarStore deltas, which in
general make the mapping non-piecewise-linear and non-invertible; such
fonts raise :class:`ReverseMapError` instead of guessing.
"""

from __future__ import annotations

__all__ = [
    "ReverseMapError",
    "reverseMap",
    "verifySolutions",
    "verifyResult",
    "main",
]

from dataclasses import replace

from fontTools.varLib.models import (
    ReverseMapResult,
    normalizeValue,
    piecewiseLinearMap,
    reversePiecewiseLinearMap,
)


class ReverseMapError(ValueError):
    """Raised when a reverse lookup cannot be answered unambiguously.

    This covers missing ``fvar``/``avar`` data, ``avar`` version 2
    tables, multi-axis input, unknown axis tags, and user-space targets
    outside the axis's fvar range.
    """


def _denormalize(v, triplet):
    if v >= 0:
        return triplet[1] + v * (triplet[2] - triplet[1])
    else:
        return triplet[1] + v * (triplet[0] - triplet[1])


def _toUserSolution(solution, triplet):
    if solution.isInterval:
        return replace(
            solution,
            intervalStart=_denormalize(solution.intervalStart, triplet),
            intervalEnd=_denormalize(solution.intervalEnd, triplet),
        )
    return replace(solution, value=_denormalize(solution.value, triplet))


def reverseMap(
    font,
    axis,
    target,
    *,
    inputNormalized=False,
    outputNormalized=False,
    clip=True,
):
    """Reverse-lookup every input producing ``target`` on one ``avar`` axis.

    Args:
        font: a :class:`~fontTools.ttLib.TTFont` containing an ``fvar``
            table (and typically an ``avar`` table).
        axis: exactly one axis tag, e.g. ``"wght"``.
        target: the desired *mapped* value.  It is interpreted in fvar
            user units unless ``inputNormalized`` is true, in which case
            it is a normalized -1..1 coordinate.
        inputNormalized: whether ``target`` is already normalized.
        outputNormalized: when false (default) the returned preimages are
            converted back to fvar user units; when true they stay
            normalized.
        clip: when true (default) restrict preimages to the axis's
            normalized -1..1 domain, so out-of-range targets are reported
            unreachable.  When false the slope-1 extrapolation outside
            the outermost mapping keys is also inverted.

    Returns:
        A :class:`~fontTools.varLib.models.ReverseMapResult`.  Every
        solution can be re-checked by feeding it back through
        :func:`~fontTools.varLib.models.piecewiseLinearMap`; see
        :func:`verifySolutions`.

    Raises:
        ReverseMapError: if the font lacks ``fvar``, the axis is
            unknown, more than one axis is requested, the font has an
            ``avar`` version 2 table, or a user-space ``target`` lies
            outside the fvar min/max while ``clip`` is true.
    """
    if "fvar" not in font:
        raise ReverseMapError(
            "font has no 'fvar' table; axis ranges are required to convert "
            "between normalized and user-space coordinates"
        )

    if isinstance(axis, dict):
        if len(axis) != 1:
            raise ReverseMapError(
                "reverse lookup is only defined for a single axis; got "
                f"{len(axis)} axes: {', '.join(sorted(axis))}"
            )
        (axis,) = axis.keys()

    axes = {a.axisTag: a for a in font["fvar"].axes}
    if axis not in axes:
        raise ReverseMapError(
            f"unknown axis tag {axis!r}; fvar axes: {', '.join(sorted(axes)) or '(none)'}"
        )

    avar = font.get("avar")
    if avar is not None and getattr(avar, "majorVersion", 1) >= 2:
        raise ReverseMapError(
            f"axis {axis!r} belongs to an 'avar' version 2 table: its VarStore "
            "deltas make the mapping non-piecewise-linear, so it cannot be "
            "inverted; only avar v1 segment maps are supported"
        )

    fvarAxis = axes[axis]
    triplet = (fvarAxis.minValue, fvarAxis.defaultValue, fvarAxis.maxValue)

    if not inputNormalized:
        if clip and not (triplet[0] <= target <= triplet[2]):
            raise ReverseMapError(
                f"target {target:g} is outside the fvar range of axis {axis!r} "
                f"[{triplet[0]:g}, {triplet[2]:g}]; pass inputNormalized=True "
                "with a -1..1 value, or clip=False to extrapolate"
            )
        normalizedTarget = normalizeValue(target, triplet, extrapolate=not clip)
    else:
        if clip and not (-1.0 <= target <= 1.0):
            raise ReverseMapError(
                f"normalized target {target:g} is outside the [-1, 1] axis "
                f"domain of axis {axis!r}; pass clip=False to extrapolate"
            )
        normalizedTarget = target

    segments = {}
    if avar is not None:
        segments = avar.segments.get(axis, {})

    result: ReverseMapResult = reversePiecewiseLinearMap(
        normalizedTarget, segments, clip=clip
    )
    result = replace(result, axis=axis)

    if not outputNormalized:
        result = replace(
            result,
            solutions=[_toUserSolution(s, triplet) for s in result.solutions],
            target=_denormalize(normalizedTarget, triplet),
            reachableRange=(
                (
                    _denormalize(result.reachableRange[0], triplet),
                    _denormalize(result.reachableRange[1], triplet),
                )
                if result.reachableRange is not None
                else None
            ),
            domain=(
                (
                    _denormalize(result.domain[0], triplet),
                    _denormalize(result.domain[1], triplet),
                )
                if result.domain is not None
                else None
            ),
            unit="user",
        )

    return result


def verifySolutions(result, segments, *, tolerance=1e-9):
    """Forward-check every solution of a *normalized* reverse lookup.

    Feeds each returned point (and each interval's endpoints plus
    midpoint) back through :func:`piecewiseLinearMap` and asserts the
    forward output matches the requested target within ``tolerance``.

    Args:
        result: a :class:`ReverseMapResult` in normalized coordinates
            (``result.unit == "normalized"``).
        segments: the avar segment mapping that produced it, i.e.
            ``font["avar"].segments[axis]``.
        tolerance: maximum allowed absolute forward error.

    Returns:
        A list of ``(solution, maxAbsError)`` pairs, one per solution,
        in the same order as ``result.solutions``.
    """
    checked = []
    for solution in result.solutions:
        if solution.isInterval:
            probePoints = (
                solution.intervalStart,
                (solution.intervalStart + solution.intervalEnd) / 2,
                solution.intervalEnd,
            )
        else:
            probePoints = (solution.value,)
        maxError = max(
            abs(piecewiseLinearMap(x, segments) - result.target) for x in probePoints
        )
        if maxError > tolerance:
            raise AssertionError(
                f"forward check failed for {solution!r}: max abs error "
                f"{maxError:g} exceeds tolerance {tolerance:g}"
            )
        checked.append((solution, maxError))
    return checked


def verifyResult(font, result, *, tolerance=1e-9):
    """Forward-check a reverse lookup in any coordinate space.

    This is the font-aware counterpart of :func:`verifySolutions`.
    Verification is always performed in normalized coordinates, because
    denormalization is a piecewise-affine map and the avar segments only
    compose correctly in normalized space.  User-space results have
    their target and probe points re-normalized through the fvar
    triplet before the forward avar mapping is applied.

    Args:
        font: the :class:`~fontTools.ttLib.TTFont` used for the lookup.
        result: the :class:`ReverseMapResult` to verify.
        tolerance: maximum allowed absolute forward error, measured in
            normalized coordinates.

    Returns:
        A list of ``(solution, maxAbsError)`` pairs in solution order;
        the solution objects are exactly those in ``result.solutions``.
    """
    avar = font.get("avar")
    segments = avar.segments.get(result.axis, {}) if avar is not None else {}

    if result.unit == "normalized":
        return verifySolutions(result, segments, tolerance=tolerance)

    axis = next(a for a in font["fvar"].axes if a.axisTag == result.axis)
    triplet = (axis.minValue, axis.defaultValue, axis.maxValue)
    normalizedTarget = normalizeValue(result.target, triplet)

    checked = []
    for solution in result.solutions:
        if solution.isInterval:
            userProbes = (
                solution.intervalStart,
                (solution.intervalStart + solution.intervalEnd) / 2,
                solution.intervalEnd,
            )
        else:
            userProbes = (solution.value,)
        maxError = max(
            abs(
                piecewiseLinearMap(normalizeValue(x, triplet), segments)
                - normalizedTarget
            )
            for x in userProbes
        )
        if maxError > tolerance:
            raise AssertionError(
                f"forward check failed for {solution!r}: max abs error "
                f"{maxError:g} exceeds tolerance {tolerance:g}"
            )
        checked.append((solution, maxError))
    return checked


def main(args=None):
    """Command-line entry point: reverse-query one avar axis."""

    from fontTools.ttLib import TTFont
    import argparse

    if args is None:
        import sys

        args = sys.argv[1:]

    parser = argparse.ArgumentParser(
        "fonttools varLib.avar.reverse_map",
        description=(
            "Find every input coordinate that maps to a target value through "
            "a single avar v1 axis (the inverse of varLib.avar.map)."
        ),
    )
    parser.add_argument("font", metavar="varfont.ttf", help="Variable-font file.")
    parser.add_argument(
        "coord",
        metavar="AXIS=value",
        help="Target mapped value, e.g. 'wght=700' (use -i for normalized).",
    )
    parser.add_argument(
        "-i",
        action="store_true",
        help="The target is a normalized coordinate (-1..1) instead of fvar units.",
    )
    parser.add_argument(
        "-o",
        action="store_true",
        help="Output preimages as normalized coordinates (-1..1).",
    )
    parser.add_argument(
        "--no-clip",
        action="store_true",
        help="Also invert the slope-1 extrapolation outside the mapping keys "
        "(by default preimages are clipped to the axis domain).",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Re-run every solution through the forward avar mapping and print "
        "the maximum absolute error.",
    )

    options = parser.parse_args(args)

    tag, sep, value = options.coord.partition("=")
    if not sep or not tag or not value:
        parser.error(
            f"Invalid coordinate {options.coord!r}. Expected AXIS=value, e.g. wght=700"
        )
    try:
        target = float(value)
    except ValueError:
        parser.error(
            f"Invalid coordinate value in {options.coord!r}: expected a number"
        )

    if options.font.endswith(".designspace"):
        from .build import build

        font = TTFont()
        build(font, options.font)
    else:
        font = TTFont(options.font)

    try:
        result = reverseMap(
            font,
            tag,
            target,
            inputNormalized=options.i,
            outputNormalized=options.o,
            clip=not options.no_clip,
        )
    except ReverseMapError as e:
        parser.error(str(e))

    unit = "normalized" if options.o else "user"
    print(
        f"axis={result.axis} target={result.target:g} ({unit} units); "
        f"{len(result.solutions)} preimage(s):"
    )

    if not result.reachable:
        print(f"  no solution: {result.reason}")
        return 1

    if options.verify:
        # Forward-check through the real avar mapping in normalized space;
        # user-space probe points are re-normalized by verifyResult.
        checked = {
            id(solution): error for solution, error in verifyResult(font, result)
        }

    for index, solution in enumerate(result.solutions):
        if solution.isInterval:
            line = (
                f"  [{index}] interval: {solution.intervalStart:g} .. "
                f"{solution.intervalEnd:g} (any input in this range maps to "
                f"{result.target:g})"
            )
        else:
            line = f"  [{index}] point: {solution.value:g}"
        if options.verify:
            line += (
                f"  | forward max abs error = {checked[id(solution)]:g}"
                " (normalized space)"
            )
        print(line)
        print(f"        why: {solution.explanation}")

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
