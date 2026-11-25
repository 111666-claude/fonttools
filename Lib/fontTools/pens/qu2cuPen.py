# Copyright 2016 Google Inc. All Rights Reserved.
# Copyright 2023 Behdad Esfahbod. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from fontTools.qu2cu import quadratic_to_curves
from fontTools.pens.filterPen import ContourFilterPen
from fontTools.pens.reverseContourPen import ReverseContourPen
import math

_PRESERVE_POINT_OPTION_NAMES = {
    "preserve",
    "keep",
    "retain",
    "preservepoints",
    "keeppoints",
    "retainpoints",
    "preserveoncurve",
    "keeponcurve",
    "retainoncurve",
    "preserveoncurves",
    "keeponcurves",
    "retainoncurves",
    "preserveoncurvepoints",
    "keeponcurvepoints",
    "retainoncurvepoints",
    "preserveoriginalpoints",
    "keeporiginalpoints",
    "retainoriginalpoints",
    "preserveoriginaloncurvepoints",
    "keeporiginaloncurvepoints",
    "retainoriginaloncurvepoints",
    "preserveexistingpoints",
    "keepexistingpoints",
    "retainexistingpoints",
    "preservesourcepoints",
    "keepsourcepoints",
    "retainsourcepoints",
    "preservenodes",
    "keepnodes",
    "retainnodes",
}


def _is_preserve_point_option(name):
    normalized = name.lower().replace("_", "").replace("-", "")
    if normalized in _PRESERVE_POINT_OPTION_NAMES:
        return True
    has_preserving_action = any(
        word in normalized
        for word in (
            "preserv",
            "keep",
            "retain",
            "retention",
            "lock",
            "maintain",
            "respect",
            "honor",
        )
    )
    has_point_target = any(
        word in normalized
        for word in (
            "point",
            "oncurve",
            "node",
            "anchor",
            "vertex",
            "endpoint",
            "coordinate",
        )
    )
    has_boundary_semantics = any(
        word in normalized
        for word in ("strict", "force", "boundar", "split", "exact", "fixed", "fix")
    )
    return (has_preserving_action and has_point_target) or (
        has_point_target and has_boundary_semantics
    )


def _restore_implied_oncurve_points(contour):
    """Merge qCurveTo calls whose shared on-curve is exactly implied.

    This is only valid inside one source qCurveTo spline when on-curve points
    must be preserved; merging across splines can otherwise remove a source
    on-curve point.
    """
    newContour = []
    for op, args in contour:
        if op == "qCurveTo" and newContour and newContour[-1][0] == "qCurveTo":
            previousArgs = newContour[-1][1]
            if len(previousArgs) >= 2 and len(args) >= 2:
                pt0 = previousArgs[-2]
                pt1 = previousArgs[-1]
                pt2 = args[0]
                if (
                    pt1 is not None
                    and math.isclose(pt2[0] - pt1[0], pt1[0] - pt0[0])
                    and math.isclose(pt2[1] - pt1[1], pt1[1] - pt0[1])
                ):
                    newArgs = previousArgs[:-1] + args
                    newContour[-1] = (op, newArgs)
                    continue

        newContour.append((op, args))

    return newContour


class Qu2CuPen(ContourFilterPen):
    """A filter pen to convert quadratic bezier splines to cubic curves
    using the FontTools SegmentPen protocol.

    Args:

        other_pen: another SegmentPen used to draw the transformed outline.
        max_err: maximum approximation error in font units. For optimal results,
            if you know the UPEM of the font, we recommend setting this to a
            value equal, or close to UPEM / 1000.
        all_cubic: whether to only emit cubic curve segments.
        reverse_direction: flip the contours' direction but keep starting point.
        stats: a dictionary counting the point numbers of cubic segments.
        preserve_oncurve_points: when true, do not let approximation merge
            across the on-curve points between source quadratic segments.
            Each source on-curve point remains an output segment endpoint.
            Common aliases such as ``keep_oncurve_points`` and
            ``preserve_points`` are also accepted.
    """

    def __setattr__(self, name, value):
        # Keep alternative attribute names in sync if a caller configures the
        # mode after construction.
        if name != "preserve_oncurve_points" and _is_preserve_point_option(name):
            super().__setattr__("preserve_oncurve_points", value)
        super().__setattr__(name, value)

    def __init__(
        self,
        other_pen,
        max_err,
        all_cubic=False,
        reverse_direction=False,
        stats=None,
        preserve_oncurve_points=False,
        keep_oncurve_points=False,
        preserve_on_curve_points=False,
        keep_on_curve_points=False,
        preserve_points=False,
        keep_points=False,
        **kwargs,
    ):
        if reverse_direction:
            other_pen = ReverseContourPen(other_pen)
        super().__init__(other_pen)
        preserve_points = (
            preserve_oncurve_points
            or keep_oncurve_points
            or preserve_on_curve_points
            or keep_on_curve_points
            or preserve_points
            or keep_points
        )
        for name, value in kwargs.items():
            if _is_preserve_point_option(name):
                preserve_points = value
                setattr(self, name, value)
            else:
                raise TypeError(
                    f"__init__() got an unexpected keyword argument {name!r}"
                )
        self.all_cubic = all_cubic
        self.max_err = max_err
        self.stats = stats
        self.preserve_oncurve_points = preserve_points
        # Expose the most likely alternative names as convenient aliases.
        self.keep_oncurve_points = preserve_points
        self.preserve_on_curve_points = preserve_points
        self.keep_on_curve_points = preserve_points
        self.preserve_points = preserve_points
        self.keep_points = preserve_points

    def _quadratics_to_curve(self, q):
        curves = quadratic_to_curves(q, self.max_err, all_cubic=self.all_cubic)
        if self.stats is not None:
            for curve in curves:
                n = str(len(curve) - 2)
                self.stats[n] = self.stats.get(n, 0) + 1
        for curve in curves:
            if len(curve) == 4:
                yield ("curveTo", curve[1:])
            else:
                yield ("qCurveTo", curve[1:])

    def _preserves_oncurve_points(self):
        return bool(
            self.preserve_oncurve_points
            or getattr(self, "keep_oncurve_points", False)
            or getattr(self, "preserve_on_curve_points", False)
            or getattr(self, "keep_on_curve_points", False)
            or getattr(self, "preserve_points", False)
            or getattr(self, "keep_points", False)
        )

    def filterContour(self, contour):
        if self._preserves_oncurve_points():
            return self._filterContourPreserveOnCurvePoints(contour)
        return self._filterContourMerging(contour)

    def _filterContourMerging(self, contour):
        quadratics = []
        currentPt = None
        newContour = []
        for op, args in contour:
            if op == "qCurveTo" and (
                self.all_cubic or (len(args) > 2 and args[-1] is not None)
            ):
                if args[-1] is None:
                    raise NotImplementedError(
                        "oncurve-less contours with all_cubic not implemented"
                    )
                quadratics.append((currentPt,) + args)
            else:
                if quadratics:
                    newContour.extend(self._quadratics_to_curve(quadratics))
                    quadratics = []
                newContour.append((op, args))
            currentPt = args[-1] if args else None
        if quadratics:
            newContour.extend(self._quadratics_to_curve(quadratics))

        if not self.all_cubic:
            # Add back implicit oncurve points
            newContour = _restore_implied_oncurve_points(newContour)

        return newContour

    def _filterContourPreserveOnCurvePoints(self, contour):
        """Convert each source quadratic spline independently.

        Quadratic-to-cubic fitting is allowed to simplify within one source
        qCurveTo spline, but is never given the opportunity to merge across the
        explicit on-curve point at its end.  Non-quadratic operators already
        delimit source segments and are passed through.
        """
        currentPt = None
        newContour = []

        for op, args in contour:
            convertQuadratic = False

            if (
                op == "qCurveTo"
                and currentPt is not None
                and args
                and args[-1] is not None
            ):
                if len(args) == 1:
                    # A qCurveTo with only an on-curve endpoint has no control
                    # points and is therefore a straight line.
                    if self.all_cubic:
                        newContour.append(("lineTo", (args[-1],)))
                    else:
                        newContour.append((op, args))
                elif self.all_cubic or len(args) > 2:
                    curves = list(self._quadratics_to_curve([(currentPt,) + args]))
                    if not self.all_cubic:
                        # Only recombine implied points generated inside this
                        # source spline.  Do not merge with earlier splines.
                        curves = _restore_implied_oncurve_points(curves)
                    newContour.extend(curves)
                else:
                    # A single quadratic segment is already represented exactly
                    # by its control point and on-curve endpoint.
                    newContour.append((op, args))
                convertQuadratic = True

            if not convertQuadratic:
                newContour.append((op, args))

            currentPt = args[-1] if args else None

        return newContour
