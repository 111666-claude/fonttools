import io
import os
from io import StringIO

import pytest

from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.beyond64k import upper_tables
from fontTools.varLib.errors import VarLibValidationError
from fontTools.varLib.hvar import add_HVAR, add_VVAR
from fontTools.varLib.varStore import VarStoreInstancer

CWD = os.path.abspath(os.path.dirname(__file__))
DATADIR = os.path.join(CWD, "data")
CFF2_VF_TTX = os.path.join(DATADIR, "..", "instancer", "data", "CFF2Instancer-VF-3.ttx")
MUTATOR_TTX = os.path.join(DATADIR, "MutatorSans_All_Variable.ttx")


def _load_cff2_font():
    font = TTFont()
    font.importXML(CFF2_VF_TTX)
    del font["VVAR"]
    return font


def _vorg_at(font, glyphName, location):
    """Interpolate the vertical origin of a glyph at a normalized location."""
    vvar = font["VVAR"].table
    instancer = VarStoreInstancer(vvar.VarStore, font["fvar"].axes)
    instancer.setLocation(location)
    delta = instancer[vvar.VOrgMap.mapping[glyphName]]
    return font["VORG"][glyphName] + delta


def test_roundtrip():
    ttx_path = os.path.join(DATADIR, "MutatorSans_All_Variable.ttx")
    font = TTFont()
    font.importXML(ttx_path)

    HVAR1 = StringIO()
    font.saveXML(HVAR1, tables=["HVAR"])

    del font["HVAR"]
    add_HVAR(font)

    HVAR2 = StringIO()
    font.saveXML(HVAR2, tables=["HVAR"])

    assert HVAR1.getvalue() == HVAR2.getvalue()


def test_roundtrip_beyond64k_gvar():
    ttx_path = os.path.join(DATADIR, "MutatorSans_All_Variable.ttx")
    font = TTFont()
    font.importXML(ttx_path)

    upper_tables(font)
    del font["HVAR"]
    add_HVAR(font)

    assert "GVAR" in font
    assert "gvar" not in font

    HVAR = StringIO()
    font.saveXML(HVAR, tables=["HVAR"])
    assert "<HVAR>" in HVAR.getvalue()


def test_add_VVAR_no_samples_builds_no_VOrgMap_cff2():
    # CFF2 variable fonts have no gvar; without samples the old behavior is
    # preserved: building VVAR is impossible (no phantom points) and no
    # VOrgMap machinery is introduced.
    font = _load_cff2_font()
    with pytest.raises(KeyError, match="gvar"):
        add_VVAR(font)
    assert "VVAR" not in font


def test_add_VVAR_vOrg_samples_cff2_default_endpoints_midpoint():
    font = _load_cff2_font()
    glyphOrder = font.getGlyphOrder()
    assert glyphOrder == [".notdef", "uni6868"]

    # The font's VORG only has a default, no explicit records.
    assert font["VORG"].VOriginRecords == {}
    assert font["VORG"].defaultVertOriginY == 880

    samples = [
        # uni6868 is not measured at the negative endpoint, so it falls back
        # to the VORG default there (sparse sample).
        ({"wght": -1.0}, {".notdef": 860}),
        ({"wght": 1.0}, {".notdef": 900, "uni6868": 700}),
    ]
    add_VVAR(font, samples)

    vvar = font["VVAR"].table
    assert vvar.VOrgMap is not None
    assert set(vvar.VOrgMap.mapping) == set(glyphOrder)
    # No gvar means no vertical-advance variations.
    assert vvar.AdvHeightMap is not None

    # Independently hand-computed expectations: piecewise-linear interpolation
    # between the sampled masters, with 880 as the default-location base.
    expected = {
        ".notdef": {
            ("wght", -1.0): 860,
            ("wght", -0.5): 870,
            ("wght", 0.0): 880,
            ("wght", 0.5): 890,
            ("wght", 1.0): 900,
        },
        "uni6868": {
            ("wght", -1.0): 880,  # unmeasured -> VORG default
            ("wght", -0.5): 880,
            ("wght", 0.0): 880,
            ("wght", 0.5): 790,
            ("wght", 1.0): 700,
        },
    }
    for glyphName, points in expected.items():
        for (axisTag, coord), want in points.items():
            got = _vorg_at(font, glyphName, {axisTag: coord})
            assert got == pytest.approx(want), (glyphName, coord, got, want)

    # The default location must reproduce the VORG table exactly.
    for glyphName in glyphOrder:
        assert _vorg_at(font, glyphName, {}) == font["VORG"][glyphName]


def test_add_VVAR_vOrg_samples_save_reload_roundtrip():
    font = _load_cff2_font()
    samples = [
        ({"wght": -1.0}, {".notdef": 860}),
        ({"wght": 1.0}, {".notdef": 900, "uni6868": 700}),
    ]
    add_VVAR(font, samples)

    buf = io.BytesIO()
    font.save(buf)
    buf.seek(0)
    reloaded = TTFont(buf)

    assert reloaded["VVAR"].table.VOrgMap.mapping == font["VVAR"].table.VOrgMap.mapping

    # Re-check the interpolated origins on the reloaded font against an
    # independent hand calculation.
    hand = {
        ".notdef": lambda w: 880 + (20 if w >= 0 else -20) * abs(w),
        "uni6868": lambda w: 880 - 180 * max(w, 0.0),
    }
    for glyphName, formula in hand.items():
        for w in (-1.0, -0.5, 0.0, 0.25, 0.5, 0.75, 1.0):
            got = _vorg_at(reloaded, glyphName, {"wght": w})
            assert got == pytest.approx(formula(w)), (glyphName, w, got)


def test_add_VVAR_vOrg_samples_explicit_records_vs_default():
    font = _load_cff2_font()
    # An explicit record equal to the VORG default, and one different.
    font["VORG"].VOriginRecords = {".notdef": 880, "uni6868": 750}
    assert font["VORG"][".notdef"] == 880
    assert font["VORG"]["uni6868"] == 750

    samples = [
        # None means "use the VORG default" at this location, even for a glyph
        # with an explicit base record.
        ({"wght": -1.0}, {".notdef": None, "uni6868": 700}),
        # uni6868 unmeasured here: its sub-model excludes this master.
        ({"wght": 1.0}, {".notdef": 900}),
    ]
    add_VVAR(font, samples)

    assert _vorg_at(font, ".notdef", {"wght": -1.0}) == 880
    assert _vorg_at(font, ".notdef", {}) == 880
    assert _vorg_at(font, ".notdef", {"wght": 1.0}) == 900
    assert _vorg_at(font, "uni6868", {"wght": -1.0}) == 700
    assert _vorg_at(font, "uni6868", {}) == 750
    # No sample at +1 -> stays at the explicit base value.
    assert _vorg_at(font, "uni6868", {"wght": 1.0}) == 750


def test_add_VVAR_vOrg_samples_none_value_equals_missing_glyph():
    font = _load_cff2_font()
    samples_a = [
        ({"wght": -1.0}, {".notdef": 860}),
        ({"wght": 1.0}, {".notdef": 900, "uni6868": None}),
    ]
    add_VVAR(font, samples_a)
    map_a = dict(font["VVAR"].table.VOrgMap.mapping)

    font = _load_cff2_font()
    samples_b = [
        ({"wght": -1.0}, {".notdef": 860}),
        ({"wght": 1.0}, {".notdef": 900}),
    ]
    add_VVAR(font, samples_b)
    map_b = font["VVAR"].table.VOrgMap.mapping
    assert map_a == map_b


def test_add_VVAR_vOrg_samples_multi_axis_gvar_font():
    # TrueType (glyf/gvar) path: advances stay gvar-driven and the sampled
    # VOrgMap is built on top; two axes including a corner location.
    font = TTFont()
    font.importXML(MUTATOR_TTX)
    glyphOrder = font.getGlyphOrder()
    glyph = glyphOrder[2]  # "A"

    vorg = newTable("VORG")
    vorg.majorVersion, vorg.minorVersion = 1, 0
    vorg.defaultVertOriginY = 800
    vorg.VOriginRecords = {glyph: 700}
    font["VORG"] = vorg

    vhea = newTable("vhea")
    vhea.tableVersion = 0x00011000
    vhea.ascent, vhea.descent, vhea.lineGap = 500, -500, 0
    vhea.advanceHeightMax = 1000
    vhea.minTopSideBearing = 0
    vhea.minBottomSideBearing = 0
    vhea.yMaxExtent = 1000
    vhea.caretSlopeRise, vhea.caretSlopeRun, vhea.caretOffset = 1, 0, 0
    vhea.reserved1 = vhea.reserved2 = vhea.reserved3 = vhea.reserved4 = 0
    vhea.metricDataFormat = 0
    vhea.numberOfVMetrics = 1
    font["vhea"] = vhea

    vmtx = newTable("vmtx")
    vmtx.metrics = {name: (1000, 0) for name in glyphOrder}
    font["vmtx"] = vmtx

    samples = [
        ({"wght": 1.0}, {glyph: 720}),
        ({"wdth": 1.0}, {glyph: 740}),
        ({"wght": 1.0, "wdth": 1.0}, {glyph: 760}),
    ]
    add_VVAR(font, samples)

    vvar = font["VVAR"].table
    assert vvar.VOrgMap is not None
    assert vvar.AdvHeightMap is not None

    assert _vorg_at(font, glyph, {}) == 700
    assert _vorg_at(font, glyph, {"wght": 1.0}) == 720
    assert _vorg_at(font, glyph, {"wdth": 1.0}) == 740
    assert _vorg_at(font, glyph, {"wght": 1.0, "wdth": 1.0}) == 760
    assert _vorg_at(font, glyph, {"wght": 0.5, "wdth": 0.5}) == 730
    # A glyph without samples stays at the VORG default everywhere.
    assert _vorg_at(font, ".notdef", {"wght": 1.0, "wdth": 1.0}) == 800


@pytest.mark.parametrize(
    "samples, message",
    [
        # Unknown axis tag.
        ([({"wdth": 1.0}, {".notdef": 900})], "unknown axis"),
        # Glyph not in the font.
        ([({"wght": 1.0}, {"bogus": 900})], "not in the font"),
        # Duplicated sample location.
        (
            [
                ({"wght": 1.0}, {".notdef": 900}),
                ({"wght": 1.0}, {".notdef": 910}),
            ],
            "duplicated location",
        ),
        # Only default-location samples.
        ([({}, {".notdef": 900})], "at least one non-default"),
        # Empty sample list.
        ([], "at least one non-default"),
        # Non-numeric origin value.
        ([({"wght": 1.0}, {".notdef": "900"})], "must be a number or None"),
        # Default-location sample conflicting with the VORG table.
        (
            [
                ({}, {".notdef": 900}),
                ({"wght": 1.0}, {".notdef": 910}),
            ],
            "conflicts with the VORG",
        ),
    ],
)
def test_add_VVAR_vOrg_samples_validation(samples, message):
    font = _load_cff2_font()
    with pytest.raises(VarLibValidationError, match=message):
        add_VVAR(font, samples)


def test_add_VVAR_vOrg_samples_without_VORG_table():
    font = _load_cff2_font()
    del font["VORG"]
    with pytest.raises(VarLibValidationError, match="without a VORG table"):
        add_VVAR(font, [({"wght": 1.0}, {".notdef": 900})])


def test_add_VVAR_vOrg_samples_agreeing_default_accepted():
    font = _load_cff2_font()
    # 880 equals the VORG default that applies to .notdef: accepted.
    add_VVAR(
        font,
        [
            ({}, {".notdef": 880}),
            ({"wght": 1.0}, {".notdef": 900}),
        ],
    )
    assert "VVAR" in font
    assert font["VVAR"].table.VOrgMap is not None
    assert _vorg_at(font, ".notdef", {"wght": 1.0}) == 900
