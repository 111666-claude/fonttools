import pytest

from fontTools.misc.transform import DecomposedTransform
from fontTools.pens.basePen import MissingComponentError, PenError
from fontTools.pens.recordingPen import RecordingPen, RecordingPointPen
from fontTools.pens.ttGlyphPen import TTGlyphPen, TTGlyphPointPen
from fontTools.ttLib.tables.otTables import VarComponentFlags


class _Glyph:
    pass


GLYPH_SET = {"a": _Glyph(), "b": _Glyph()}


class VarComponentPenTestBase:
    penClass = None

    def _pen(self, glyphSet=GLYPH_SET):
        return self.penClass(glyphSet)

    def test_var_component_stored_on_glyph(self):
        pen = self._pen()
        pen.addVarComponent(
            "a",
            DecomposedTransform(translateX=10, scaleX=1.5),
            {"wght": 0.5},
        )
        glyph = pen.glyph()
        assert glyph.numberOfContours == 0
        assert len(glyph.varComponents) == 1
        component = glyph.varComponents[0]
        assert component.glyphName == "a"
        assert component.transform.translateX == 10
        assert component.transform.scaleX == 1.5
        assert component.location == {"wght": 0.5}

    def test_reset_unspecified_axes_flag(self):
        pen = self._pen()
        pen.addVarComponent(
            "a", DecomposedTransform(), {}, resetUnspecifiedAxes=True
        )
        component = pen.glyph().varComponents[0]
        assert component.flags & VarComponentFlags.RESET_UNSPECIFIED_AXES

    def test_reset_unspecified_axes_default_off(self):
        pen = self._pen()
        pen.addVarComponent("a", DecomposedTransform(), {})
        component = pen.glyph().varComponents[0]
        assert not (component.flags & VarComponentFlags.RESET_UNSPECIFIED_AXES)

    def test_multiple_var_components(self):
        pen = self._pen()
        pen.addVarComponent("a", DecomposedTransform(translateX=1), {"wght": 0})
        pen.addVarComponent("b", DecomposedTransform(translateX=2), {"wght": 1})
        glyph = pen.glyph()
        assert [c.glyphName for c in glyph.varComponents] == ["a", "b"]

    def test_missing_component_raises(self):
        pen = self._pen()
        with pytest.raises(MissingComponentError):
            pen.addVarComponent("ghost", DecomposedTransform(), {})

    def test_none_glyph_set_skips_name_check(self):
        pen = self.penClass(None)
        pen.addVarComponent("ghost", DecomposedTransform(), {})
        assert pen.glyph().varComponents[0].glyphName == "ghost"

    def test_transform_must_be_decomposed(self):
        pen = self._pen()
        with pytest.raises(PenError, match="DecomposedTransform"):
            pen.addVarComponent("a", (1, 0, 0, 1, 0, 0), {})

    def test_location_must_be_dict(self):
        pen = self._pen()
        with pytest.raises(PenError, match="dict"):
            pen.addVarComponent("a", DecomposedTransform(), [("wght", 0.5)])

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"translateX": 32768},
            {"translateY": -32769},
            {"tCenterX": 40000},
            {"rotation": 8.0 * 180},
            {"scaleX": 32.0},
            {"skewX": -8.0 * 180 - 180.0 / 4096},
        ],
    )
    def test_unencodable_transform_raises(self, kwargs):
        pen = self._pen()
        with pytest.raises(PenError, match="cannot be encoded"):
            pen.addVarComponent("a", DecomposedTransform(**kwargs), {})

    def test_non_finite_transform_raises(self):
        pen = self._pen()
        with pytest.raises(PenError, match="finite"):
            pen.addVarComponent("a", DecomposedTransform(rotation=float("nan")), {})

    def test_transform_int16_boundaries_accepted(self):
        pen = self._pen()
        pen.addVarComponent(
            "a",
            DecomposedTransform(translateX=32767, translateY=-32768),
            {},
        )
        transform = pen.glyph().varComponents[0].transform
        assert transform.translateX == 32767
        assert transform.translateY == -32768

    def test_contour_then_var_component_raises(self):
        pen = self._pen()
        if self.penClass is TTGlyphPen:
            pen.moveTo((0, 0))
            pen.lineTo((1, 0))
            pen.lineTo((1, 1))
            pen.closePath()
        else:
            pen.beginPath()
            pen.addPoint((0, 0), "line")
            pen.addPoint((1, 1), "line")
            pen.endPath()
        with pytest.raises(PenError, match="mix"):
            pen.addVarComponent("a", DecomposedTransform(), {})

    def test_var_component_then_contour_raises(self):
        pen = self._pen()
        pen.addVarComponent("a", DecomposedTransform(), {})
        with pytest.raises(PenError, match="mix"):
            if self.penClass is TTGlyphPen:
                pen.moveTo((0, 0))
            else:
                pen.beginPath()

    def test_var_component_then_component_raises(self):
        pen = self._pen()
        pen.addVarComponent("a", DecomposedTransform(), {})
        with pytest.raises(PenError, match="mix"):
            pen.addComponent("a", (1, 0, 0, 1, 0, 0))

    def test_component_then_var_component_raises(self):
        pen = self._pen()
        pen.addComponent("a", (1, 0, 0, 1, 0, 0))
        with pytest.raises(PenError, match="mix"):
            pen.addVarComponent("a", DecomposedTransform(), {})

    def test_recording_replay_roundtrip(self):
        if self.penClass is TTGlyphPen:
            recording = RecordingPen()
        else:
            recording = RecordingPointPen()
        recording.addVarComponent(
            "a",
            DecomposedTransform(translateX=3, rotation=45),
            {"wght": 1.0},
            resetUnspecifiedAxes=True,
        )
        pen = self._pen()
        recording.replay(pen)
        component = pen.glyph().varComponents[0]
        assert component.glyphName == "a"
        assert component.location == {"wght": 1.0}
        assert component.transform.translateX == 3
        assert component.transform.rotation == 45
        assert component.flags & VarComponentFlags.RESET_UNSPECIFIED_AXES

    def test_ordinary_outlines_unaffected(self):
        pen = self.penClass(None)
        if self.penClass is TTGlyphPen:
            pen.moveTo((0, 0))
            pen.lineTo((10, 0))
            pen.lineTo((10, 10))
            pen.closePath()
        else:
            pen.beginPath()
            pen.addPoint((0, 0), "line")
            pen.addPoint((10, 0), "line")
            pen.addPoint((10, 10), "line")
            pen.endPath()
        glyph = pen.glyph()
        assert glyph.numberOfContours == 1
        assert not hasattr(glyph, "varComponents")

    def test_ordinary_component_unaffected(self):
        pen = self._pen()
        pen.addComponent("a", (1, 0, 0, 1, 5, 7))
        glyph = pen.glyph()
        assert glyph.isComposite()
        assert glyph.components[0].glyphName == "a"
        assert (glyph.components[0].x, glyph.components[0].y) == (5, 7)
        assert not hasattr(glyph, "varComponents")


class TestTTGlyphPenVarComponent(VarComponentPenTestBase):
    penClass = TTGlyphPen


class TestTTGlyphPointPenVarComponent(VarComponentPenTestBase):
    penClass = TTGlyphPointPen
