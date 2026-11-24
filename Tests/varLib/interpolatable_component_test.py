from types import SimpleNamespace

import pytest

from fontTools.misc.transform import Identity
from fontTools.pens.recordingPen import (
    DecomposingRecordingPen,
    RecordingPen,
    replayRecording,
)
from fontTools.pens.statisticsPen import StatisticsPen, StatisticsControlPen
from fontTools.varLib import interpolatable
from fontTools.varLib.interpolatableHelpers import contour_vector_from_stats

STAT_FIELDS = (
    "area",
    "meanX",
    "meanY",
    "varianceX",
    "varianceY",
    "stddevX",
    "stddevY",
    "covariance",
    "correlation",
    "slant",
)


def component(name, transform=Identity):
    pen = RecordingPen()
    pen.addComponent(name, transform)
    return pen


def make_outline():
    pen = RecordingPen()
    pen.moveTo((0, 0))
    pen.qCurveTo((50, 125), (100, 0))
    pen.lineTo((120, -20))
    pen.curveTo((80, -50), (20, -30), (0, 0))
    pen.closePath()
    pen.moveTo((150, 0))
    pen.lineTo((180, 60))
    pen.lineTo((200, 0))
    pen.closePath()
    return pen


class CountingGlyph:
    """Glyph wrapper that counts how many times its outline is drawn."""

    def __init__(self, outline):
        self.outline = outline
        self.draws = 0

    def draw(self, pen):
        self.draws += 1
        self.outline.replay(pen)


def make_nested_glyphset(transform=Identity):
    """Fixed nested sample.

    'composite' references 'nested' and 'base'; 'nested' references 'base'.
    The two entries in 'composite' are what the analysis expands, so the old
    code (area/control/green pens each expanding per contour) drew 'base'
    four times.
    """
    outline = make_outline()
    composite = component("nested", transform)
    composite.addComponent("base", (0.5, 0, 0, 0.5, 200, 50))
    glyphset = {
        "base": CountingGlyph(outline),
        "nested": CountingGlyph(component("base", (1.25, 0.125, -0.25, 0.75, 40, -20))),
        "composite": CountingGlyph(composite),
    }
    return glyphset, composite, outline


def replay_glyph(outline):
    return SimpleNamespace(draw=outline.replay)


def reference_stat(entry, outline):
    """Statistics for one component entry, computed without any caching."""
    glyphset = {
        "base": replay_glyph(outline),
        "nested": replay_glyph(component("base", (1.25, 0.125, -0.25, 0.75, 40, -20))),
    }
    decomposed = DecomposingRecordingPen(glyphset)
    replayRecording([entry], decomposed)
    pens = []
    for penClass in (StatisticsPen, StatisticsControlPen):
        pen = penClass(glyphset)
        replayRecording(decomposed.value, pen)
        pens.append(pen)
    return pens


@pytest.mark.parametrize(
    "transform",
    [
        Identity,
        (-1, 0, 0, 1, 80, 25),
        (0.75, 0.25, -0.125, 1.5, 10, -30),
        (1, 2, 2, 4, -10, 20),
    ],
)
def test_component_outline_reused_for_both_statistics_pens(transform):
    glyphset, composite, outline = make_nested_glyphset(transform)

    glyph = interpolatable.Glyph("composite", glyphset)

    # Each component is expanded once per analysis, not once per statistics
    # pen. The old code drew 'base' 4 times for this sample.
    assert glyphset["base"].draws == 2
    assert glyphset["nested"].draws == 1

    assert glyph.nodeTypes == [["addComponent"], ["addComponent"]]
    assert [recording.value for recording in glyph.recordings] == [
        [entry] for entry in composite.value
    ]
    assert glyph.points == [None, None]
    assert glyph.isomorphisms == [None, None]
    assert glyph.openContours == [False, False]

    for i, entry in enumerate(composite.value):
        green, control = reference_stat(entry, outline)
        actualGreen = glyph.greenStats[i]
        actualControl = glyph.controlStats[i]
        assert [getattr(actualGreen, f) for f in STAT_FIELDS] == [
            getattr(green, f) for f in STAT_FIELDS
        ]
        assert [getattr(actualControl, f) for f in STAT_FIELDS] == [
            getattr(control, f) for f in STAT_FIELDS
        ]
        assert glyph.greenVectors[i] == contour_vector_from_stats(green)
        assert glyph.controlVectors[i] == contour_vector_from_stats(control)


def test_decomposition_is_not_cached_across_glyphs_or_masters():
    glyphset, _, outline = make_nested_glyphset()
    other = component("base", (2, 0, 0, 2, 0, 0))
    glyphset["other"] = CountingGlyph(other)

    interpolatable.Glyph("composite", glyphset)
    assert glyphset["base"].draws == 2

    otherGlyph = interpolatable.Glyph("other", glyphset)
    # A fresh expansion, not a cached recording from the previous glyph.
    assert glyphset["base"].draws == 3
    green, control = reference_stat(other.value[0], outline)
    assert [getattr(otherGlyph.greenStats[0], f) for f in STAT_FIELDS] == [
        getattr(green, f) for f in STAT_FIELDS
    ]
    assert [getattr(otherGlyph.controlStats[0], f) for f in STAT_FIELDS] == [
        getattr(control, f) for f in STAT_FIELDS
    ]


def test_missing_component_is_skipped(caplog):
    glyphset, _, _ = make_nested_glyphset()
    glyphset["composite"] = CountingGlyph(component("missing"))

    glyph = interpolatable.Glyph("composite", glyphset)

    assert glyph.openContours == [False]
    assert glyph.greenStats[0].area == 0
    assert glyph.controlStats[0].area == 0
    assert "missing from glyphSet; skipped" in caplog.text


def test_open_component_is_reported():
    glyphset, _, _ = make_nested_glyphset()
    openOutline = RecordingPen()
    openOutline.moveTo((0, 0))
    openOutline.lineTo((100, 0))
    openOutline.endPath()
    glyphset["base"] = CountingGlyph(openOutline)

    glyph = interpolatable.Glyph("composite", glyphset)

    assert glyph.openContours == [True, True]
    assert glyph.greenStats == [None, None]
    assert glyph.controlStats == [None, None]
    # Each component is expanded once, even when the contour turns out open.
    assert glyphset["base"].draws == 2


@pytest.mark.parametrize("error", [ValueError, NotImplementedError, AttributeError])
def test_unsupported_component_keeps_existing_behavior(error):
    def draw(pen):
        raise error("unsupported component")

    glyphset = {"base": SimpleNamespace(draw=draw), "composite": component("base")}
    with pytest.raises(error):
        interpolatable.Glyph("composite", glyphset)


def single_component_glyphset(open_=False):
    # A one-component composite keeps the contour-order matcher away (it only
    # runs for two or more contours), so this test exercises report ordering.
    base = RecordingPen()
    base.moveTo((0, 0))
    base.lineTo((100, 0))
    if open_:
        base.endPath()
    else:
        base.lineTo((100, 100))
        base.closePath()
    return {"base": CountingGlyph(base), "composite": CountingGlyph(component("base"))}


def test_diagnostics_order_is_preserved():
    # Three masters: valid, open component, missing glyph. The report order
    # must follow master order as it did before the optimization.
    valid = single_component_glyphset()
    openGlyphset = single_component_glyphset(open_=True)
    missing = dict(valid)
    missing["composite"] = None

    problems = list(
        interpolatable.test_gen(
            [valid, openGlyphset, missing],
            glyphs=["composite"],
            names=["Regular", "Open", "Sparse"],
        )
    )

    assert problems == [
        (
            "composite",
            {"type": "open_path", "master": "Open", "master_idx": 1, "contour": 0},
        ),
        ("composite", {"type": "missing", "master": "Sparse", "master_idx": 2}),
    ]


def test_compatible_nested_components_report_no_problems():
    regular, _, _ = make_nested_glyphset()
    bold, _, _ = make_nested_glyphset()
    problems = list(
        interpolatable.test_gen(
            [regular, bold],
            glyphs=["composite"],
            names=["Regular", "Bold"],
            show_all=True,
        )
    )
    assert problems == [
        (
            "composite",
            {
                "type": "nothing",
                "master_1": "Regular",
                "master_2": "Bold",
                "master_1_idx": 0,
                "master_2_idx": 1,
            },
        )
    ]
    # Each master was expanded independently: two draws each, no sharing
    # between masters.
    assert regular["base"].draws == 2
    assert bold["base"].draws == 2
