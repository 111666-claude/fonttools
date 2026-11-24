from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables._f_v_a_r import Axis
from fontTools.varLib.avar.build import build
from fontTools.varLib.avar.map import map as map_avar, main as map_main
from fontTools.varLib.models import VariationModel
from fontTools.varLib.avar.unbuild import _pruneLocations, mappings_from_avar, unbuild
from io import StringIO
from pathlib import Path
import os
import unittest
import pytest

TESTS = [
    (
        [
            {"wght": 1},
            {"wght": 0.5},
        ],
        [
            {"wght": 0.5},
        ],
        [
            {"wght": 0.5},
        ],
    ),
    (
        [
            {"wght": 1, "wdth": 1},
            {"wght": 0.5, "wdth": 1},
        ],
        [
            {"wght": 1, "wdth": 1},
        ],
        [
            {"wght": 1, "wdth": 1},
            {"wght": 0.5, "wdth": 1},
        ],
    ),
    (
        [
            {"wght": 1},
            {"wdth": 1},
            {"wght": 0.5, "wdth": 0.5},
        ],
        [
            {"wght": 0.5, "wdth": 0.5},
        ],
        [
            {"wght": 0.5, "wdth": 0.5},
        ],
    ),
]


@pytest.mark.parametrize("locations, poles, expected", TESTS)
def test_pruneLocations(locations, poles, expected):
    axisTags = set()
    for location in locations:
        axisTags.update(location.keys())
    axisTags = sorted(axisTags)

    locations = [{}] + locations

    pruned = _pruneLocations(locations, poles, axisTags)

    assert pruned == expected, (pruned, expected)


@pytest.mark.parametrize("locations, poles, expected", TESTS)
def test_roundtrip(locations, poles, expected):
    axisTags = set()
    for location in locations:
        axisTags.update(location.keys())
    axisTags = sorted(axisTags)

    locations = [{}] + locations
    expected = [{}] + expected

    model1 = VariationModel(locations, axisTags)
    model2 = VariationModel(expected, axisTags)

    for location in poles:
        i = model1.locations.index(location)
        support1 = model1.supports[i]

        i = model2.locations.index(location)
        support2 = model2.supports[i]

        assert support1 == support2, (support1, support2)


def test_mappings_from_avar():
    CWD = os.path.abspath(os.path.dirname(__file__))
    DATADIR = os.path.join(CWD, "..", "ttLib", "tables", "data")
    varfont_path = os.path.join(DATADIR, "Amstelvar-avar2.subset.ttf")
    font = TTFont(varfont_path)
    mappings = mappings_from_avar(font)

    assert len(mappings) == 2, mappings


def test_mappings_from_avar_without_avar_table():
    font = TTFont()
    font["fvar"] = newTable("fvar")
    font["fvar"].axes = []

    axis_maps, mappings = mappings_from_avar(font)

    assert axis_maps == {}
    assert mappings == []


def test_unbuild_falls_back_to_axis_tag_when_name_missing():
    font = TTFont()
    font["fvar"] = newTable("fvar")
    axis = Axis()
    axis.axisTag = "wght"
    axis.axisNameID = 999
    axis.minValue = 100
    axis.defaultValue = 400
    axis.maxValue = 900
    font["fvar"].axes = [axis]
    font["name"] = newTable("name")

    output = StringIO()
    unbuild(font, output)

    assert 'name="wght"' in output.getvalue()


def test_map_rejects_unknown_axis():
    font = TTFont()
    font["fvar"] = newTable("fvar")
    axis = Axis()
    axis.axisTag = "wght"
    axis.axisNameID = 256
    axis.minValue = 100
    axis.defaultValue = 400
    axis.maxValue = 900
    font["fvar"].axes = [axis]

    with pytest.raises(ValueError, match="Unknown axis tag"):
        map_avar(font, {"wdth": 100})


# Fixed axis table shared by the default-position tests below: two visible
# axes plus a hidden one, with a non-identity avar1 segment on "wght".
FIXED_AXES = [
    # tag, min, default, max, flags
    ("wght", 100, 400, 900, 0),
    ("wdth", 50, 100, 125, 0),
    ("XXXX", 0, 0, 1, 0x0002),  # hidden axis
]
FIXED_DEFAULT_LOCATION = {"wght": 400.0, "wdth": 100.0, "XXXX": 0.0}

AVAR2_TEST_FONT = os.path.join(
    os.path.abspath(os.path.dirname(__file__)),
    "..",
    "ttLib",
    "tables",
    "data",
    "Amstelvar-avar2.subset.ttf",
)


def make_fixed_axis_font():
    font = TTFont()
    fvar = newTable("fvar")
    fvar.axes = []
    for tag, minValue, defaultValue, maxValue, flags in FIXED_AXES:
        axis = Axis()
        axis.axisTag = tag
        axis.axisNameID = 256
        axis.minValue = minValue
        axis.defaultValue = defaultValue
        axis.maxValue = maxValue
        axis.flags = flags
        fvar.axes.append(axis)
    font["fvar"] = fvar
    avar = newTable("avar")
    avar.segments = {
        "wght": {-1.0: -1.0, 0.0: 0.0, 0.5: 0.7, 1.0: 1.0},
        "wdth": {-1.0: -1.0, 0.0: 0.0, 1.0: 1.0},
        "XXXX": {-1.0: -1.0, 0.0: 0.0, 1.0: 1.0},
    }
    font["avar"] = avar
    return font


def test_map_default_position_empty_sparse_and_full_input():
    # Empty, sparse and full inputs all denote the same default position,
    # in user coordinates as well as in normalized coordinates; omitted
    # axes (including hidden ones) are filled with their defaults.
    font = make_fixed_axis_font()
    expected = dict(FIXED_DEFAULT_LOCATION)

    assert map_avar(font, {}) == expected
    assert map_avar(font, {}, inputNormalized=True) == expected
    assert map_avar(font, {"wght": 400}) == expected
    assert map_avar(font, {"wght": 0}, inputNormalized=True) == expected
    assert map_avar(font, dict(FIXED_DEFAULT_LOCATION)) == expected
    assert map_avar(font, {"wght": 0, "wdth": 0, "XXXX": 0}, inputNormalized=True) == (
        expected
    )


def test_map_default_position_normalized_output():
    font = make_fixed_axis_font()
    expected = {"wght": 0.0, "wdth": 0.0, "XXXX": 0.0}

    assert map_avar(font, {}, outputNormalized=True) == expected
    assert map_avar(font, {}, inputNormalized=True, outputNormalized=True) == expected


def test_map_dropZeroes_only_when_requested():
    font = make_fixed_axis_font()

    # Zero values are kept by default ...
    assert map_avar(font, {}) == dict(FIXED_DEFAULT_LOCATION)
    # ... and omitted only under the explicit option, for empty and
    # sparse input alike.
    assert map_avar(font, {}, dropZeroes=True) == {}
    assert map_avar(font, {"wght": 400}, dropZeroes=True) == {}
    assert map_avar(font, {"wght": 650}, dropZeroes=True) == {"wght": 750.0}


def test_map_non_default_positions_unchanged():
    # Filling defaults must not alter the mapping of non-default positions:
    # wght=650 normalizes to 0.5, which the avar segment maps to 0.7,
    # denormalizing to 750.
    font = make_fixed_axis_font()

    assert map_avar(font, {"wght": 650}) == {
        "wght": 750.0,
        "wdth": 100.0,
        "XXXX": 0.0,
    }
    assert map_avar(font, {"wght": 0.5}, inputNormalized=True) == {
        "wght": 750.0,
        "wdth": 100.0,
        "XXXX": 0.0,
    }
    assert map_avar(font, {"wght": 650}, outputNormalized=True) == {
        "wght": 0.7,
        "wdth": 0.0,
        "XXXX": 0.0,
    }


def test_map_default_position_avar2():
    # avar2 fonts follow the same default-position semantics as avar1.
    font = TTFont(AVAR2_TEST_FONT)
    expected = {a.axisTag: float(a.defaultValue) for a in font["fvar"].axes}

    assert map_avar(font, {}) == expected
    assert map_avar(font, {}, inputNormalized=True) == expected
    assert map_avar(font, {"wght": 400}) == expected
    assert map_avar(font, expected) == expected
    assert map_avar(font, {}, dropZeroes=True) == {}


def parse_cli_output(output):
    location = {}
    for line in output.splitlines():
        tag, sep, value = line.partition("=")
        assert sep
        location[tag] = float(value)
    return location


def test_map_main_matches_library(tmp_path, capsys):
    font = make_fixed_axis_font()
    font_path = tmp_path / "Test.ttf"
    font.save(font_path)
    # Reload so the library result goes through the same F2Dot14
    # quantization of the avar segments as the CLI's font.
    font = TTFont(font_path)

    # Empty input: CLI and library agree on the default position.
    # (The CLI prints with %g precision, so compare approximately.)
    map_main([str(font_path), "-f"])
    assert parse_cli_output(capsys.readouterr().out) == pytest.approx(
        map_avar(font, {})
    )

    # Without -f, default-position zeroes are omitted.
    map_main([str(font_path)])
    assert capsys.readouterr().out == ""

    # Sparse and full input, user and normalized coordinates.
    for args, location, kwargs in [
        (["wght=650"], {"wght": 650}, {}),
        (["wght=650", "wdth=100", "XXXX=0"], {"wght": 650}, {}),
        (["-i", "-o", "wght=0.5"], {"wght": 0.5}, {"inputNormalized": True}),
    ]:
        map_main([str(font_path), "-f"] + args)
        assert parse_cli_output(capsys.readouterr().out) == pytest.approx(
            map_avar(font, location, outputNormalized="-o" in args, **kwargs)
        )


def test_map_default_position_avar2_cli(capsys):
    font = TTFont(AVAR2_TEST_FONT)

    map_main([AVAR2_TEST_FONT, "-f"])
    assert parse_cli_output(capsys.readouterr().out) == pytest.approx(map_avar(font, {}))


def test_map_default_location_instantiates_default_outlines():
    # Instantiating at the mapped default location must reproduce the
    # font's default outlines, however the location was specified.
    from fontTools.varLib.instancer import instantiateVariableFont

    mapped = map_avar(TTFont(AVAR2_TEST_FONT), {})
    assert mapped == map_avar(TTFont(AVAR2_TEST_FONT), {"wght": 400})

    inst = instantiateVariableFont(TTFont(AVAR2_TEST_FONT), mapped)
    default = TTFont(AVAR2_TEST_FONT)

    for glyph_name in default.getGlyphOrder():
        g_default = default["glyf"][glyph_name]
        g_inst = inst["glyf"][glyph_name]
        if hasattr(g_default, "coordinates"):
            assert list(g_inst.coordinates) == list(g_default.coordinates)
        else:
            assert g_inst.isComposite() == g_default.isComposite()
            if g_default.isComposite():
                assert [
                    (c.glyphName, c.x, c.y) for c in g_inst.components
                ] == [(c.glyphName, c.x, c.y) for c in g_default.components]


def test_map_main_rejects_malformed_coordinate(tmp_path):
    designspace = Path(tmp_path) / "Test.designspace"
    designspace.write_text(
        """\
<?xml version='1.0' encoding='UTF-8'?>
<designspace format="5.0">
  <axes>
    <axis tag="wght" name="Weight" minimum="100" maximum="900" default="400"/>
  </axes>
</designspace>
""",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="2"):
        map_main([str(designspace), "wght"])


def test_build_preserves_existing_name_table(tmp_path):
    designspace = Path(tmp_path) / "Test.designspace"
    designspace.write_text(
        """\
<?xml version='1.0' encoding='UTF-8'?>
<designspace format="5.0">
  <axes>
    <axis tag="wght" name="Weight" minimum="100" maximum="900" default="400"/>
  </axes>
</designspace>
""",
        encoding="utf-8",
    )

    font = TTFont()
    font["name"] = newTable("name")
    font["name"].setName("Existing Name", 320, 3, 1, 0x409)

    build(font, designspace)

    assert font["name"].getDebugName(320) == "Existing Name"


def test_unbuild_escapes_axis_name_in_designspace():
    # Axis names come from the font's 'name' table (untrusted); unbuild writes
    # them into XML attribute values. A name containing markup must not be able
    # to break out of the attribute and inject elements into the designspace.
    from xml.etree import ElementTree

    font = TTFont()
    name = newTable("name")
    name.names = []
    hostile = 'W" /><!DOCTYPE x><axis tag="z'
    name.setName(hostile, 256, 3, 1, 0x409)
    font["name"] = name

    fvar = newTable("fvar")
    axis = Axis()
    axis.axisTag = "wght"
    axis.minValue, axis.defaultValue, axis.maxValue = 100, 400, 900
    axis.axisNameID = 256
    fvar.axes = [axis]
    font["fvar"] = fvar

    buf = StringIO()
    unbuild(font, f=buf)
    out = buf.getvalue()

    # No unescaped markup leaked through
    assert "<!DOCTYPE" not in out
    # Output is well-formed and the hostile string survives as a plain
    # attribute value on the single <axis> element
    root = ElementTree.fromstring(out)
    axes = root.findall(".//axis")
    assert len(axes) == 1
    assert axes[0].get("name") == hostile
