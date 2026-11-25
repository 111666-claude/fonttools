"""End-to-end tests for chained DesignSpace rules in the built GSUB table.

Two rules that both fire at one location must be applied consecutively in
rule order, matching designspaceLib.processRules: rule 1 substituting A with
B followed by rule 2 substituting B with C yields C, not B.  The built
FeatureVariations used to flatten same-region substitution dictionaries into
a single single-substitution lookup, which broke such chains.
"""

from io import BytesIO

import pytest

from fontTools.designspaceLib import (
    AxisDescriptor,
    DesignSpaceDocument,
    RuleDescriptor,
    SourceDescriptor,
    processRules,
)
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from fontTools.varLib import build, models

GLYPH_ORDER = [".notdef", "A", "B", "C", "D", "X"]


def make_master():
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(GLYPH_ORDER)
    builder.setupCharacterMap({})
    glyphs = {}
    for name in GLYPH_ORDER:
        pen = TTGlyphPen(None)
        pen.moveTo((0, 0))
        pen.lineTo((500, 0))
        pen.lineTo((500, 700))
        pen.lineTo((0, 700))
        pen.closePath()
        glyphs[name] = pen.glyph()
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics({name: (600, 0) for name in glyphs})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "Chain", "styleName": "Regular"})
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200)
    builder.setupPost()
    return builder.font


def make_designspace(rules, axis_minimum=100, axis_default=400, axis_maximum=900):
    document = DesignSpaceDocument()
    axis = AxisDescriptor(
        name="Weight",
        tag="wght",
        minimum=axis_minimum,
        default=axis_default,
        maximum=axis_maximum,
    )
    document.addAxis(axis)
    for value in (axis_minimum, axis_default, axis_maximum):
        source = SourceDescriptor()
        source.location = {"Weight": value}
        source.font = make_master()
        document.addSource(source)
    for rule in rules:
        document.addRule(rule)
    return document


def reload_font(font):
    stream = BytesIO()
    font.save(stream)
    return TTFont(BytesIO(stream.getvalue()))


def simulate_feature_variations(font, location, glyph_names):
    """Run the rvrn FeatureVariations of a built font at a normalized location.

    The first FeatureVariation record whose conditions match is selected, and
    its lookups are applied in order, exactly as a shaper applies the lookups
    of a feature to a run of glyphs.
    """
    gsub = font["GSUB"].table
    records = gsub.FeatureVariations.FeatureVariationRecord
    chosen = None
    for record in records:
        if record.ConditionSet is None:
            chosen = record
            break
        if all(
            condition.FilterRangeMinValue
            <= location["wght"]
            <= condition.FilterRangeMaxValue
            for condition in record.ConditionSet.ConditionTable
        ):
            chosen = record
            break
    if chosen is None:
        return list(glyph_names)
    result = list(glyph_names)
    for substitution in chosen.FeatureTableSubstitution.SubstitutionRecord:
        for lookup_index in substitution.Feature.LookupListIndex:
            lookup = gsub.LookupList.Lookup[lookup_index]
            mapping = lookup.SubTable[0].mapping
            result = [mapping.get(name, name) for name in result]
    return result


def rule(name, minimum, maximum, subs):
    return RuleDescriptor(
        name=name,
        conditionSets=[[{"name": "Weight", "minimum": minimum, "maximum": maximum}]],
        subs=subs,
    )


@pytest.mark.parametrize(
    "rules,location,expected",
    [
        # Chained rules sharing the exact same region: A -> B -> C.
        (
            [
                rule("a-to-b", 500, None, [("A", "B")]),
                rule("b-to-c", 500, None, [("B", "C")]),
            ],
            700,
            ["C", "C", "C", "D", "X"],
        ),
        # Three-rule chain: A -> B -> C -> D.
        (
            [
                rule("a-to-b", 500, None, [("A", "B")]),
                rule("b-to-c", 500, None, [("B", "C")]),
                rule("c-to-d", 500, None, [("C", "D")]),
            ],
            700,
            ["D", "D", "D", "D", "X"],
        ),
        # Conflicting rules with the same source: the earlier rule wins,
        # because A becomes B and the later rule no longer matches it.
        (
            [
                rule("a-to-b", 500, None, [("A", "B")]),
                rule("a-to-x", 500, None, [("A", "X")]),
            ],
            700,
            ["B", "B", "C", "D", "X"],
        ),
        # A substitution cycle must terminate after one pass per rule:
        # A -> B -> A, B -> A -> B.
        (
            [
                rule("a-to-b", 500, None, [("A", "B")]),
                rule("b-to-a", 500, None, [("B", "A")]),
            ],
            700,
            ["A", "A", "C", "D", "X"],
        ),
    ],
)
def test_built_gsub_matches_process_rules(rules, location, expected):
    document = make_designspace(rules)
    font, _, _ = build(document)
    font = reload_font(font)

    support = (100, 400, 900)
    normalized = models.normalizeValue(location, support, allow_decreasing=True)

    gsub_names = simulate_feature_variations(
        font, {"wght": normalized}, list(GLYPH_ORDER[1:])
    )
    assert gsub_names == expected

    rules_names = processRules(rules, {"Weight": location}, list(GLYPH_ORDER[1:]))
    assert rules_names == expected
    assert gsub_names == rules_names


def test_chain_does_not_fire_outside_region():
    rules = [
        rule("a-to-b", 500, None, [("A", "B")]),
        rule("b-to-c", 500, None, [("B", "C")]),
    ]
    document = make_designspace(rules)
    font, _, _ = build(document)
    font = reload_font(font)

    support = (100, 400, 900)
    normalized = models.normalizeValue(400, support, allow_decreasing=True)
    glyphs = list(GLYPH_ORDER[1:])
    assert simulate_feature_variations(font, {"wght": normalized}, glyphs) == glyphs
    assert processRules(rules, {"Weight": 400}, glyphs) == glyphs


def test_chain_fires_at_boundary_axis_value():
    rules = [
        rule("a-to-b", 500, None, [("A", "B")]),
        rule("b-to-c", 500, None, [("B", "C")]),
    ]
    document = make_designspace(rules)
    font, _, _ = build(document)
    font = reload_font(font)

    support = (100, 400, 900)
    glyphs = list(GLYPH_ORDER[1:])
    expected = processRules(rules, {"Weight": 500}, glyphs)
    assert expected == ["C", "C", "C", "D", "X"]

    # Condition tables store bounds as f2dot14 fixed-point values, so use the
    # actual stored minimum of the built condition rather than the float input.
    # The designspace condition minimum is inclusive, so the stored bound
    # itself must match and the chain must fire there.
    record = font["GSUB"].table.FeatureVariations.FeatureVariationRecord[0]
    condition = record.ConditionSet.ConditionTable[0]
    boundary = condition.FilterRangeMinValue
    assert simulate_feature_variations(font, {"wght": boundary}, glyphs) == expected

    # Just inside the default side nothing fires.
    below = models.normalizeValue(499, support, allow_decreasing=True)
    assert below < boundary
    assert simulate_feature_variations(font, {"wght": below}, glyphs) == glyphs


def test_partially_overlapping_regions_chain_in_overlap_only():
    rules = [
        # Rule 1 fires over a wider region, rule 2 only in a nested one.
        rule("a-to-b", 300, None, [("A", "B")]),
        rule("b-to-c", 600, None, [("B", "C")]),
    ]
    document = make_designspace(rules)
    font, _, _ = build(document)
    font = reload_font(font)

    support = (100, 400, 900)
    glyphs = list(GLYPH_ORDER[1:])

    # Overlap region: full chain A -> B -> C.
    loc = models.normalizeValue(700, support, allow_decreasing=True)
    expected = processRules(rules, {"Weight": 700}, glyphs)
    assert expected == ["C", "C", "C", "D", "X"]
    assert simulate_feature_variations(font, {"wght": loc}, glyphs) == expected

    # Non-overlap region where only rule 1 fires: A -> B, B untouched.
    loc = models.normalizeValue(450, support, allow_decreasing=True)
    expected = processRules(rules, {"Weight": 450}, glyphs)
    assert expected == ["B", "B", "C", "D", "X"]
    assert simulate_feature_variations(font, {"wght": loc}, glyphs) == expected

    # Outside every region: glyphs untouched.
    loc = models.normalizeValue(200, support, allow_decreasing=True)
    assert simulate_feature_variations(font, {"wght": loc}, glyphs) == glyphs


def test_same_region_chain_builds_ordered_lookups():
    rules = [
        rule("a-to-b", 500, None, [("A", "B")]),
        rule("b-to-c", 500, None, [("B", "C")]),
    ]
    document = make_designspace(rules)
    font, _, _ = build(document)
    font = reload_font(font)

    gsub = font["GSUB"].table
    # One region, but two distinct single-substitution lookups in rule order.
    assert len(gsub.FeatureVariations.FeatureVariationRecord) == 1
    record = gsub.FeatureVariations.FeatureVariationRecord[0]
    lookup_indices = record.FeatureTableSubstitution.SubstitutionRecord[
        0
    ].Feature.LookupListIndex
    assert lookup_indices == [0, 1]
    assert gsub.LookupList.Lookup[0].SubTable[0].mapping == {"A": "B"}
    assert gsub.LookupList.Lookup[1].SubTable[0].mapping == {"B": "C"}


def test_identical_rules_are_deduplicated():
    # The exact same rule repeated must not produce a duplicated lookup.
    rules = [
        rule("first", 500, None, [("A", "B")]),
        rule("second", 500, None, [("A", "B")]),
    ]
    document = make_designspace(rules)
    font, _, _ = build(document)
    font = reload_font(font)

    gsub = font["GSUB"].table
    assert len(gsub.LookupList.Lookup) == 1
    record = gsub.FeatureVariations.FeatureVariationRecord[0]
    assert record.FeatureTableSubstitution.SubstitutionRecord[
        0
    ].Feature.LookupListIndex == [0]
