from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables._f_v_a_r import Axis
from fontTools.varLib.avar.build import build
from fontTools.varLib.avar.map import map as map_avar, main as map_main
from fontTools.varLib.avar.reverse_map import (
    ReverseMapError,
    reverseMap,
    verifySolutions,
    verifyResult,
    main as reverseMap_main,
)
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


# ---------------------------------------------------------------------------
# varLib.avar.reverse_map: single-axis reverse lookup
# ---------------------------------------------------------------------------

# Fixed acceptance mapping (normalized coordinates): one plateau plus a
# non-monotone hump, so a single target can have several distinct preimages.
REVERSE_SEGMENTS = {
    -1.0: -1.0,
    0.0: 0.0,
    0.25: 0.5,
    0.5: 0.5,
    0.75: 0.25,
    1.0: 1.0,
}
WGH_TRIPLET = (100, 400, 900)


def _reverseFont(segments=REVERSE_SEGMENTS, *, avarVersion=1, axes=None):
    font = TTFont()
    fvar = newTable("fvar")
    if axes is None:
        axis = Axis()
        axis.axisTag = "wght"
        axis.axisNameID = 256
        axis.minValue, axis.defaultValue, axis.maxValue = WGH_TRIPLET
        axes = [axis]
    fvar.axes = axes
    font["fvar"] = fvar
    if segments is not None:
        from fontTools.ttLib.tables import otTables

        avar = newTable("avar")
        avar.majorVersion, avar.minorVersion = avarVersion, 0
        avar.segments = {"wght": segments}
        avar.table = otTables.avar()
        avar.table.Reserved = 0
        avar.table.VarIdxMap = None
        avar.table.VarStore = None
        font["avar"] = avar
    return font


def test_reverseMap_normalized_plateau_and_hump_all_forward_check():
    font = _reverseFont()
    result = reverseMap(font, "wght", 0.5, inputNormalized=True, outputNormalized=True)
    assert result.axis == "wght"
    assert result.unit == "normalized"
    assert result.clip is True
    # One interval preimage (the plateau) and one point (the hump crossing).
    assert len(result.intervals) == 1
    assert result.intervals[0].intervalStart == 0.25
    assert result.intervals[0].intervalEnd == 0.5
    assert len(result.points) == 1
    assert result.points[0].value == pytest.approx(5 / 6, abs=1e-12)
    # Solutions are sorted by input position.
    positions = [s.intervalStart if s.isInterval else s.value for s in result.solutions]
    assert positions == sorted(positions)
    # Acceptance criterion: every returned solution forward-maps to the target.
    for _solution, error in verifySolutions(result, REVERSE_SEGMENTS):
        assert error <= 1e-12


def test_reverseMap_user_units_round_trip():
    font = _reverseFont()
    # Normalized target 0.5 -> user target 400 + 0.5 * 500 = 650.
    result = reverseMap(font, "wght", 650)
    assert result.unit == "user"
    assert result.target == 650
    interval = result.intervals[0]
    # normalized [0.25, 0.5] -> user [400+0.25*500, 400+0.5*500]
    assert interval.intervalStart == 525
    assert interval.intervalEnd == 650
    # Font-aware verification re-normalizes user coordinates and applies
    # the real avar segment mapping.
    for _solution, error in verifyResult(font, result):
        assert error <= 1e-9
    # And the normalized view must agree with the user-space view.
    normalized = reverseMap(
        font, "wght", 650, inputNormalized=False, outputNormalized=True
    )
    assert normalized.intervals[0].intervalStart == pytest.approx(0.25)
    assert normalized.intervals[0].intervalEnd == pytest.approx(0.5)


def test_reverseMap_fixed_mapping_every_target_forward_verified():
    """Dense acceptance sweep over the fixed mapping: every solution of
    every reachable target reproduces that target through the forward map."""
    font = _reverseFont()
    grid = [-1.0 + 2 * k / 500 for k in range(501)]
    seen = 0
    for target in grid:
        result = reverseMap(
            font, "wght", target, inputNormalized=True, outputNormalized=True
        )
        assert result.reachable
        for solution, error in verifySolutions(result, REVERSE_SEGMENTS):
            assert error <= 1e-10
            assert solution.explanation
        seen += len(result.solutions)
    assert seen > len(grid)  # the plateau/hump produce extra preimages


def test_reverseMap_unreachable_target_returns_empty_with_reason():
    # Mapping whose image over [-1, 1] is only [-0.5, 0.5]: a target of
    # 0.75 is inside the axis domain but outside the map's output range.
    segments = {-1.0: -0.5, 0.0: 0.0, 1.0: 0.5}
    font = _reverseFont(segments)
    result = reverseMap(font, "wght", 0.75, inputNormalized=True, outputNormalized=True)
    assert not result.reachable
    assert result.solutions == []
    assert "0.75" in result.reason
    assert result.reachableRange == (-0.5, 0.5)
    # The same target becomes reachable via the slope-1 extrapolation tail.
    extrap = reverseMap(
        font,
        "wght",
        0.75,
        inputNormalized=True,
        outputNormalized=True,
        clip=False,
    )
    assert extrap.reachable and extrap.points


def test_reverseMap_clip_false_inverts_extrapolation_tails():
    font = _reverseFont({-1.0: -1.0, 0.0: 0.0, 1.0: 1.0})
    result = reverseMap(
        font,
        "wght",
        1.5,
        inputNormalized=True,
        outputNormalized=True,
        clip=False,
    )
    assert result.reachable
    assert result.points[-1].value == 1.5
    verifySolutions(result, {-1.0: -1.0, 0.0: 0.0, 1.0: 1.0})


def test_reverseMap_without_avar_is_identity():
    font = _reverseFont(segments=None)
    result = reverseMap(font, "wght", 700)
    assert result.reachable
    assert len(result.solutions) == 1
    assert result.solutions[0].value == 700
    # Identity must still forward-verify.
    verifyResult(font, result)


def test_reverseMap_user_space_verification_with_non_uniform_mapping():
    # Regression: user-space verification must re-normalize probe points
    # and run the real avar segments in normalized space.  Building a
    # "user-space segment dict" by denormalizing keys and values
    # separately is wrong because denormalization is piecewise-affine.
    segments = {-1.0: -1.0, 0.0: 0.0, 0.5: 0.5, 0.75: 0.5, 1.0: 1.0}
    font = _reverseFont(segments)
    # Normalized target 0.5 -> user target 650; plateau input
    # normalized [0.5, 0.75] -> user [650, 775].
    result = reverseMap(font, "wght", 650)
    assert result.unit == "user"
    interval = result.intervals[0]
    assert (interval.intervalStart, interval.intervalEnd) == (650, 775)
    for _solution, error in verifyResult(font, result):
        assert error <= 1e-12
    # Every interior user point of the interval must also verify.
    from fontTools.varLib.models import normalizeValue, piecewiseLinearMap

    triplet = WGH_TRIPLET
    for userValue in (650, 700, 775):
        normalized = normalizeValue(userValue, triplet)
        assert piecewiseLinearMap(normalized, segments) == pytest.approx(0.5, abs=1e-12)


def test_reverseMap_missing_fvar_raises():
    with pytest.raises(ReverseMapError, match="no 'fvar' table"):
        reverseMap(TTFont(), "wght", 0.5, inputNormalized=True)


def test_reverseMap_unknown_axis_raises():
    font = _reverseFont()
    with pytest.raises(ReverseMapError, match="unknown axis tag"):
        reverseMap(font, "wdth", 0.5, inputNormalized=True)


def test_reverseMap_multi_axis_input_raises():
    font = _reverseFont()
    with pytest.raises(ReverseMapError, match="single axis"):
        reverseMap(font, {"wght": 1, "wdth": 1}, 0.5, inputNormalized=True)


def test_reverseMap_user_target_outside_fvar_range_raises():
    font = _reverseFont()
    with pytest.raises(ReverseMapError, match="outside the fvar range"):
        reverseMap(font, "wght", 950)
    # The same target is accepted when clipping is disabled.
    result = reverseMap(font, "wght", 950, clip=False)
    assert result.reachable


def test_reverseMap_normalized_target_outside_domain_raises():
    font = _reverseFont()
    with pytest.raises(ReverseMapError, match=r"outside the \[-1, 1\]"):
        reverseMap(font, "wght", 1.2, inputNormalized=True)


def test_reverseMap_avar2_raises():
    font = _reverseFont(avarVersion=2)
    with pytest.raises(ReverseMapError, match="avar. version 2"):
        reverseMap(font, "wght", 0.5, inputNormalized=True)


def test_reverseMap_cli_point_and_interval(capsys, tmp_path):
    fontPath = tmp_path / "Reverse.ttf"
    _reverseFont().save(fontPath)

    rc = reverseMap_main([str(fontPath), "wght=650", "--verify"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "interval" in out
    assert "525" in out and "650" in out
    assert "forward max abs error" in out

    capsys.readouterr()  # flush
    rc = reverseMap_main([str(fontPath), "-i", "-o", "wght=0.0", "--verify"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "point: 0" in out


def test_reverseMap_cli_unreachable_exits_nonzero(capsys, tmp_path):
    fontPath = tmp_path / "Reverse.ttf"
    _reverseFont({-1.0: -0.5, 0.0: 0.0, 1.0: 0.5}).save(fontPath)
    rc = reverseMap_main([str(fontPath), "-i", "-o", "wght=0.75"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "no solution" in out


def test_reverseMap_cli_extrapolation_and_malformed(capsys, tmp_path):
    fontPath = tmp_path / "Reverse.ttf"
    _reverseFont({-1.0: -1.0, 0.0: 0.0, 1.0: 1.0}).save(fontPath)
    rc = reverseMap_main(
        [str(fontPath), "-i", "-o", "--no-clip", "wght=1.5", "--verify"]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "point: 1.5" in out

    with pytest.raises(SystemExit):
        reverseMap_main([str(fontPath), "wght"])


def test_reverseMap_cli_designspace_input_user_space_verify(capsys, tmp_path):
    designspace = tmp_path / "Test.designspace"
    # A plateau in user space: inputs 650..775 all map to output 650.
    designspace.write_text(
        """\
<?xml version='1.0' encoding='UTF-8'?>
<designspace format="5.0">
  <axes>
    <axis tag="wght" name="Weight" minimum="100" maximum="900" default="400">
      <map input="100" output="100"/>
      <map input="400" output="400"/>
      <map input="650" output="650"/>
      <map input="775" output="650"/>
      <map input="900" output="900"/>
    </axis>
  </axes>
</designspace>
""",
        encoding="utf-8",
    )
    rc = reverseMap_main([str(designspace), "wght=650", "--verify"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "interval: 650 .. 775" in out
    assert "forward max abs error = 0" in out


def test_reverseMap_cli_avar2_font_errors(capsys, tmp_path):
    fontPath = tmp_path / "Avar2.ttf"
    _reverseFont(avarVersion=2).save(fontPath)
    with pytest.raises(SystemExit):
        reverseMap_main([str(fontPath), "-i", "-o", "wght=0.0"])
