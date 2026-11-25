import warnings
from types import SimpleNamespace

import pytest

from fontTools.designspaceLib import DesignSpaceDocument, AxisDescriptor
from fontTools.feaLib.variableScalar import (
    AxisValue,
    VariableScalar,
    VariableScalarBuilder,
)
from fontTools.fontBuilder import addFvar
from fontTools.ttLib import newTable
from fontTools.ttLib.ttFont import TTFont
from fontTools.varLib.varStore import OnlineVarStoreBuilder
from fontTools.varLib.models import VariationModel, normalizeValue


def test_variable_scalar_repr():
    scalar = VariableScalar()
    scalar.add_value({}, 20)
    scalar.add_value({"wght": 400}, 1)
    scalar.add_value({"wght": 500.5}, 4)
    scalar.add_value({"wght": 700}, 10)

    assert str(scalar) == "(20 wght=400:1 wght=500.5:4 wght=700:10)"


def _builder_with_avar():
    return VariableScalarBuilder(
        axis_triples={"wght": (200, 400, 800)},
        axis_mappings={"wght": {-1.0: -1.0, -0.5: -0.2, 0.0: 0.0, 1.0: 1.0}},
        model_cache={},
    )


def test_resolve_user_units():
    builder = _builder_with_avar()
    scalar = VariableScalar()
    scalar.add_raw_value(None, 20)
    scalar.add_raw_value((("wght", AxisValue(800.0, unit="u")),), 80)
    builder.resolve(scalar)
    assert scalar.values[(("wght", 800.0),)] == 80
    # The default location is fully specified.
    assert scalar.values[(("wght", 400),)] == 20


def test_resolve_normalized_units():
    builder = _builder_with_avar()
    scalar = VariableScalar()
    scalar.add_raw_value((("wght", AxisValue(1.0, unit="n")),), 80)
    builder.resolve(scalar)
    # 1n denormalizes to the axis maximum.
    assert (("wght", 800.0),) in scalar.values

    min_scalar = VariableScalar()
    min_scalar.add_raw_value((("wght", AxisValue(-1.0, unit="n")),), 10)
    builder.resolve(min_scalar)
    assert (("wght", 200.0),) in min_scalar.values


def test_resolve_adjacent_normalized_step():
    builder = _builder_with_avar()
    scalar = VariableScalar()
    scalar.add_raw_value((("wght", AxisValue(0.0, unit="n", adjacent=1)),), 1)
    builder.resolve(scalar)
    ((loc, value),) = scalar.values.items()
    # One F2dot14 step above the normalized default, denormalized along the
    # positive half of the axis (400 -> 800).
    assert loc == (("wght", 400 + (1 / 16384) * 400),)
    assert value == 1


def test_resolve_designer_units_without_mapping_equals_user():
    # A TTF-derived builder has no design triples: d and u must coincide and
    # avar is still applied at normalization time.
    builder = _builder_with_avar()
    d_scalar = VariableScalar()
    d_scalar.add_raw_value((("wght", AxisValue(300.0, unit="d")),), 25)
    builder.resolve(d_scalar)
    u_scalar = VariableScalar()
    u_scalar.add_raw_value((("wght", AxisValue(300.0, unit="u")),), 25)
    builder.resolve(u_scalar)
    assert d_scalar.values == u_scalar.values
    loc = (("wght", 300.0),)
    assert builder._normalize_location(loc) == {"wght": -0.2}


def test_resolve_designer_units_with_designspace_mapping():
    # With a real designspace mapping, designer values go through the
    # inverse avar mapping before denormalization.
    doc = DesignSpaceDocument()
    doc.addAxis(
        AxisDescriptor(
            tag="wght",
            minimum=200,
            default=400,
            maximum=800,
            map=[(200, 50), (400, 100), (800, 150)],
        )
    )
    builder = VariableScalarBuilder.from_designspace(doc)

    scalar = VariableScalar()
    # Designer 50 is the mapped minimum -> user minimum 200.
    scalar.add_raw_value((("wght", AxisValue(50.0, unit="d")),), 10)
    builder.resolve(scalar)
    assert (("wght", 200.0),) in scalar.values

    max_scalar = VariableScalar()
    max_scalar.add_raw_value((("wght", AxisValue(150.0, unit="d")),), 80)
    builder.resolve(max_scalar)
    assert (("wght", 800.0),) in max_scalar.values


def test_resolve_unknown_axis_raises_featureliberror():
    from fontTools.feaLib.error import FeatureLibError

    builder = _builder_with_avar()
    scalar = VariableScalar()
    scalar.add_raw_value((("slnt", AxisValue(0.0, unit="u")),), 1)
    with pytest.raises(FeatureLibError, match="Unknown axis slnt"):
        builder.resolve(scalar)


def test_resolve_duplicate_location_raises():
    builder = _builder_with_avar()
    scalar = VariableScalar()
    scalar.add_raw_value((("wght", AxisValue(200.0, unit="u")),), 10)
    scalar.add_raw_value((("wght", AxisValue(200.0, unit="u")),), 20)
    with pytest.raises(ValueError, match="Duplicate value for location"):
        builder.resolve(scalar)


def test_axis_value_asfea():
    assert AxisValue(600.0, unit="d").asFea() == "600d"
    assert AxisValue(0.0, unit="n", adjacent=1).asFea() == "0n+"
    assert AxisValue(1.0, unit="n", adjacent=-1).asFea() == "1n-"
    assert AxisValue(200.0, unit="u", explicit_unit=False).asFea() == "200"


@pytest.mark.parametrize(
    "axis_map",
    [
        [(200, 50), (300, 90), (400, 100), (800, 150)],
        # same axis with design values decreasing as user values increase
        [(200, 150), (300, 110), (400, 100), (800, 50)],
    ],
    ids=["increasing", "decreasing"],
)
def test_variable_scalar_interpolation_with_avar(axis_map):
    """Test that avar mapping is applied when interpolating a variable scalar
    from a designspace.

    The map entry for user 300 shifts it toward the design default, so the
    interpolated value is closer to 40 than a naive interpolation without avar
    would give.
    """
    scalar = VariableScalar()
    scalar.add_value({"wght": 200}, 10)
    scalar.add_value({"wght": 400}, 40)
    scalar.add_value({"wght": 800}, 80)

    doc = DesignSpaceDocument()
    doc.addAxis(
        AxisDescriptor(
            tag="wght",
            minimum=200,
            default=400,
            maximum=800,
            map=axis_map,
        )
    )

    builder = VariableScalarBuilder.from_designspace(doc)

    # With avar, user 300 maps near the design default -> value 34.
    value = builder.value_at_location(scalar, (("wght", 300),))
    assert value == pytest.approx(34.0)

    # Without avar, user 300 is halfway between min and default -> value 25.
    builder_no_avar = VariableScalarBuilder(
        axis_triples=builder.axis_triples,
        axis_mappings={},
        model_cache={},
    )
    value_no_avar = builder_no_avar.value_at_location(scalar, (("wght", 300),))
    assert value_no_avar == pytest.approx(25.0)


def test_from_ttf_with_avar():
    """Test that from_ttf reads fvar axes and avar segments correctly,
    and produces the same interpolation results as from_designspace."""
    font = TTFont()
    font.setGlyphOrder([".notdef"])
    font["name"] = newTable("name")
    addFvar(font, [("wght", 200, 400, 800, "Weight")], [])
    del font["name"]
    font["avar"] = newTable("avar")
    # Equivalent normalized avar segments for the designspace map
    # [(200, 50), (300, 90), (400, 100), (800, 150)]
    font["avar"].segments = {"wght": {-1.0: -1.0, -0.5: -0.2, 0.0: 0.0, 1.0: 1.0}}

    builder = VariableScalarBuilder.from_ttf(font)

    scalar = VariableScalar()
    scalar.add_value({"wght": 200}, 10)
    scalar.add_value({"wght": 400}, 40)
    scalar.add_value({"wght": 800}, 80)

    # Same result as the from_designspace test above.
    value = builder.value_at_location(scalar, (("wght", 300),))
    assert value == pytest.approx(34.0)


def test_model_uses_axes_order():
    """VariableScalarBuilder.model() should use the axis order from
    axis_triples, not the default alphabetical order, to ensure consistent
    deltas regardless of axis tag sorting.

    https://github.com/fonttools/fonttools/pull/4053
    """

    builder = VariableScalarBuilder(
        axis_triples={
            "wght": (100, 400, 900),
            "wdth": (62.5, 100, 100),
        },
        axis_mappings={},
        model_cache={},
    )

    scalar = VariableScalar()
    scalar.add_value({"wght": 100, "wdth": 100}, 151)
    scalar.add_value({"wght": 400, "wdth": 100}, 176)
    scalar.add_value({"wght": 900, "wdth": 100}, 221)
    scalar.add_value({"wght": 100, "wdth": 62.5}, 98)
    scalar.add_value({"wght": 400, "wdth": 62.5}, 111)
    scalar.add_value({"wght": 900, "wdth": 62.5}, 161)
    scalar.add_value({"wght": 705, "wdth": 62.5}, 136)

    # Build a reference model with explicit axisOrder matching builder axis order.
    triples = builder.axis_triples
    locations = [
        {tag: normalizeValue(val, triples[tag]) for tag, val in location}
        for location in scalar.values.keys()
    ]
    ref_model = VariationModel(locations, axisOrder=["wght", "wdth"])
    ref_deltas, ref_supports = ref_model.getDeltasAndSupports(
        list(scalar.values.values()), round=round
    )

    # VariableScalarBuilder.model() should produce the same deltas
    deltas, supports = builder.get_deltas_and_supports(scalar)

    assert deltas == ref_deltas
    assert supports == ref_supports


def test_deprecated_add_to_variation_store():
    """The deprecated VariableScalar.add_to_variation_store() shim should
    produce the same result as going through VariableScalarBuilder, while
    emitting a DeprecationWarning.

    This is the pattern used by babelfont + fontFeatures:
    https://github.com/simoncozens/babelfont/blob/3.1.3/src/babelfont/Font.py#L205-L206
    https://github.com/simoncozens/fontFeatures/blob/v1.9.0/Lib/fontFeatures/ttLib/Routine.py#L46
    """
    axes = [
        SimpleNamespace(axisTag="wght", minValue=100, defaultValue=400, maxValue=900),
        SimpleNamespace(axisTag="wdth", minValue=75, defaultValue=100, maxValue=125),
    ]

    scalar = VariableScalar()
    scalar.axes = axes
    scalar.add_value({"wght": 100, "wdth": 100}, 10)
    scalar.add_value({"wght": 400, "wdth": 100}, 20)
    scalar.add_value({"wght": 900, "wdth": 100}, 40)

    # Use the deprecated shim (like fontFeatures does)
    store_builder = OnlineVarStoreBuilder([ax.axisTag for ax in axes])
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always", DeprecationWarning)
        default, index = scalar.add_to_variation_store(store_builder)
        assert len(w) == 1
        assert "deprecated" in str(w[0].message).lower()

    assert default == 20
    assert index is not None

    # Compare with the new API
    builder = VariableScalarBuilder(
        axis_triples={
            ax.axisTag: (ax.minValue, ax.defaultValue, ax.maxValue) for ax in axes
        },
        axis_mappings={},
        model_cache={},
    )
    store_builder2 = OnlineVarStoreBuilder([ax.axisTag for ax in axes])
    default2, index2 = builder.add_to_variation_store(scalar, store_builder2)

    assert default == default2
    assert index == index2
