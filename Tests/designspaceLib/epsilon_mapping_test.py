# coding=utf-8
"""Tests for the ``epsilon`` offset on mapping dimensions.

See https://github.com/fonttools/fonttools/issues/3568. An epsilon of +/-1
nudges a mapping ``xvalue`` by exactly one normalized F2DOT14 int16 step
(1/16384), whose user-space magnitude depends on the axis min/default/max.
"""

import pytest

from fontTools.designspaceLib import (
    AxisDescriptor,
    AxisMappingDescriptor,
    DesignSpaceDocument,
    DesignSpaceDocumentError,
    EPSILON_SCALE,
    epsilonUserOffset,
)
from fontTools.varLib.models import normalizeValue

EPS = EPSILON_SCALE  # 16384

# Two deliberately asymmetric axes: default is not midway between extremes.
ASYMMETRIC_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<designspace format="5.0">
  <axes>
    <axis tag="wght" name="Weight" minimum="100" maximum="900" default="400"/>
    <axis tag="wdth" name="Width" minimum="50" maximum="200" default="80"/>
    <mappings>
      <mapping description="at default">
        <input>
          <dimension name="Weight" xvalue="400" epsilon="1"/>
          <dimension name="Width" xvalue="80" epsilon="-1"/>
        </input>
        <output>
          <dimension name="Weight" xvalue="400" epsilon="-1"/>
          <dimension name="Width" xvalue="80" epsilon="1"/>
        </output>
      </mapping>
      <mapping description="off default">
        <input>
          <dimension name="Weight" xvalue="700" epsilon="1"/>
          <dimension name="Width" xvalue="60" epsilon="-1"/>
        </input>
      </mapping>
    </mappings>
  </axes>
</designspace>
"""


@pytest.fixture
def doc():
    return DesignSpaceDocument.fromstring(ASYMMETRIC_XML.encode())


def test_scale_is_one_f2dot14_step():
    assert EPSILON_SCALE == 16384


def test_epsilon_offsets_use_correct_asymmetric_spans(doc):
    weight = doc.getAxis("Weight")
    width = doc.getAxis("Width")

    # Positive direction uses the default -> maximum span.
    assert epsilonUserOffset(weight, 1) == pytest.approx(500 / EPS)
    assert epsilonUserOffset(width, 1) == pytest.approx(120 / EPS)
    # Negative direction uses the minimum -> default span (negative sign).
    assert epsilonUserOffset(weight, -1) == pytest.approx(-300 / EPS)
    assert epsilonUserOffset(width, -1) == pytest.approx(-30 / EPS)
    # Zero is no offset.
    assert epsilonUserOffset(weight, 0) == 0.0

    # Also usable with a plain (minimum, default, maximum) triple.
    assert epsilonUserOffset((100, 400, 900), -1) == pytest.approx(-300 / EPS)


def test_parse_resolves_epsilon_in_input_and_output(doc):
    at_default, off_default = doc.axisMappings

    assert at_default.inputEpsilon == {"Weight": 1, "Width": -1}
    assert at_default.outputEpsilon == {"Weight": -1, "Width": 1}

    loc = at_default.inputLocation
    assert loc["Weight"] == pytest.approx(400 + 500 / EPS)
    assert loc["Width"] == pytest.approx(80 - 30 / EPS)

    out = at_default.outputLocation
    assert out["Weight"] == pytest.approx(400 - 300 / EPS)
    assert out["Width"] == pytest.approx(80 + 120 / EPS)

    second = off_default.inputLocation
    assert second["Weight"] == pytest.approx(700 + 500 / EPS)
    assert second["Width"] == pytest.approx(60 - 30 / EPS)
    assert off_default.inputEpsilon == {"Weight": 1, "Width": -1}
    assert off_default.outputLocation == {}
    assert off_default.outputEpsilon == {}


def test_epsilon_is_exactly_one_normalized_int16_unit(doc):
    weight_triple = (100, 400, 900)
    width_triple = (50, 80, 200)
    at_default, off_default = doc.axisMappings

    # At the default the normalized base is 0, so +/-1 lands on +/-1/EPS.
    assert normalizeValue(
        at_default.inputLocation["Weight"], weight_triple
    ) == pytest.approx(1 / EPS)
    assert normalizeValue(
        at_default.inputLocation["Width"], width_triple
    ) == pytest.approx(-1 / EPS)
    assert normalizeValue(
        at_default.outputLocation["Weight"], weight_triple
    ) == pytest.approx(-1 / EPS)
    assert normalizeValue(
        at_default.outputLocation["Width"], width_triple
    ) == pytest.approx(1 / EPS)

    # Same-direction nudges away from the default keep the exact unit step.
    assert normalizeValue(
        off_default.inputLocation["Weight"], weight_triple
    ) == pytest.approx(normalizeValue(700, weight_triple) + 1 / EPS)
    assert normalizeValue(
        off_default.inputLocation["Width"], width_triple
    ) == pytest.approx(normalizeValue(60, width_triple) - 1 / EPS)


def test_epsilon_xml_roundtrip_preserves_attribute_and_values(doc, tmp_path):
    path = tmp_path / "epsilon.designspace"
    doc.write(str(path))
    text = path.read_text(encoding="utf-8")

    # The clean integer base xvalue and the epsilon attribute are preserved,
    # rather than being flattened into a long user-coordinate decimal.
    assert 'xvalue="400" epsilon="1"' in text
    assert 'xvalue="400" epsilon="-1"' in text
    assert 'xvalue="80" epsilon="-1"' in text
    assert 'xvalue="80" epsilon="1"' in text
    assert "400.0305" not in text

    reparsed = DesignSpaceDocument()
    reparsed.read(str(path))
    assert len(reparsed.axisMappings) == len(doc.axisMappings)
    for original, copied in zip(doc.axisMappings, reparsed.axisMappings):
        assert copied.inputEpsilon == original.inputEpsilon
        assert copied.outputEpsilon == original.outputEpsilon
        assert copied.inputLocation == original.inputLocation
        assert copied.outputLocation == original.outputLocation


def test_missing_and_zero_epsilon_match_existing_behavior():
    xml = """\
<?xml version="1.0"?>
<designspace format="5.0"><axes>
<axis tag="w" name="W" minimum="0" maximum="1000" default="400"/>
<mappings><mapping>
<input><dimension name="W" xvalue="123"/></input>
<output><dimension name="W" xvalue="400" epsilon="0"/></output>
</mapping></mappings></axes></designspace>
"""
    doc = DesignSpaceDocument.fromstring(xml.encode())
    mapping = doc.axisMappings[0]
    # Plain floats, no recorded epsilon for missing or explicit zero.
    assert mapping.inputLocation == {"W": 123.0}
    assert mapping.outputLocation == {"W": 400.0}
    assert mapping.inputEpsilon == {}
    assert mapping.outputEpsilon == {}

    import tempfile

    path = tempfile.mktemp(suffix=".designspace")
    doc.write(path)
    text = open(path, encoding="utf-8").read()
    assert 'name="W" xvalue="123"/' in text
    assert "epsilon" not in text


@pytest.mark.parametrize("bad", ["2", "-2", "0.5", "1.0", "abc", "", "true"])
def test_invalid_epsilon_raises_clear_error(bad):
    xml = f"""\
<?xml version="1.0"?>
<designspace format="5.0"><axes>
<axis tag="w" name="W" minimum="0" maximum="1000" default="400"/>
<mappings><mapping><input>
<dimension name="W" xvalue="400" epsilon="{bad}"/>
</input><output><dimension name="W" xvalue="400"/></output></mapping></mappings>
</axes></designspace>
"""
    with pytest.raises(DesignSpaceDocumentError, match="epsilon"):
        DesignSpaceDocument.fromstring(xml.encode())


def test_epsilon_on_unknown_axis_raises_clear_error():
    xml = """\
<?xml version="1.0"?>
<designspace format="5.0"><axes>
<axis tag="w" name="W" minimum="0" maximum="1000" default="400"/>
<mappings><mapping><input>
<dimension name="Ghost" xvalue="400" epsilon="1"/>
</input><output><dimension name="W" xvalue="400"/></output></mapping></mappings>
</axes></designspace>
"""
    with pytest.raises(DesignSpaceDocumentError, match="Ghost"):
        DesignSpaceDocument.fromstring(xml.encode())


def test_epsilon_on_discrete_axis_raises_clear_error():
    xml = """\
<?xml version="1.0"?>
<designspace format="5.0"><axes>
<axis tag="i" name="Italic" default="0" values="0 1"/>
<mappings><mapping><input>
<dimension name="Italic" xvalue="0" epsilon="1"/>
</input><output/></mapping></mappings>
</axes></designspace>
"""
    with pytest.raises(DesignSpaceDocumentError):
        DesignSpaceDocument.fromstring(xml.encode())


def test_programmatic_descriptor_epsilon_roundtrip(tmp_path):
    weight = AxisDescriptor()
    weight.name = "Weight"
    weight.tag = "wght"
    weight.minimum = 100
    weight.default = 400
    weight.maximum = 900

    mapping = AxisMappingDescriptor(
        inputLocation={"Weight": 400 + 500 / EPS},
        inputEpsilon={"Weight": 1},
        outputLocation={},
    )
    doc = DesignSpaceDocument()
    doc.addAxis(weight)
    doc.addAxisMapping(mapping)

    path = tmp_path / "programmatic.designspace"
    doc.write(str(path))
    text = path.read_text(encoding="utf-8")
    assert 'xvalue="400" epsilon="1"' in text

    reparsed = DesignSpaceDocument()
    reparsed.read(str(path))
    assert reparsed.axisMappings[0].inputEpsilon == {"Weight": 1}
    assert reparsed.axisMappings[0].inputLocation["Weight"] == pytest.approx(
        400 + 500 / EPS
    )
