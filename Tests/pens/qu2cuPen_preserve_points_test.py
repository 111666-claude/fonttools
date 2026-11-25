import pytest

from fontTools.pens.qu2cuPen import Qu2CuPen
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.ttGlyphPen import TTGlyphPen


def _two_connected_quadratics(max_err, **kwargs):
    pen = RecordingPen()
    converter = Qu2CuPen(pen, max_err, all_cubic=True, **kwargs)
    converter.moveTo((0, 0))
    converter.qCurveTo((0, 1), (1, 1))
    converter.qCurveTo((3, 1), (3, 0))
    converter.closePath()
    return pen.value


def _segment_endpoints(recording):
    return [
        args[-1]
        for op, args in recording
        if op in ("moveTo", "lineTo", "curveTo", "qCurveTo")
        and args
        and args[-1] is not None
    ]


def test_loose_tolerance_default_merges_across_shared_oncurve():
    value = _two_connected_quadratics(0.5)

    curves = [op for op, _ in value if op == "curveTo"]
    assert curves == ["curveTo"]


def test_preserve_oncurve_points_keeps_shared_node_loose_and_tight():
    expected_first = tuple(
        (pytest.approx(x), pytest.approx(y))
        for x, y in (
            (0.0, 2 / 3),
            (1 / 3, 1.0),
            (1.0, 1.0),
        )
    )
    expected_second = tuple(
        (pytest.approx(x), pytest.approx(y))
        for x, y in (
            (7 / 3, 1.0),
            (3.0, 2 / 3),
            (3.0, 0.0),
        )
    )

    for max_err in (0.2, 0.5, 10.0):
        value = _two_connected_quadratics(max_err, preserve_oncurve_points=True)
        curves = [args for op, args in value if op == "curveTo"]

        assert len(curves) == 2
        assert curves[0] == expected_first
        assert curves[1] == expected_second
        assert (1, 1) in _segment_endpoints(value)


def test_preserve_loose_matches_default_tight_split():
    tight = _two_connected_quadratics(1e-9)
    preserved_loose = _two_connected_quadratics(100.0, preserve_oncurve_points=True)

    assert preserved_loose == tight


@pytest.mark.parametrize(
    "keyword",
    [
        "keep_oncurve_points",
        "preserve_on_curve_points",
        "keep_on_curve_points",
        "preserve_points",
        "keep_points",
    ],
)
def test_preserve_mode_accepts_common_keyword_aliases(keyword):
    value = _two_connected_quadratics(10.0, **{keyword: True})

    assert len([op for op, _ in value if op == "curveTo"]) == 2
    assert (1, 1) in _segment_endpoints(value)


def test_non_cubic_mode_does_not_make_explicit_node_implicit():
    out = RecordingPen()
    pen = Qu2CuPen(out, 10.0, preserve_oncurve_points=True)
    pen.moveTo((0, 0))
    pen.qCurveTo((1, 2), (2, 0))
    pen.qCurveTo((3, -2), (4, 0))
    pen.closePath()

    assert out.value == [
        ("moveTo", ((0, 0),)),
        ("qCurveTo", ((1, 2), (2, 0))),
        ("qCurveTo", ((3, -2), (4, 0))),
        ("closePath", ()),
    ]

    default_out = RecordingPen()
    default_pen = Qu2CuPen(default_out, 10.0)
    default_pen.moveTo((0, 0))
    default_pen.qCurveTo((1, 2), (2, 0))
    default_pen.qCurveTo((3, -2), (4, 0))
    default_pen.closePath()
    assert default_out.value == [
        ("moveTo", ((0, 0),)),
        ("qCurveTo", ((1, 2), (3, -2), (4, 0))),
        ("closePath", ()),
    ]


def test_preserve_mode_handles_open_mixed_contour_and_replays():
    out = RecordingPen()
    pen = Qu2CuPen(out, 100.0, all_cubic=True, preserve_oncurve_points=True)

    source_points = [
        (0, 0),
        (1, 0),
        (1, 1),
        (2, 2),
        (3, 1),
        (4, 1),
        (5, 0),
    ]
    pen.moveTo(source_points[0])
    pen.lineTo(source_points[1])
    pen.qCurveTo((2, 0), source_points[2])
    pen.qCurveTo((4, 2), source_points[3])
    pen.curveTo((2, 3), (4, 3), source_points[4])
    pen.lineTo(source_points[5])
    pen.qCurveTo((4.5, -1), source_points[6])
    pen.endPath()

    endpoints = _segment_endpoints(out.value)
    for point in source_points:
        assert point in endpoints
    assert not any(op == "qCurveTo" for op, _ in out.value)

    replay = RecordingPen()
    out.replay(replay)
    assert replay.value == out.value

    glyph_pen = TTGlyphPen(None)
    out.replay(glyph_pen)
    assert glyph_pen.glyph().numberOfContours == 1

    charstring_pen = T2CharStringPen(600, None)
    out.replay(charstring_pen)
    charstring_pen.getCharString().compile()


def test_preserve_mode_handles_degenerate_controls():
    out = RecordingPen()
    pen = Qu2CuPen(out, 1.0, all_cubic=True, keep_oncurve_points=True)

    pen.moveTo((1, 1))
    pen.lineTo((1, 1))
    pen.qCurveTo((1, 1), (1, 1))
    pen.qCurveTo((1, 1), (2, 2))
    pen.qCurveTo((1e-12, 2), (2, 2))
    pen.qCurveTo((2 + 1e-12, 2), (3, 2))
    pen.lineTo((3, 2))
    pen.closePath()

    assert all(op != "qCurveTo" for op, _ in out.value)
    assert (2, 2) in _segment_endpoints(out.value)

    glyph_pen = TTGlyphPen(None)
    out.replay(glyph_pen)
    glyph_pen.glyph()
