"""Tests for referencing declared axes by their four-character ``tag``.

Axis names can be renamed whereas OpenType axis tags are stable. These tests
cover that source/instance locations, rule conditions and mapping dimensions
accept a ``tag`` attribute and resolve to exactly the same canonical name-keyed
structures as the equivalent ``name`` document.
"""

from __future__ import annotations

import pytest

from fontTools.designspaceLib import (
    DesignSpaceDocument,
    DesignSpaceDocumentError,
    evaluateRule,
    processRules,
)

WEIGHT_AXIS = (
    '<axis name="Weight" tag="wght" minimum="100" maximum="900" default="400"/>'
)
WIDTH_AXIS = '<axis name="Width" tag="wdth" minimum="50" maximum="200" default="100"/>'


def _xml(ref):
    """Build the same two-axis document; ``ref(kind)`` renders a reference."""
    src_w = ref("src_w")
    src_d = ref("src_d")
    inst_w = ref("inst_w")
    inst_d = ref("inst_d")
    cond_w = ref("cond_w")
    cond_d = ref("cond_d")
    map_iw = ref("map_iw")
    map_id = ref("map_id")
    map_ow = ref("map_ow")

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<designspace format="5.0">
  <axes>
    {WEIGHT_AXIS}
    {WIDTH_AXIS}
    <mappings>
      <mapping description="m">
        <input>{map_iw}{map_id}</input>
        <output>{map_ow}</output>
      </mapping>
    </mappings>
  </axes>
  <rules>
    <rule name="wide.heavy">
      <conditionset>
        {cond_w}
        {cond_d}
      </conditionset>
      <sub name="A" with="A.alt"/>
    </rule>
  </rules>
  <sources>
    <source filename="a.ufo" name="a">
      <location>{src_w}{src_d}</location>
    </source>
  </sources>
  <instances>
    <instance name="Black Wide" familyname="F" stylename="Black Wide">
      <location>{inst_w}{inst_d}</location>
    </instance>
  </instances>
</designspace>
"""


def name_ref(kind, **_):
    table = {
        "src_w": '<dimension name="Weight" xvalue="700"/>',
        "src_d": '<dimension name="Width" xvalue="150"/>',
        "inst_w": '<dimension name="Weight" xvalue="900"/>',
        "inst_d": '<dimension name="Width" xvalue="200"/>',
        "cond_w": '<condition name="Weight" minimum="600" maximum="900"/>',
        "cond_d": '<condition name="Width" minimum="120"/>',
        "map_iw": '<dimension name="Weight" xvalue="700"/>',
        "map_id": '<dimension name="Width" xvalue="150"/>',
        "map_ow": '<dimension name="Weight" xvalue="720"/>',
    }
    return table[kind]


def tag_ref(kind, **_):
    table = {
        "src_w": '<dimension tag="wght" xvalue="700"/>',
        "src_d": '<dimension tag="wdth" xvalue="150"/>',
        "inst_w": '<dimension tag="wght" xvalue="900"/>',
        "inst_d": '<dimension tag="wdth" xvalue="200"/>',
        "cond_w": '<condition tag="wght" minimum="600" maximum="900"/>',
        "cond_d": '<condition tag="wdth" minimum="120"/>',
        "map_iw": '<dimension tag="wght" xvalue="700"/>',
        "map_id": '<dimension tag="wdth" xvalue="150"/>',
        "map_ow": '<dimension tag="wght" xvalue="720"/>',
    }
    return table[kind]


@pytest.fixture(scope="module")
def name_doc():
    return DesignSpaceDocument.fromstring(_xml(name_ref))


@pytest.fixture(scope="module")
def tag_doc():
    return DesignSpaceDocument.fromstring(_xml(tag_ref))


def _resolved(doc):
    return {
        "sources": [dict(s.location) for s in doc.sources],
        "source_full": [s.getFullDesignLocation(doc) for s in doc.sources],
        "instances": [dict(i.designLocation) for i in doc.instances],
        "rules": [[dict(c) for cs in r.conditionSets for c in cs] for r in doc.rules],
        "mappings": [
            (dict(m.inputLocation), dict(m.outputLocation)) for m in doc.axisMappings
        ],
    }


def test_tag_references_resolve_to_canonical_axis_names(tag_doc):
    # Keyed by declared name, not left keyed by the raw tag.
    assert tag_doc.sources[0].location == {"Weight": 700.0, "Width": 150.0}
    assert tag_doc.instances[0].designLocation == {
        "Weight": 900.0,
        "Width": 200.0,
    }
    condition = tag_doc.rules[0].conditionSets[0]
    assert {c["name"] for c in condition} == {"Weight", "Width"}
    assert tag_doc.axisMappings[0].inputLocation == {
        "Weight": 700.0,
        "Width": 150.0,
    }
    assert tag_doc.axisMappings[0].outputLocation == {"Weight": 720.0}


def test_tag_and_name_writings_give_identical_locations_and_rules(name_doc, tag_doc):
    assert _resolved(tag_doc) == _resolved(name_doc)


@pytest.mark.parametrize(
    "location",
    [{"Weight": w, "Width": d} for w in (300, 650, 800) for d in (80, 130, 180)],
)
def test_rule_hits_are_identical(name_doc, tag_doc, location):
    name_hit = [evaluateRule(r, location) for r in name_doc.rules]
    tag_hit = [evaluateRule(r, location) for r in tag_doc.rules]
    assert tag_hit == name_hit
    assert processRules(tag_doc.rules, location, ["A", "B"]) == processRules(
        name_doc.rules, location, ["A", "B"]
    )


def test_rule_actually_hits_in_tag_document(tag_doc):
    hit = {"Weight": 700, "Width": 160}
    assert evaluateRule(tag_doc.rules[0], hit)
    assert processRules(tag_doc.rules, hit, ["A", "B"]) == ["A.alt", "B"]
    miss = {"Weight": 300, "Width": 160}
    assert not evaluateRule(tag_doc.rules[0], miss)
    assert processRules(tag_doc.rules, miss, ["A", "B"]) == ["A", "B"]


def test_roundtrip_preserves_semantics_and_converges(name_doc, tag_doc):
    name_rt = DesignSpaceDocument.fromstring(name_doc.tostring())
    tag_rt = DesignSpaceDocument.fromstring(tag_doc.tostring())

    assert _resolved(name_rt) == _resolved(name_doc)
    assert _resolved(tag_rt) == _resolved(tag_doc)
    # The two source writings describe the very same document.
    assert _resolved(tag_rt) == _resolved(name_rt)

    # Values survive (not silently reset to the axis default of 400/100).
    assert tag_rt.sources[0].location == {"Weight": 700.0, "Width": 150.0}
    assert tag_rt.instances[0].designLocation == {
        "Weight": 900.0,
        "Width": 200.0,
    }


def test_written_dimensions_use_canonical_names(tag_doc):
    xml = tag_doc.tostring().decode("utf-8")
    assert '<dimension name="Weight" xvalue="700"' in xml
    assert '<condition name="Weight" minimum="600" maximum="900"' in xml


def test_agreeing_name_and_tag_on_same_reference_is_allowed():
    xml = f"""<designspace format="5.0"><axes>{WEIGHT_AXIS}</axes>
      <sources><source name="s"><location>
        <dimension name="Weight" tag="wght" xvalue="500"/>
      </location></source></sources></designspace>"""
    doc = DesignSpaceDocument.fromstring(xml)
    assert doc.sources[0].location == {"Weight": 500.0}


_TWO_AXES = f"<axes>{WEIGHT_AXIS}{WIDTH_AXIS}</axes>"


@pytest.mark.parametrize(
    "fragment",
    [
        # source location
        '<sources><source name="s"><location>'
        '<dimension tag="ZZZZ" xvalue="1"/></location></source></sources>',
        # instance location
        '<instances><instance name="i"><location>'
        '<dimension tag="ZZZZ" xvalue="1"/></location></instance></instances>',
        # rule condition
        "<rules><rule name='r'><conditionset>"
        '<condition tag="ZZZZ" minimum="1"/></conditionset>'
        '<sub name="A" with="B"/></rule></rules>',
    ],
)
def test_unknown_tag_is_a_located_error_not_default(fragment):
    xml = f'<designspace format="5.0">{_TWO_AXES}{fragment}</designspace>'
    with pytest.raises(DesignSpaceDocumentError, match="ZZZZ"):
        DesignSpaceDocument.fromstring(xml)
    with pytest.raises(DesignSpaceDocumentError, match="unknown tag"):
        DesignSpaceDocument.fromstring(xml)


def test_unknown_tag_in_mapping_is_a_located_error():
    xml = f"""<designspace format="5.0">
      <axes>{WEIGHT_AXIS}{WIDTH_AXIS}
        <mappings><mapping><input>
          <dimension tag="ZZZZ" xvalue="1"/>
        </input><output/></mapping></mappings>
      </axes></designspace>"""
    with pytest.raises(DesignSpaceDocumentError, match="unknown tag"):
        DesignSpaceDocument.fromstring(xml)
    with pytest.raises(DesignSpaceDocumentError, match="mapping"):
        DesignSpaceDocument.fromstring(xml)


def test_duplicate_axis_tag_is_an_error():
    xml = """<designspace format="5.0"><axes>
      <axis name="Weight" tag="wght" minimum="1" maximum="9" default="4"/>
      <axis name="WeightAgain" tag="wght" minimum="1" maximum="9" default="4"/>
    </axes></designspace>"""
    with pytest.raises(DesignSpaceDocumentError, match="wght"):
        DesignSpaceDocument.fromstring(xml)
    with pytest.raises(DesignSpaceDocumentError, match="duplicate tag"):
        DesignSpaceDocument.fromstring(xml)


@pytest.mark.parametrize(
    "reference",
    [
        '<dimension name="Weight" tag="wdth" xvalue="1"/>',
        '<condition name="Weight" tag="wdth" minimum="1"/>',
    ],
)
def test_name_tag_conflict_is_an_error(reference):
    if reference.startswith("<dimension"):
        body = (
            "<sources><source name='s'><location>"
            f"{reference}</location></source></sources>"
        )
    else:
        body = (
            "<rules><rule name='r'><conditionset>"
            f"{reference}</conditionset></rule></rules>"
        )
    xml = f'<designspace format="5.0">{_TWO_AXES}{body}</designspace>'
    with pytest.raises(DesignSpaceDocumentError, match="name/tag conflict"):
        DesignSpaceDocument.fromstring(xml)
    with pytest.raises(DesignSpaceDocumentError, match="Weight"):
        DesignSpaceDocument.fromstring(xml)
    with pytest.raises(DesignSpaceDocumentError, match="wdth"):
        DesignSpaceDocument.fromstring(xml)


def test_name_only_documents_continue_to_work():
    doc = DesignSpaceDocument.fromstring(_xml(name_ref))
    assert doc.getAxis("Weight").tag == "wght"
    assert doc.sources[0].location["Weight"] == 700.0
    # And a plain write/read cycle keeps working.
    rt = DesignSpaceDocument.fromstring(doc.tostring())
    assert _resolved(rt) == _resolved(doc)


def test_tag_reference_with_uservalue():
    xml = f"""<designspace format="5.0"><axes>{WEIGHT_AXIS}</axes>
      <instances><instance name="i"><location>
        <dimension tag="wght" uservalue="700"/>
      </location></instance></instances></designspace>"""
    doc = DesignSpaceDocument.fromstring(xml)
    assert doc.instances[0].userLocation == {"Weight": 700.0}
    rt = DesignSpaceDocument.fromstring(doc.tostring())
    assert rt.instances[0].userLocation == {"Weight": 700.0}


def test_tag_references_survive_axis_rename():
    # The motivating property: rename the axis name, keep its tag, and every
    # tag reference follows the renamed axis without being edited.
    xml = """<designspace format="5.0"><axes>
      <axis name="Boldness" tag="wght" minimum="1" maximum="9" default="4"/>
    </axes>
      <rules><rule name="r"><conditionset>
        <condition tag="wght" minimum="6"/>
      </conditionset><sub name="A" with="A.alt"/></rule></rules>
      <sources><source name="s"><location>
        <dimension tag="wght" xvalue="7"/>
      </location></source></sources></designspace>"""
    doc = DesignSpaceDocument.fromstring(xml)
    assert doc.sources[0].location == {"Boldness": 7.0}
    assert doc.rules[0].conditionSets[0][0]["name"] == "Boldness"
    assert evaluateRule(doc.rules[0], {"Boldness": 7})
    rt = DesignSpaceDocument.fromstring(doc.tostring())
    assert rt.sources[0].location == {"Boldness": 7.0}
