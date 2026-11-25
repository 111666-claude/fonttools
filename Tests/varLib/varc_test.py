import io

import pytest

from fontTools.fontBuilder import FontBuilder
from fontTools.misc.transform import DecomposedTransform
from fontTools.pens.basePen import PenError
from fontTools.pens.recordingPen import (
    DecomposingRecordingPen,
    RecordingPen,
)
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables.otTables import VarComponentFlags
from fontTools.varLib.varc import buildVARC


AXES = [
    ("wght", 100, 400, 900, "Weight"),
    ("wdth", 50, 100, 200, "Width"),
]
GLYPH_ORDER = [".notdef", "box", "leaf", "stem", "composite", "nested"]


def _simple_glyph(pen_class, points):
    pen = pen_class(None)
    pen.moveTo(points[0])
    for point in points[1:]:
        pen.lineTo(point)
    pen.closePath()
    return pen.glyph()


def build_minimal_font():
    """Build a two-axis font with simple outlines plus two variable
    composite glyphs, one of which nests another variable composite.

    All numeric inputs are chosen to be exactly representable in the
    VARC fixed-point encodings so binary round trips are lossless.
    """
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder(GLYPH_ORDER)
    fb.setupCharacterMap({0x61: "composite", 0x62: "nested"})

    glyphs = {
        ".notdef": TTGlyphPen(None).glyph(),
        "box": _simple_glyph(
            TTGlyphPen, [(0, 0), (300, 0), (300, 300), (0, 300)]
        ),
        "leaf": _simple_glyph(
            TTGlyphPen, [(0, 0), (200, 0), (100, 250)]
        ),
        "stem": _simple_glyph(
            TTGlyphPen, [(0, 0), (50, 0), (50, 400), (0, 400)]
        ),
    }
    metrics = {
        ".notdef": (500, 0),
        "box": (400, 0),
        "leaf": (300, 0),
        "stem": (100, 0),
        "composite": (600, 0),
        "nested": (700, 0),
    }
    fb.setupHorizontalMetrics(metrics)
    fb.setupGlyf(glyphs)
    font = fb.font
    glyph_set = font.getGlyphSet()

    pen = TTGlyphPen(glyph_set)
    pen.addVarComponent(
        "box",
        DecomposedTransform(),
        {"wght": 0.0, "wdth": 0.0},
    )
    # 45 degrees is exactly representable in F4Dot12 (1024 / 4096 * 180).
    pen.addVarComponent(
        "leaf",
        DecomposedTransform(translateX=100, translateY=50, rotation=45.0),
        {"wght": 0.5, "wdth": -0.5},
    )
    font["glyf"]["composite"] = pen.glyph()

    pen = TTGlyphPen(glyph_set)
    pen.addVarComponent(
        "composite",
        DecomposedTransform(translateX=20, translateY=30),
        {"wght": -0.25, "wdth": 0.75},
        resetUnspecifiedAxes=True,
    )
    pen.addVarComponent(
        "stem",
        DecomposedTransform(translateX=400),
        {"wght": 1.0},
    )
    font["glyf"]["nested"] = pen.glyph()

    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "VarCTest", "styleName": "Regular"})
    fb.setupOS2(
        sTypoAscender=800,
        sTypoDescender=-200,
        usWinAscent=800,
        usWinDescent=200,
    )
    fb.setupPost()
    fb.setupMaxp()
    fb.setupFvar(axes=AXES, instances=[])

    buildVARC(font)
    return font


def save_and_reload(font):
    blob = io.BytesIO()
    font.save(blob)
    blob.seek(0)
    return TTFont(blob)


def add_glyph(font, name, glyph):
    """Register a new glyph so glyf lookup and VARC coverage can resolve it."""
    font.setGlyphOrder(font.getGlyphOrder() + [name])
    font["glyf"][name] = glyph
    font["hmtx"].metrics[name] = (500, 0)


class TestBuildVARC:
    def test_table_structure(self):
        font = build_minimal_font()
        varc = font["VARC"].table
        assert varc.Coverage.glyphs == ["composite", "nested"]
        # (wght, wdth) and (wght,) tuples, interned.
        assert varc.AxisIndicesList.Item == [[0, 1], [0]]
        assert varc.MultiVarStore is None
        assert varc.ConditionList is None
        records = varc.VarCompositeGlyphs.VarCompositeGlyph
        assert len(records) == 2
        assert [c.glyphName for c in records[0].components] == ["box", "leaf"]
        assert [c.glyphName for c in records[1].components] == [
            "composite",
            "stem",
        ]

    def test_axis_values_and_transform_preserved(self):
        font = save_and_reload(build_minimal_font())
        varc = font["VARC"].table
        leaf = varc.VarCompositeGlyphs.VarCompositeGlyph[0].components[1]
        assert leaf.glyphName == "leaf"
        assert leaf.transform.rotation == 45.0
        assert leaf.transform.translateX == 100
        assert leaf.transform.translateY == 50
        assert leaf.axisValues == (0.5, -0.5)

        nested = varc.VarCompositeGlyphs.VarCompositeGlyph[1].components[0]
        assert nested.glyphName == "composite"
        assert nested.flags & VarComponentFlags.RESET_UNSPECIFIED_AXES
        assert nested.transform.translateX == 20
        assert nested.transform.translateY == 30
        assert nested.axisValues == (-0.25, 0.75)

    @pytest.mark.parametrize(
        "location",
        [
            {},
            {"wght": 400, "wdth": 100},
            {"wght": 900, "wdth": 200},
            {"wght": 100, "wdth": 50},
            {"wght": 700, "wdth": 120},
        ],
    )
    def test_binary_roundtrip_outlines(self, location):
        original = build_minimal_font()
        reloaded = save_and_reload(original)
        for name in ("composite", "nested"):
            pen1, pen2 = RecordingPen(), RecordingPen()
            original.getGlyphSet(location=location)[name].draw(pen1)
            reloaded.getGlyphSet(location=location)[name].draw(pen2)
            assert pen1.value == pen2.value

    def test_decomposed_geometry_applies_transform(self):
        import math

        font = save_and_reload(build_minimal_font())
        pen = DecomposingRecordingPen(font.getGlyphSet())
        font.getGlyphSet()["composite"].draw(pen)
        angle = math.radians(45)
        expected = [
            (
                x * math.cos(angle) - y * math.sin(angle) + 100,
                x * math.sin(angle) + y * math.cos(angle) + 50,
            )
            for (x, y) in [(0, 0), (200, 0), (100, 250)]
        ]
        points = [
            point
            for op in pen.value
            if op[0] in ("moveTo", "lineTo")
            for point in op[1]
        ]
        for ex, ey in expected:
            assert any(
                ax == pytest.approx(ex, abs=1e-9)
                and ay == pytest.approx(ey, abs=1e-9)
                for ax, ay in points
            )

    def test_nested_components_resolve(self):
        font = save_and_reload(build_minimal_font())
        pen = RecordingPen()
        font.getGlyphSet()["nested"].draw(pen)
        assert [entry[1][0] for entry in pen.value] == ["composite", "stem"]
        # The nested reference carries the reset flag and its own location.
        nested = font["VARC"].table.VarCompositeGlyphs.VarCompositeGlyph[1]
        component = nested.components[0]
        assert component.flags & VarComponentFlags.RESET_UNSPECIFIED_AXES
        assert component.axisValues == (-0.25, 0.75)

    def test_ttx_roundtrip(self):
        font = build_minimal_font()
        xml = io.StringIO()
        font.saveXML(xml)
        xml.seek(0)
        reimported = TTFont()
        reimported.importXML(xml)
        for name in ("composite", "nested"):
            pen1, pen2 = RecordingPen(), RecordingPen()
            font.getGlyphSet()[name].draw(pen1)
            reimported.getGlyphSet()[name].draw(pen2)
            assert pen1.value == pen2.value

    def test_deterministic_binary_output(self):
        blob1 = io.BytesIO()
        build_minimal_font().save(blob1)
        blob2 = io.BytesIO()
        build_minimal_font().save(blob2)
        assert blob1.getvalue() == blob2.getvalue()

    def test_unknown_component_glyph_raises(self):
        font = build_minimal_font()
        pen = TTGlyphPen(None)
        pen.addVarComponent("phantom", DecomposedTransform(), {})
        add_glyph(font, "x", pen.glyph())
        with pytest.raises(PenError, match="unknown glyph 'phantom'"):
            buildVARC(font)

    def test_unknown_axis_raises(self):
        font = build_minimal_font()
        pen = TTGlyphPen(font.getGlyphSet())
        pen.addVarComponent("box", DecomposedTransform(), {"slnt": 0.3})
        add_glyph(font, "bad", pen.glyph())
        with pytest.raises(PenError, match="unknown axis"):
            buildVARC(font)

    def test_location_outside_f2dot14_raises(self):
        font = build_minimal_font()
        pen = TTGlyphPen(font.getGlyphSet())
        pen.addVarComponent("box", DecomposedTransform(), {"wght": 2.5})
        add_glyph(font, "bad", pen.glyph())
        with pytest.raises(PenError, match="F2Dot14"):
            buildVARC(font)

    def test_non_numeric_location_raises(self):
        font = build_minimal_font()
        pen = TTGlyphPen(font.getGlyphSet())
        pen.addVarComponent("box", DecomposedTransform(), {"wght": "heavy"})
        add_glyph(font, "bad", pen.glyph())
        with pytest.raises(PenError, match="number"):
            buildVARC(font)

    def test_boolean_location_raises(self):
        font = build_minimal_font()
        pen = TTGlyphPen(font.getGlyphSet())
        pen.addVarComponent("box", DecomposedTransform(), {"wght": True})
        add_glyph(font, "bad", pen.glyph())
        with pytest.raises(PenError, match="number"):
            buildVARC(font)

    def test_non_finite_location_raises(self):
        font = build_minimal_font()
        pen = TTGlyphPen(font.getGlyphSet())
        pen.addVarComponent("box", DecomposedTransform(), {"wght": float("nan")})
        add_glyph(font, "bad", pen.glyph())
        with pytest.raises(PenError, match="finite"):
            buildVARC(font)

    def test_missing_fvar_raises(self):
        font = build_minimal_font()
        del font["fvar"]
        with pytest.raises(PenError, match="fvar"):
            buildVARC(font)

    def test_no_variable_components_raises(self):
        font = build_minimal_font()
        for name in font.getGlyphOrder():
            glyph = font["glyf"][name]
            if hasattr(glyph, "varComponents"):
                del glyph.varComponents
        del font["VARC"]
        with pytest.raises(PenError, match="No glyphs"):
            buildVARC(font)

    def test_rebuild_after_resolution(self):
        # Components whose location has already been resolved into axis
        # indices can still be rebuilt.
        font = build_minimal_font()
        for name in font["VARC"].table.Coverage.glyphs:
            for component in font["glyf"][name].varComponents:
                del component.location
        buildVARC(font)
        reloaded = save_and_reload(font)
        assert reloaded["VARC"].table.Coverage.glyphs == [
            "composite",
            "nested",
        ]

    def test_explicit_scale_y_roundtrips(self):
        font = build_minimal_font()
        pen = TTGlyphPen(font.getGlyphSet())
        pen.addVarComponent(
            "box",
            DecomposedTransform(scaleX=2.0, scaleY=3.0),
            {"wght": 0.1},
        )
        font["glyf"]["composite"] = pen.glyph()
        buildVARC(font)
        reloaded = save_and_reload(font)
        component = reloaded["VARC"].table.VarCompositeGlyphs.VarCompositeGlyph[
            0
        ].components[0]
        assert component.transform.scaleX == 2.0
        assert component.transform.scaleY == 3.0

    def test_glyph_is_var_composite(self):
        font = build_minimal_font()
        assert font["glyf"]["composite"].isVarComposite()
        assert font["glyf"]["nested"].isVarComposite()
        assert not font["glyf"]["box"].isVarComposite()
        assert not font["glyf"][".notdef"].isVarComposite()

    def test_compact_preserves_var_components(self):
        font = build_minimal_font()
        glyf = font["glyf"]
        glyph = glyf["composite"]
        glyph.compact(glyf, recalcBBoxes=False)
        assert glyph.isVarComposite()
        glyph.expand(glyf)
        assert glyph.isVarComposite()
        # The VARC table can still be rebuilt after a compact/expand cycle.
        buildVARC(font)
        reloaded = save_and_reload(font)
        pen = RecordingPen()
        reloaded.getGlyphSet()["composite"].draw(pen)
        assert [entry[1][0] for entry in pen.value] == ["box", "leaf"]
