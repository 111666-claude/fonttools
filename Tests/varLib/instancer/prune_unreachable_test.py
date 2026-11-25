"""Tests for the opt-in reachability-based glyph pruning after instancing.

Scenario (task: optional precise cleanup for full instancing):

* ``A.alt`` is referenced only by a conditional ``rvrn`` substitution
  ``A -> A.alt``. Pinning the weight axis below the condition culls the
  FeatureVariations record and prunes the lookup, so ``A.alt`` becomes
  unreachable but is still present unless pruning is enabled.
* ``sharedcomp`` is a component shared by the cmap-mapped ``A`` and ``B``
  composite glyphs; it must survive.
* ``B.alt`` is referenced by a normal, surviving ``ccmp`` substitution and
  must survive.
* ``paintlayer`` is referenced only by a COLR v0 layer and must survive.
"""

import io

import pytest

from fontTools.colorLib.builder import buildCOLR, buildCPAL
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from fontTools.varLib import featureVars
from fontTools.varLib.instancer import (
    instantiateVariableFont,
    pruneUnreachableGlyphs,
)

GLYPH_ORDER = [
    ".notdef",
    "A",
    "A.alt",
    "B",
    "B.alt",
    "sharedcomp",
    "C",
    "paintlayer",
]


def _rect_glyph(x0=100, y0=0, x1=500, y1=700):
    pen = TTGlyphPen(None)
    pen.moveTo((x0, y0))
    pen.lineTo((x0, y1))
    pen.lineTo((x1, y1))
    pen.lineTo((x1, y0))
    pen.closePath()
    return pen.glyph()


def _alt_glyph():
    pen = TTGlyphPen(None)
    pen.moveTo((300, 0))
    pen.lineTo((600, 350))
    pen.lineTo((300, 700))
    pen.lineTo((0, 350))
    pen.closePath()
    return pen.glyph()


def _component_glyph(glyphSet, component, dx=0):
    pen = TTGlyphPen(glyphSet)
    pen.addComponent(component, (1, 0, 0, 1, dx, 0))
    return pen.glyph()


def build_scenario_font():
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder(GLYPH_ORDER)
    fb.setupCharacterMap({0x41: "A", 0x42: "B", 0x43: "C"})

    glyphs = {
        ".notdef": _rect_glyph(x0=50, x1=550, y1=800),
        "A": None,
        "A.alt": _alt_glyph(),
        "B": None,
        "B.alt": _rect_glyph(x0=150, x1=650, y1=720),
        "sharedcomp": _rect_glyph(x0=100, x1=400, y1=700),
        "C": TTGlyphPen(None).glyph(),
        "paintlayer": _rect_glyph(x0=120, x1=520, y0=60, y1=660),
    }
    glyphs["A"] = _component_glyph(glyphs, "sharedcomp")
    glyphs["B"] = _component_glyph(glyphs, "sharedcomp", dx=120)
    fb.setupGlyf(glyphs)

    metrics = {name: (600, 50) for name in GLYPH_ORDER}
    metrics["A"] = (700, 0)
    metrics["B"] = (720, 120)
    metrics["C"] = (640, 60)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "Uid73", "styleName": "Regular"})
    fb.setupOS2(
        sTypoAscender=800,
        sTypoDescender=-200,
        usWinAscent=800,
        usWinDescent=200,
    )
    fb.setupPost()
    fb.setupMaxp()
    fb.setupFvar(
        axes=[("wght", 400, 400, 900, "Weight")],
        instances=[
            dict(location={"wght": 400}, stylename="Regular"),
            dict(location={"wght": 900}, stylename="Black"),
        ],
    )

    font = fb.font

    # Normal substitution that survives every instancing location.
    addOpenTypeFeaturesFromString(
        font,
        """
        languagesystem DFLT dflt;
        languagesystem latn dflt;
        feature ccmp {
            sub B by B.alt;
        } ccmp;
        """,
    )

    # Conditional A -> A.alt for normalized wght in [0.5, 1.0].
    featureVars.addFeatureVariations(
        font,
        [([{"wght": (0.5, 1.0)}], {"A": "A.alt"})],
    )

    # COLR v0 layer referencing paintlayer and nothing else.
    font["COLR"] = buildCOLR({"C": [("paintlayer", 0)]})
    font["CPAL"] = buildCPAL([[(1.0, 0.0, 0.0, 1.0)]])

    return font


def _save_reload(font):
    buf = io.BytesIO()
    font.save(buf)
    buf.seek(0)
    return TTFont(buf)


@pytest.fixture
def scenario_font():
    return build_scenario_font()


class PruneUnreachableGlyphsTest(object):
    def test_default_instancing_keeps_orphan_alternate(self, scenario_font):
        instantiateVariableFont(scenario_font, {"wght": 400}, inplace=True, static=True)
        # Default behavior is unchanged: the culled branch's glyph stays.
        assert scenario_font.getGlyphOrder() == GLYPH_ORDER

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"pruneUnreachableGlyphs": True},
            {"prune_unreachable_glyphs": True},
            {"pruneUnusedGlyphs": True},
            {"prune_unused_glyphs": True},
        ],
    )
    def test_prune_removes_only_conditional_alternate(self, scenario_font, kwargs):
        instantiateVariableFont(
            scenario_font, {"wght": 400}, inplace=True, static=True, **kwargs
        )
        order = scenario_font.getGlyphOrder()

        assert "A.alt" not in order
        for name in (".notdef", "A", "B", "B.alt", "sharedcomp", "C", "paintlayer"):
            assert name in order

        # Relative glyph order of survivors is preserved.
        assert order == [name for name in GLYPH_ORDER if name in order]
        assert len(order) == len(GLYPH_ORDER) - 1

    def test_active_conditional_branch_glyph_is_retained(self, scenario_font):
        # At wght=900 the conditional substitution applies and is merged into
        # the surviving GSUB feature, so A.alt must remain reachable.
        instantiateVariableFont(
            scenario_font,
            {"wght": 900},
            inplace=True,
            static=True,
            pruneUnreachableGlyphs=True,
        )
        assert "A.alt" in scenario_font.getGlyphOrder()

    def test_saved_font_has_valid_indices_and_records(self, scenario_font):
        instantiateVariableFont(
            scenario_font,
            {"wght": 400},
            inplace=True,
            static=True,
            pruneUnreachableGlyphs=True,
        )
        reloaded = _save_reload(scenario_font)
        order = reloaded.getGlyphOrder()

        assert reloaded["maxp"].numGlyphs == len(order)
        assert set(reloaded["glyf"].glyphs.keys()) == set(order)
        assert set(reloaded["hmtx"].metrics.keys()) == set(order)

        # cmap mappings survive and point at surviving glyphs.
        cmap = reloaded.getBestCmap()
        assert cmap == {0x41: "A", 0x42: "B", 0x43: "C"}

        # The composite still references the shared component.
        assert reloaded["glyf"]["A"].isComposite()
        component_names = [g.glyphName for g in reloaded["glyf"]["A"].components]
        assert component_names == ["sharedcomp"]

        # COLR layer reference is remapped but still names paintlayer.
        layers = reloaded["COLR"].ColorLayers["C"]
        assert [layer.name for layer in layers] == ["paintlayer"]

        # The surviving normal substitution is intact.
        mappings = {}
        for lookup in reloaded["GSUB"].table.LookupList.Lookup:
            for subtable in lookup.SubTable:
                mappings.update(getattr(subtable, "mapping", {}))
        assert mappings == {"B": "B.alt"}

    def test_inplace_false_leaves_source_untouched(self, scenario_font):
        result = instantiateVariableFont(
            scenario_font,
            {"wght": 400},
            static=True,
            pruneUnreachableGlyphs=True,
        )
        assert "A.alt" not in result.getGlyphOrder()
        assert "A.alt" in scenario_font.getGlyphOrder()

    def test_helper_function_directly(self, scenario_font):
        instantiateVariableFont(scenario_font, {"wght": 400}, inplace=True, static=True)
        assert "A.alt" in scenario_font.getGlyphOrder()
        pruneUnreachableGlyphs(scenario_font)
        assert "A.alt" not in scenario_font.getGlyphOrder()

    def test_empty_branches_never_drop_shared_component(self, scenario_font):
        # An empty/universal condition branch (or its total absence) must not
        # cause a reference-counting cleanup to delete a shared component.
        # Reachability is computed from the surviving tables themselves, so
        # the emptiest possible "branch" -- no GSUB at all -- is safe: the
        # cmap + composite closure retains the shared component and its users.
        instantiateVariableFont(scenario_font, {"wght": 400}, inplace=True, static=True)
        del scenario_font["GSUB"]
        pruneUnreachableGlyphs(scenario_font)
        order = scenario_font.getGlyphOrder()
        assert "sharedcomp" in order
        assert "A" in order and "B" in order

    def test_empty_lookup_list_keeps_component(self, scenario_font):
        # A present but emptied GSUB (the residue of culled branches) is
        # likewise harmless.
        instantiateVariableFont(scenario_font, {"wght": 400}, inplace=True, static=True)
        scenario_font["GSUB"].table.LookupList.Lookup = []
        scenario_font["GSUB"].table.LookupList.LookupCount = 0
        pruneUnreachableGlyphs(scenario_font)
        order = scenario_font.getGlyphOrder()
        assert "sharedcomp" in order
        assert "A" in order and "B" in order
        # B is cmap-mapped and composite; with ccmp gone it must still shape
        # to B itself rather than disappearing.
        reloaded = _save_reload(scenario_font)
        assert "B" in reloaded.getGlyphOrder()

    def test_font_without_cmap_is_left_alone(self, scenario_font):
        del scenario_font["cmap"]
        before = list(scenario_font.getGlyphOrder())
        pruneUnreachableGlyphs(scenario_font)
        assert scenario_font.getGlyphOrder() == before

    def test_shaping_is_stable_after_pruning(self, scenario_font, tmp_path):
        hb = pytest.importorskip("uharfbuzz")

        def shape(path):
            font = TTFont(path)
            order = font.getGlyphOrder()
            blob = hb.Blob.from_file_path(str(path))
            face = hb.Face(blob)
            hbfont = hb.Font(face)
            buf = hb.Buffer()
            buf.add_str("ABC")
            buf.guess_segment_properties()
            hb.shape(hbfont, buf)
            names = [order[info.codepoint] for info in buf.glyph_infos]
            positions = [
                (pos.x_advance, pos.x_offset, pos.y_offset)
                for pos in buf.glyph_positions
            ]
            return names, positions

        instantiateVariableFont(scenario_font, {"wght": 400}, inplace=True, static=True)
        before_path = tmp_path / "before.ttf"
        scenario_font.save(str(before_path))
        names_before, positions_before = shape(before_path)
        assert names_before == ["A", "B.alt", "C"]

        pruneUnreachableGlyphs(scenario_font)
        after_path = tmp_path / "after.ttf"
        scenario_font.save(str(after_path))
        names_after, positions_after = shape(after_path)

        assert names_after == names_before
        assert positions_after == positions_before
