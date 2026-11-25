from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from fontTools.designspaceLib import AxisDescriptor, DesignSpaceDocument
from fontTools.feaLib.error import FeatureLibError
from fontTools.ttLib.ttFont import TTFont
from fontTools.varLib.models import (
    VariationModel,
    noRound,
    normalizeValue,
    piecewiseLinearMap,
)

import typing
import warnings

if typing.TYPE_CHECKING:
    from typing import Self

LocationTuple = tuple[tuple[str, float], ...]
"""A hashable location."""


def Location(location: Mapping[str, float]) -> LocationTuple:
    """Create a hashable location from a dictionary-like location."""
    return tuple(sorted(location.items()))


#: The unit letters allowed on axis values, following the Adobe variable
#: feature syntax: ``u`` user units, ``d`` designer units, ``n`` normalized
#: coordinates (-1..1).
AXIS_UNITS = frozenset("udn")


@dataclass(frozen=True)
class AxisValue:
    """A single axis value as written in a feature file.

    The numeric ``value`` is expressed in one of three scales given by
    ``unit``: ``"u"`` user-space units, ``"d"`` designer-space units, or
    ``"n"`` normalized coordinates (-1..1, 0 is the axis default).
    ``adjacent`` is optionally ``+1`` or ``-1`` for the F2dot14 adjacent
    position suffixes (``wght=600d+`` / ``wght=600d-``).
    ``explicit_unit`` is False for the legacy unitless syntax, which
    serializes without a unit letter for backwards compatibility.
    """

    value: float
    unit: str = "u"
    adjacent: int = 0
    explicit_unit: bool = True

    def asFea(self) -> str:
        text = (
            str(int(self.value)) if float(self.value).is_integer() else str(self.value)
        )
        if self.adjacent > 0:
            suffix = "+"
        elif self.adjacent < 0:
            suffix = "-"
        else:
            suffix = ""
        if self.explicit_unit:
            return f"{text}{self.unit}{suffix}"
        return f"{text}{suffix}"


#: A location as written in a feature file: an ordered tuple of
#: ``(axis tag, AxisValue)`` pairs.
RawLocation = tuple[tuple[str, AxisValue], ...]

#: F2dot14 precision: one normalized unit is split into 2**14 steps.
F2DOT14_STEP = 1.0 / (1 << 14)


def _denormalizeValue(value: float, triple: tuple[float, float, float]) -> float:
    """Inverse of :func:`normalizeValue`: map a normalized coordinate back to
    user-space values for the given (minimum, default, maximum) triple."""
    minimum, default, maximum = triple
    if value == 0:
        return default
    if value < 0:
        return default + value * (default - minimum)
    return default + value * (maximum - default)


def _inverse_mapping(mapping: Mapping[float, float]) -> dict[float, float]:
    return {design: user for user, design in mapping.items()}


class VariableScalar:
    """A scalar with different values at different points in the designspace."""

    values: dict[LocationTuple, int]
    """The values across various user-locations. Must always include the default
    location by time of building.

    Values written with axis units (``u``/``d``/``n``) start out unresolved in
    :attr:`raw_values`; :meth:`VariableScalarBuilder.resolve` converts them to
    plain user-space locations and fills this dictionary."""

    raw_values: list[tuple[RawLocation | None, int]]
    """The parsed (location, value) pairs in source order, with ``None``
    marking the bare default-location value."""

    def __init__(self, location_value=None):
        self.values = {
            Location(location): value
            for location, value in (location_value or {}).items()
        }
        self.raw_values = [
            (
                (
                    tuple(
                        (axis, AxisValue(float(coord), unit="u", explicit_unit=False))
                        for axis, coord in location
                    )
                    if location
                    else None
                ),
                value,
            )
            for location, value in (location_value or {}).items()
        ]
        # Deprecated: only used by the add_to_variation_store() backwards-compat
        # shim. New code should use VariableScalarBuilder instead.
        self.axes = []

    def __repr__(self):
        items = []
        for location, value in self.raw_values:
            if location is None:
                items.append("%i" % value)
            else:
                loc = ",".join(f"{ax}={axval.asFea()}" for ax, axval in location)
                items.append("%s:%i" % (loc, value))
        return "(" + (" ".join(items)) + ")"

    @property
    def does_vary(self) -> bool:
        values = list(self.values.values())
        return any(v != values[0] for v in values[1:])

    def add_value(self, location: Mapping[str, float], value: int):
        self.values[Location(location)] = value
        self.raw_values.append(
            (
                (
                    tuple(
                        (axis, AxisValue(float(coord), unit="u", explicit_unit=False))
                        for axis, coord in Location(location)
                    )
                    if location
                    else None
                ),
                value,
            )
        )

    def add_raw_value(self, location: RawLocation | None, value: int):
        """Add a value at a location expressed with axis units (``u``/``d``/
        ``n``). The location stays unresolved until the scalar is built."""
        self.raw_values.append((location, value))

    def add_to_variation_store(self, store_builder, model_cache=None, avar=None):
        """Deprecated: use VariableScalarBuilder.add_to_variation_store() instead."""
        warnings.warn(
            "VariableScalar.add_to_variation_store() is deprecated. "
            "Use VariableScalarBuilder.add_to_variation_store() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        if not self.axes:
            raise ValueError(
                ".axes must be defined on variable scalar before calling "
                "add_to_variation_store()"
            )
        builder = VariableScalarBuilder(
            axis_triples={
                ax.axisTag: (ax.minValue, ax.defaultValue, ax.maxValue)
                for ax in self.axes
            },
            axis_mappings=({} if avar is None else dict(avar.segments)),
            model_cache=model_cache if model_cache is not None else {},
        )
        return builder.add_to_variation_store(self, store_builder)


@dataclass
class VariableScalarBuilder:
    """A helper class for building variable scalars, or otherwise interrogating
    their variation model for interpolation or similar."""

    axis_triples: dict[str, tuple[float, float, float]]
    """Minimum, default, and maximum for each axis in user-coordinates."""
    axis_mappings: dict[str, Mapping[float, float]]
    """Optional mappings from normalized user-coordinates to normalized
    design-coordinates."""

    model_cache: dict[tuple[LocationTuple, ...], VariationModel]
    """We often use the same exact locations (i.e. font sources) for a large
    number of variable scalars. Instead of creating a model for each, cache
    them. Cache by user-location to avoid repeated mapping computations."""

    design_axis_triples: dict[str, tuple[float, float, float]] | None = None
    """Minimum, default, and maximum for each axis in designer-coordinates.
    Required to resolve values written in designer units (``d``). When absent,
    designer units are treated as identical to user units."""

    def _resolve_axis_value(
        self, axtag: str, axis_value: AxisValue, fea_location=None
    ) -> float:
        """Resolve one axis value (with its u/d/n unit and optional adjacent
        position suffix) to a user-space coordinate."""

        if axtag not in self.axis_triples:
            raise FeatureLibError("Unknown axis %s" % axtag, fea_location)

        unit, value, adjacent = axis_value.unit, axis_value.value, axis_value.adjacent
        if unit == "u":
            return value
        if unit == "n":
            # The adjacent step is defined in normalized F2dot14 space.
            normalized = value + adjacent * F2DOT14_STEP if adjacent else value
            return _denormalizeValue(normalized, self.axis_triples[axtag])
        if unit != "d":  # pragma: no cover - guarded by the parser
            raise FeatureLibError(
                "Unknown axis unit %r (expected one of u, d, n)" % unit, fea_location
            )

        # Designer units. Without an explicit designspace mapping the
        # designer scale is identical to the user scale, so 'd' behaves like
        # 'u' and any avar mapping is applied later during normalization.
        design_triple = (
            self.design_axis_triples.get(axtag)
            if self.design_axis_triples is not None
            else None
        )
        mapping = self.axis_mappings.get(axtag)
        if design_triple is None or mapping is None:
            return value

        design_normalized = normalizeValue(value, design_triple)
        if adjacent:
            design_normalized += adjacent * F2DOT14_STEP
        user_normalized = piecewiseLinearMap(
            design_normalized, _inverse_mapping(mapping)
        )
        return _denormalizeValue(user_normalized, self.axis_triples[axtag])

    def resolve_location(
        self, raw_location: RawLocation, fea_location=None
    ) -> LocationTuple:
        """Resolve a location written with axis units (u/d/n) to a fully
        specified user-space location, filling unmentioned axes with their
        user-space defaults."""

        full = {}
        for axtag, axis_value in raw_location:
            full[axtag] = self._resolve_axis_value(axtag, axis_value, fea_location)
        for axtag, (_, axis_default, _) in self.axis_triples.items():
            if axtag not in full:
                full[axtag] = axis_default
        return Location(full)

    def resolve(self, scalar: VariableScalar, fea_location=None) -> VariableScalar:
        """Resolve all of a scalar's raw (unit-bearing) locations into
        user-space :attr:`VariableScalar.values` in place."""

        values = {}
        for raw_location, value in scalar.raw_values:
            if raw_location is None:
                location = Location(
                    {tag: default for tag, (_, default, _) in self.axis_triples.items()}
                )
            else:
                location = self.resolve_location(raw_location, fea_location)
            if location in values:
                raise ValueError(
                    "Duplicate value for location %s"
                    % ",".join("%s=%s" % item for item in location)
                )
            values[location] = value
        scalar.values = values
        return scalar

    @classmethod
    def from_ttf(cls, ttf: TTFont) -> Self:
        return cls(
            axis_triples={
                axis.axisTag: (axis.minValue, axis.defaultValue, axis.maxValue)
                for axis in ttf["fvar"].axes
            },
            axis_mappings=(
                {}
                if (avar := ttf.get("avar")) is None
                else {axis: segments for axis, segments in avar.segments.items()}
            ),
            model_cache={},
        )

    @classmethod
    def from_designspace(cls, doc: DesignSpaceDocument) -> Self:
        return cls(
            axis_triples={
                axis.tag: (axis.minimum, axis.default, axis.maximum)
                for axis in doc.axes
            },
            axis_mappings={
                axis.tag: {
                    normalizeValue(
                        user, (axis.minimum, axis.default, axis.maximum)
                    ): normalizeValue(
                        design,
                        (
                            axis.map_forward(axis.minimum),
                            axis.map_forward(axis.default),
                            axis.map_forward(axis.maximum),
                        ),
                        allow_decreasing=True,
                    )
                    for user, design in axis.map
                }
                for axis in doc.axes
                if axis.map
            },
            model_cache={},
            design_axis_triples={
                axis.tag: (
                    axis.map_forward(axis.minimum),
                    axis.map_forward(axis.default),
                    axis.map_forward(axis.maximum),
                )
                for axis in doc.axes
                if isinstance(axis, AxisDescriptor) and axis.map
            },
        )

    def _fully_specify_location(self, location: LocationTuple) -> LocationTuple:
        """Validate and fully-specify a user-space location by filling in
        missing axes with their user-space defaults."""

        full = {}
        for axtag, value in location:
            if axtag not in self.axis_triples:
                raise ValueError("Unknown axis %s in %s" % (axtag, location))
            full[axtag] = value

        for axtag, (_, axis_default, _) in self.axis_triples.items():
            if axtag not in full:
                full[axtag] = axis_default

        return Location(full)

    def _normalize_location(self, location: LocationTuple) -> dict[str, float]:
        """Normalize a user-space location, applying avar mappings if present.

        TODO: This only handles avar1 (per-axis piecewise linear mappings),
        not avar2 (multi-dimensional mappings).
        """

        result = {}
        for axtag, value in location:
            axis_min, axis_default, axis_max = self.axis_triples[axtag]
            normalized = normalizeValue(value, (axis_min, axis_default, axis_max))
            mapping = self.axis_mappings.get(axtag)
            if mapping is not None:
                normalized = piecewiseLinearMap(normalized, mapping)
            result[axtag] = normalized

        return result

    def _full_locations_and_values(
        self, scalar: VariableScalar
    ) -> list[tuple[LocationTuple, int]]:
        """Return a list of (fully-specified user-space location, value) pairs,
        preserving order and length of scalar.values."""

        return [
            (self._fully_specify_location(loc), val)
            for loc, val in scalar.values.items()
        ]

    def default_value(self, scalar: VariableScalar) -> int:
        """Get the default value of a variable scalar."""

        default_loc = Location(
            {tag: default for tag, (_, default, _) in self.axis_triples.items()}
        )
        for location, value in self._full_locations_and_values(scalar):
            if location == default_loc:
                return value

        raise ValueError("Default value could not be found")

    def value_at_location(
        self, scalar: VariableScalar, location: LocationTuple
    ) -> float:
        """Interpolate the value of a scalar from a user-location."""

        location = self._fully_specify_location(location)
        pairs = self._full_locations_and_values(scalar)

        # If user location matches exactly, no axis mapping or variation model needed.
        for loc, val in pairs:
            if loc == location:
                return val

        values = [val for _, val in pairs]
        normalized_location = self._normalize_location(location)

        value = self.model(scalar).interpolateFromMasters(normalized_location, values)
        if value is None:
            raise ValueError("Insufficient number of values to interpolate")

        return value

    def model(self, scalar: VariableScalar) -> VariationModel:
        """Return a variation model based on a scalar's values.

        Variable scalars with the same fully-specified user-locations will use
        the same cached variation model."""

        pairs = self._full_locations_and_values(scalar)
        cache_key = tuple(loc for loc, _ in pairs)

        cached_model = self.model_cache.get(cache_key)
        if cached_model is not None:
            return cached_model

        normalized_locations = [self._normalize_location(loc) for loc, _ in pairs]
        axisOrder = list(self.axis_triples.keys())
        model = self.model_cache[cache_key] = VariationModel(
            normalized_locations, axisOrder=axisOrder
        )

        return model

    def get_deltas_and_supports(self, scalar: VariableScalar):
        """Calculate deltas and supports from this scalar's variation model."""
        values = list(scalar.values.values())
        return self.model(scalar).getDeltasAndSupports(values, round=round)

    def add_to_variation_store(
        self, scalar: VariableScalar, store_builder
    ) -> tuple[int, int]:
        """Serialize this scalar's variation model to a store, returning the
        default value and variation index."""

        deltas, supports = self.get_deltas_and_supports(scalar)
        store_builder.setSupports(supports)
        index = store_builder.storeDeltas(deltas, round=noRound)

        # NOTE: Default value should be an exact integer by construction of
        #       VariableScalar.
        return int(self.default_value(scalar)), index
