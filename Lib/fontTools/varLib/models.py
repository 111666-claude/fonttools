"""Variation fonts interpolation models."""

from __future__ import annotations

__all__ = [
    "normalizeValue",
    "normalizeLocation",
    "supportScalar",
    "piecewiseLinearMap",
    "ReverseSolution",
    "ReverseMapResult",
    "reversePiecewiseLinearMap",
    "VariationModel",
]

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING
from fontTools.misc.roundTools import noRound
from .errors import VariationModelError

if TYPE_CHECKING:
    from typing import Mapping, Sequence


def nonNone(lst):
    return [l for l in lst if l is not None]


def allNone(lst):
    return all(l is None for l in lst)


def allEqualTo(ref, lst, mapper=None):
    if mapper is None:
        return all(ref == item for item in lst)

    mapped = mapper(ref)
    return all(mapped == mapper(item) for item in lst)


def allEqual(lst, mapper=None):
    if not lst:
        return True
    it = iter(lst)
    try:
        first = next(it)
    except StopIteration:
        return True
    return allEqualTo(first, it, mapper=mapper)


def subList(truth, lst):
    assert len(truth) == len(lst)
    return [l for l, t in zip(lst, truth) if t]


def normalizeValue(
    v: float,
    triple: Sequence[float],
    extrapolate: bool = False,
    *,
    allow_decreasing: bool = False,
) -> float:
    """Normalizes value based on a min/default/max triple.

    >>> normalizeValue(400, (100, 400, 900))
    0.0
    >>> normalizeValue(100, (100, 400, 900))
    -1.0
    >>> normalizeValue(650, (100, 400, 900))
    0.5

    If allow_decreasing is true, the triple can also be decreasing (e.g. the
    design values of a designspace axis whose map falls as the user values
    rise). Its first value still maps to -1 and its last to +1, so -1 is always
    the minimum of the user axis, even when that is the largest number in the
    triple.

    >>> normalizeValue(38, (38, 28, 23), allow_decreasing=True)
    -1.0
    >>> normalizeValue(33, (38, 28, 23), allow_decreasing=True)
    -0.5
    >>> normalizeValue(23, (38, 28, 23), allow_decreasing=True)
    1.0
    """
    lower, default, upper = triple
    decreasing = allow_decreasing and lower > upper
    if not (lower >= default >= upper if decreasing else lower <= default <= upper):
        raise ValueError(
            f"Invalid axis values, must be minimum, default, maximum: "
            f"{lower:3.3f}, {default:3.3f}, {upper:3.3f}"
        )
    if decreasing:
        normalized = normalizeValue(v, (upper, default, lower), extrapolate)
        return -normalized if normalized else 0.0
    if not extrapolate:
        v = max(min(v, upper), lower)

    if v == default or lower == upper:
        return 0.0

    if (v < default and lower != default) or (v > default and upper == default):
        return (v - default) / (default - lower)
    else:
        assert (v > default and upper != default) or (
            v < default and lower == default
        ), f"Ooops... v={v}, triple=({lower}, {default}, {upper})"
        return (v - default) / (upper - default)


def normalizeLocation(
    location: Mapping[str, float],
    axes: Mapping[str, tuple[float, float, float]],
    extrapolate: bool = False,
    *,
    validate: bool = False,
    allow_decreasing: bool = False,
) -> dict[str, float]:
    """Normalizes location based on axis min/default/max values from axes.

    >>> axes = {"wght": (100, 400, 900)}
    >>> normalizeLocation({"wght": 400}, axes)
    {'wght': 0.0}
    >>> normalizeLocation({"wght": 100}, axes)
    {'wght': -1.0}
    >>> normalizeLocation({"wght": 900}, axes)
    {'wght': 1.0}
    >>> normalizeLocation({"wght": 650}, axes)
    {'wght': 0.5}
    >>> normalizeLocation({"wght": 1000}, axes)
    {'wght': 1.0}
    >>> normalizeLocation({"wght": 0}, axes)
    {'wght': -1.0}
    >>> axes = {"wght": (0, 0, 1000)}
    >>> normalizeLocation({"wght": 0}, axes)
    {'wght': 0.0}
    >>> normalizeLocation({"wght": -1}, axes)
    {'wght': 0.0}
    >>> normalizeLocation({"wght": 1000}, axes)
    {'wght': 1.0}
    >>> normalizeLocation({"wght": 500}, axes)
    {'wght': 0.5}
    >>> normalizeLocation({"wght": 1001}, axes)
    {'wght': 1.0}
    >>> axes = {"wght": (0, 1000, 1000)}
    >>> normalizeLocation({"wght": 0}, axes)
    {'wght': -1.0}
    >>> normalizeLocation({"wght": -1}, axes)
    {'wght': -1.0}
    >>> normalizeLocation({"wght": 500}, axes)
    {'wght': -0.5}
    >>> normalizeLocation({"wght": 1000}, axes)
    {'wght': 0.0}
    >>> normalizeLocation({"wght": 1001}, axes)
    {'wght': 0.0}
    """
    if validate:
        assert set(location.keys()) <= set(axes.keys()), set(location.keys()) - set(
            axes.keys()
        )
    out = {}
    for tag, triple in axes.items():
        v = location.get(tag, triple[1])
        out[tag] = normalizeValue(
            v, triple, extrapolate=extrapolate, allow_decreasing=allow_decreasing
        )
    return out


def supportScalar(location, support, ot=True, extrapolate=False, axisRanges=None):
    """Returns the scalar multiplier at location, for a master
    with support.  If ot is True, then a peak value of zero
    for support of an axis means "axis does not participate".  That
    is how OpenType Variation Font technology works.

    If extrapolate is True, axisRanges must be a dict that maps axis
    names to (axisMin, axisMax) tuples.

      >>> supportScalar({}, {})
      1.0
      >>> supportScalar({'wght':.2}, {})
      1.0
      >>> supportScalar({'wght':.2}, {'wght':(0,2,3)})
      0.1
      >>> supportScalar({'wght':2.5}, {'wght':(0,2,4)})
      0.75
      >>> supportScalar({'wght':2.5, 'wdth':0}, {'wght':(0,2,4), 'wdth':(-1,0,+1)})
      0.75
      >>> supportScalar({'wght':2.5, 'wdth':.5}, {'wght':(0,2,4), 'wdth':(-1,0,+1)}, ot=False)
      0.375
      >>> supportScalar({'wght':2.5, 'wdth':0}, {'wght':(0,2,4), 'wdth':(-1,0,+1)})
      0.75
      >>> supportScalar({'wght':2.5, 'wdth':.5}, {'wght':(0,2,4), 'wdth':(-1,0,+1)})
      0.75
      >>> supportScalar({'wght':3}, {'wght':(0,1,2)}, extrapolate=True, axisRanges={'wght':(0, 2)})
      -1.0
      >>> supportScalar({'wght':-1}, {'wght':(0,1,2)}, extrapolate=True, axisRanges={'wght':(0, 2)})
      -1.0
      >>> supportScalar({'wght':3}, {'wght':(0,2,2)}, extrapolate=True, axisRanges={'wght':(0, 2)})
      1.5
      >>> supportScalar({'wght':-1}, {'wght':(0,2,2)}, extrapolate=True, axisRanges={'wght':(0, 2)})
      -0.5
    """
    if extrapolate and axisRanges is None:
        raise TypeError("axisRanges must be passed when extrapolate is True")
    scalar = 1.0
    for axis, (lower, peak, upper) in support.items():
        if ot:
            # OpenType-specific case handling
            if peak == 0.0:
                continue
            if lower > peak or peak > upper:
                continue
            if lower < 0.0 and upper > 0.0:
                continue
            v = location.get(axis, 0.0)
        else:
            assert axis in location
            v = location[axis]
        if v == peak:
            continue

        if extrapolate:
            axisMin, axisMax = axisRanges[axis]
            if v < axisMin and lower <= axisMin:
                if peak <= axisMin and peak < upper:
                    scalar *= (v - upper) / (peak - upper)
                    continue
                elif axisMin < peak:
                    scalar *= (v - lower) / (peak - lower)
                    continue
            elif axisMax < v and axisMax <= upper:
                if axisMax <= peak and lower < peak:
                    scalar *= (v - lower) / (peak - lower)
                    continue
                elif peak < axisMax:
                    scalar *= (v - upper) / (peak - upper)
                    continue

        if v <= lower or upper <= v:
            scalar = 0.0
            break

        if v < peak:
            scalar *= (v - lower) / (peak - lower)
        else:  # v > peak
            scalar *= (v - upper) / (peak - upper)
    return scalar


class VariationModel(object):
    """Locations must have the base master at the origin (ie. 0).

    If axis-ranges are not provided, values are assumed to be normalized to
    the range [-1, 1].

    If the extrapolate argument is set to True, then values are extrapolated
    outside the axis range.

      >>> from pprint import pprint
      >>> axisRanges = {'wght': (-180, +180), 'wdth': (-1, +1)}
      >>> locations = [ \
      {'wght':100}, \
      {'wght':-100}, \
      {'wght':-180}, \
      {'wdth':+.3}, \
      {'wght':+120,'wdth':.3}, \
      {'wght':+120,'wdth':.2}, \
      {}, \
      {'wght':+180,'wdth':.3}, \
      {'wght':+180}, \
      ]
      >>> model = VariationModel(locations, axisOrder=['wght'], axisRanges=axisRanges)
      >>> pprint(model.locations)
      [{},
       {'wght': -100},
       {'wght': -180},
       {'wght': 100},
       {'wght': 180},
       {'wdth': 0.3},
       {'wdth': 0.3, 'wght': 180},
       {'wdth': 0.3, 'wght': 120},
       {'wdth': 0.2, 'wght': 120}]
      >>> pprint(model.deltaWeights)
      [{},
       {0: 1.0},
       {0: 1.0},
       {0: 1.0},
       {0: 1.0},
       {0: 1.0},
       {0: 1.0, 4: 1.0, 5: 1.0},
       {0: 1.0, 3: 0.75, 4: 0.25, 5: 1.0, 6: 0.6666666666666666},
       {0: 1.0,
        3: 0.75,
        4: 0.25,
        5: 0.6666666666666667,
        6: 0.4444444444444445,
        7: 0.6666666666666667}]
    """

    def __init__(
        self, locations, axisOrder=None, extrapolate=False, *, axisRanges=None
    ):
        locations = [{k: v for k, v in loc.items() if v != 0.0} for loc in locations]

        if len(set(tuple(sorted(l.items())) for l in locations)) != len(locations):
            raise VariationModelError("Locations must be unique.")

        self.origLocations = locations
        self.axisOrder = axisOrder if axisOrder is not None else []
        self.extrapolate = extrapolate
        if axisRanges is None:
            if extrapolate:
                axisRanges = self.computeAxisRanges(locations)
            else:
                allAxes = {axis for loc in locations for axis in loc.keys()}
                axisRanges = {axis: (-1, 1) for axis in allAxes}
        self.axisRanges = axisRanges
        keyFunc = self.getMasterLocationsSortKeyFunc(
            locations, axisOrder=self.axisOrder
        )
        self.locations = sorted(locations, key=keyFunc)

        # Mapping from user's master order to our master order
        self.mapping = [self.locations.index(l) for l in locations]
        self.reverseMapping = [locations.index(l) for l in self.locations]

        self._computeMasterSupports()
        self._subModels = {}

    def getSubModel(self, items):
        """Return a sub-model and the items that are not None.

        The sub-model is necessary for working with the subset
        of items when some are None.

        The sub-model is cached."""
        if None not in items:
            return self, items
        key = tuple(v is not None for v in items)
        subModel = self._subModels.get(key)
        if subModel is None:
            subModel = VariationModel(
                subList(key, self.origLocations),
                self.axisOrder,
                extrapolate=self.extrapolate,
                axisRanges=self.axisRanges,
            )
            self._subModels[key] = subModel
        return subModel, subList(key, items)

    @staticmethod
    def computeAxisRanges(locations):
        axisRanges = {}
        allAxes = {axis for loc in locations for axis in loc.keys()}
        for loc in locations:
            for axis in allAxes:
                value = loc.get(axis, 0)
                axisMin, axisMax = axisRanges.get(axis, (value, value))
                axisRanges[axis] = min(value, axisMin), max(value, axisMax)
        return axisRanges

    @staticmethod
    def getMasterLocationsSortKeyFunc(locations, axisOrder=[]):
        if {} not in locations:
            raise VariationModelError("Base master not found.")
        axisPoints = {}
        for loc in locations:
            if len(loc) != 1:
                continue
            axis = next(iter(loc))
            value = loc[axis]
            if axis not in axisPoints:
                axisPoints[axis] = {0.0}
            assert (
                value not in axisPoints[axis]
            ), 'Value "%s" in axisPoints["%s"] -->  %s' % (value, axis, axisPoints)
            axisPoints[axis].add(value)

        def getKey(axisPoints, axisOrder):
            def sign(v):
                return -1 if v < 0 else +1 if v > 0 else 0

            def key(loc):
                rank = len(loc)
                onPointAxes = [
                    axis
                    for axis, value in loc.items()
                    if axis in axisPoints and value in axisPoints[axis]
                ]
                orderedAxes = [axis for axis in axisOrder if axis in loc]
                orderedAxes.extend(
                    [axis for axis in sorted(loc.keys()) if axis not in axisOrder]
                )
                return (
                    rank,  # First, order by increasing rank
                    -len(onPointAxes),  # Next, by decreasing number of onPoint axes
                    tuple(
                        axisOrder.index(axis) if axis in axisOrder else 0x10000
                        for axis in orderedAxes
                    ),  # Next, by known axes
                    tuple(orderedAxes),  # Next, by all axes
                    tuple(
                        sign(loc[axis]) for axis in orderedAxes
                    ),  # Next, by signs of axis values
                    tuple(
                        abs(loc[axis]) for axis in orderedAxes
                    ),  # Next, by absolute value of axis values
                )

            return key

        ret = getKey(axisPoints, axisOrder)
        return ret

    def reorderMasters(self, master_list, mapping):
        # For changing the master data order without
        # recomputing supports and deltaWeights.
        new_list = [master_list[idx] for idx in mapping]
        self.origLocations = [self.origLocations[idx] for idx in mapping]
        locations = [
            {k: v for k, v in loc.items() if v != 0.0} for loc in self.origLocations
        ]
        self.mapping = [self.locations.index(l) for l in locations]
        self.reverseMapping = [locations.index(l) for l in self.locations]
        self._subModels = {}
        return new_list

    def _computeMasterSupports(self):
        self.supports = []
        regions = self._locationsToRegions()
        for i, region in enumerate(regions):
            locAxes = set(region.keys())
            # Walk over previous masters now
            for prev_region in regions[:i]:
                # Master with different axes do not participate
                if set(prev_region.keys()) != locAxes:
                    continue
                # If it's NOT in the current box, it does not participate
                relevant = True
                for axis, (lower, peak, upper) in region.items():
                    if not (
                        prev_region[axis][1] == peak
                        or lower < prev_region[axis][1] < upper
                    ):
                        relevant = False
                        break
                if not relevant:
                    continue

                # Split the box for new master; split in whatever direction
                # that has largest range ratio.
                #
                # For symmetry, we actually cut across multiple axes
                # if they have the largest, equal, ratio.
                # https://github.com/fonttools/fonttools/commit/7ee81c8821671157968b097f3e55309a1faa511e#commitcomment-31054804

                bestAxes = {}
                bestRatio = -1
                for axis in prev_region.keys():
                    val = prev_region[axis][1]
                    assert axis in region
                    lower, locV, upper = region[axis]
                    newLower, newUpper = lower, upper
                    if val < locV:
                        newLower = val
                        ratio = (val - locV) / (lower - locV)
                    elif locV < val:
                        newUpper = val
                        ratio = (val - locV) / (upper - locV)
                    else:  # val == locV
                        # Can't split box in this direction.
                        continue
                    if ratio > bestRatio:
                        bestAxes = {}
                        bestRatio = ratio
                    if ratio == bestRatio:
                        bestAxes[axis] = (newLower, locV, newUpper)

                for axis, triple in bestAxes.items():
                    region[axis] = triple
            self.supports.append(region)
        self._computeDeltaWeights()

    def _locationsToRegions(self):
        locations = self.locations
        axisRanges = self.axisRanges

        regions = []
        for loc in locations:
            region = {}
            for axis, locV in loc.items():
                if locV > 0:
                    region[axis] = (0, locV, axisRanges[axis][1])
                else:
                    region[axis] = (axisRanges[axis][0], locV, 0)
            regions.append(region)
        return regions

    def _computeDeltaWeights(self):
        self.deltaWeights = []
        for i, loc in enumerate(self.locations):
            deltaWeight = {}
            # Walk over previous masters now, populate deltaWeight
            for j, support in enumerate(self.supports[:i]):
                scalar = supportScalar(loc, support)
                if scalar:
                    deltaWeight[j] = scalar
            self.deltaWeights.append(deltaWeight)

    def getDeltas(self, masterValues, *, round=noRound):
        assert len(masterValues) == len(self.deltaWeights), (
            len(masterValues),
            len(self.deltaWeights),
        )
        mapping = self.reverseMapping
        out = []
        for i, weights in enumerate(self.deltaWeights):
            delta = masterValues[mapping[i]]
            for j, weight in weights.items():
                if weight == 1:
                    delta -= out[j]
                else:
                    delta -= out[j] * weight
            out.append(round(delta))
        return out

    def getDeltasAndSupports(self, items, *, round=noRound):
        model, items = self.getSubModel(items)
        return model.getDeltas(items, round=round), model.supports

    def getScalars(self, loc):
        """Return scalars for each delta, for the given location.
        If interpolating many master-values at the same location,
        this function allows speed up by fetching the scalars once
        and using them with interpolateFromMastersAndScalars()."""
        return [
            supportScalar(
                loc, support, extrapolate=self.extrapolate, axisRanges=self.axisRanges
            )
            for support in self.supports
        ]

    def getMasterScalars(self, targetLocation):
        """Return multipliers for each master, for the given location.
        If interpolating many master-values at the same location,
        this function allows speed up by fetching the scalars once
        and using them with interpolateFromValuesAndScalars().

        Note that the scalars used in interpolateFromMastersAndScalars(),
        are *not* the same as the ones returned here. They are the result
        of getScalars()."""
        out = self.getScalars(targetLocation)
        for i, weights in reversed(list(enumerate(self.deltaWeights))):
            for j, weight in weights.items():
                out[j] -= out[i] * weight

        out = [out[self.mapping[i]] for i in range(len(out))]
        return out

    @staticmethod
    def interpolateFromValuesAndScalars(values, scalars):
        """Interpolate from values and scalars coefficients.

        If the values are master-values, then the scalars should be
        fetched from getMasterScalars().

        If the values are deltas, then the scalars should be fetched
        from getScalars(); in which case this is the same as
        interpolateFromDeltasAndScalars().
        """
        v = None
        assert len(values) == len(scalars)
        for value, scalar in zip(values, scalars):
            if not scalar:
                continue
            contribution = value * scalar
            if v is None:
                v = contribution
            else:
                v += contribution
        return v

    @staticmethod
    def interpolateFromDeltasAndScalars(deltas, scalars):
        """Interpolate from deltas and scalars fetched from getScalars()."""
        return VariationModel.interpolateFromValuesAndScalars(deltas, scalars)

    def interpolateFromDeltas(self, loc, deltas):
        """Interpolate from deltas, at location loc."""
        scalars = self.getScalars(loc)
        return self.interpolateFromDeltasAndScalars(deltas, scalars)

    def interpolateFromMasters(self, loc, masterValues, *, round=noRound):
        """Interpolate from master-values, at location loc."""
        scalars = self.getMasterScalars(loc)
        return self.interpolateFromValuesAndScalars(masterValues, scalars)

    def interpolateFromMastersAndScalars(self, masterValues, scalars, *, round=noRound):
        """Interpolate from master-values, and scalars fetched from
        getScalars(), which is useful when you want to interpolate
        multiple master-values with the same location."""
        deltas = self.getDeltas(masterValues, round=round)
        return self.interpolateFromDeltasAndScalars(deltas, scalars)


def piecewiseLinearMap(v: float, mapping: Mapping[float, float]) -> float:
    keys = mapping.keys()
    if not keys:
        return v
    if v in keys:
        return mapping[v]
    k = min(keys)
    if v < k:
        return v + mapping[k] - k
    k = max(keys)
    if v > k:
        return v + mapping[k] - k
    # Interpolate
    a = max(k for k in keys if k < v)
    b = min(k for k in keys if k > v)
    va = mapping[a]
    vb = mapping[b]
    return va + (vb - va) * (v - a) / (b - a)


# Tolerance used by reversePiecewiseLinearMap to snap computed points onto
# mapping knots and to merge coincident solutions.  This is on the normalized
# (-1..1) coordinate scale used by avar, where 1e-12 is far below the F2Dot14
# quantization step (~6.1e-5) and still safely above ordinary float noise.
REVERSE_MAP_EPS = 1e-12


@dataclass(frozen=True)
class ReverseSolution:
    """One preimage of a target value under a piecewise-linear map.

    A solution is either a single input point (``kind == "point"``) or a
    closed input interval (``kind == "interval"``).  Intervals arise from
    flat segments of the mapping: every input inside
    ``[intervalStart, intervalEnd]`` maps to the same output, so the whole
    interval is a valid answer and no unique input exists.

    Attributes:
        kind: ``"point"`` or ``"interval"``.
        value: the input value (point solutions only; ``None`` otherwise).
        intervalStart/intervalEnd: inclusive input bounds (interval
            solutions only; ``None`` otherwise).
        explanation: human-readable description of which segment produced
            the solution, expressed in the same (normalized) coordinates
            as the mapping.
        segmentIndex: index of the responsible mapping segment, or
            ``None`` for extrapolation tails and identity maps.
    """

    kind: str
    explanation: str
    value: float | None = None
    intervalStart: float | None = None
    intervalEnd: float | None = None
    segmentIndex: int | None = None

    @property
    def isInterval(self) -> bool:
        return self.kind == "interval"


@dataclass(frozen=True)
class ReverseMapResult:
    """Result of a reverse lookup on a piecewise-linear map.

    Attributes:
        target: the requested output value.
        solutions: all distinct preimages, sorted by input position.
        reachable: whether the target is reached by at least one input.
        reason: when ``reachable`` is false, an explanation of why no
            preimage exists; otherwise an empty string.
        reachableRange: the map's overall output range ``(low, high)``
            over its key domain (a single interval, since a continuous
            map on an interval has a connected image); ``None`` for an
            empty mapping.
        domain: input interval ``[low, high]`` covered by the mapping
            keys, or ``None`` for an empty (identity) mapping.
        clip: whether the search was restricted to ``domain``.  When
            false, slope-1 extrapolation outside the outermost keys is
            also considered.
        unit: ``"normalized"`` for the math-level function; font-level
            wrappers rewrite this to ``"user"`` after denormalization.
        axis: optional axis tag, set by font-level wrappers.
    """

    target: float
    solutions: list[ReverseSolution]
    reachable: bool
    reason: str = ""
    reachableRange: tuple[float, float] | None = None
    domain: tuple[float, float] | None = None
    clip: bool = True
    unit: str = "normalized"
    axis: str | None = None

    @property
    def points(self) -> list[ReverseSolution]:
        return [s for s in self.solutions if not s.isInterval]

    @property
    def intervals(self) -> list[ReverseSolution]:
        return [s for s in self.solutions if s.isInterval]


def _mergeRanges(
    ranges: list[tuple[float, float]], eps: float
) -> tuple[float, float] | None:
    """Return the hull ``(low, high)`` of closed ``(low, high)`` ranges.

    A continuous piecewise-linear map on an interval has a connected
    image, so the per-segment output ranges always join into one
    interval; the eps-tolerant merge documents that rather than relying
    on it silently.
    """
    if not ranges:
        return None
    merged: list[tuple[float, float]] = []
    for low, high in sorted(ranges):
        if merged and low <= merged[-1][1] + eps:
            prevLow, prevHigh = merged[-1]
            merged[-1] = (prevLow, max(prevHigh, high))
        else:
            merged.append((low, high))
    return merged[0][0], merged[-1][1]


def reversePiecewiseLinearMap(
    target: float,
    mapping: Mapping[float, float],
    *,
    clip: bool = True,
    eps: float = REVERSE_MAP_EPS,
) -> ReverseMapResult:
    """Find every input ``x`` such that ``piecewiseLinearMap(x, mapping) == target``.

    The mapping is treated as a continuous piecewise-linear function of
    one variable, which covers non-monotone mappings (the same target can
    be reached several times), flat segments (whole interval preimages),
    repeated endpoint values, and arbitrary key/value orders.

    By default (``clip=True``) the search is restricted to the closed
    domain spanned by the mapping keys, matching the normalized -1..1
    range of an ``avar`` axis: a target outside the map's output range
    yields an unreachable result.  With ``clip=False`` the slope-1
    extrapolation used by :func:`piecewiseLinearMap` outside the
    outermost keys is also inverted, so every target is reachable except
    those falling into an interior output-range gap of a non-monotone
    map.

    An empty mapping is the identity map, whose preimage is the target
    itself.

    Returned solutions are de-duplicated, sorted by input position, and
    each carries an :attr:`ReverseSolution.explanation` string.

    >>> mapping = {-1.0: -1.0, 0.0: 0.0, 0.25: 0.5, 0.5: 0.5, 1.0: 1.0}
    >>> result = reversePiecewiseLinearMap(0.5, mapping)
    >>> [(s.kind, s.value, s.intervalStart, s.intervalEnd) for s in result.solutions]
    [('interval', None, 0.25, 0.5)]
    >>> reversePiecewiseLinearMap(0.75, mapping).points[0].value
    0.75
    >>> reversePiecewiseLinearMap(1.5, mapping).reachable
    False
    """
    # Empty mapping: identity.  piecewiseLinearMap(v, {}) == v for every v.
    if not mapping:
        point = ReverseSolution(
            kind="point",
            value=target,
            explanation="empty (identity) mapping: the preimage is the target itself",
        )
        return ReverseMapResult(
            target=target,
            solutions=[point],
            reachable=True,
            reachableRange=None,
            domain=None,
            clip=clip,
        )

    items = sorted(mapping.items())
    keys = [k for k, _ in items]
    values = [v for _, v in items]
    xMin, xMax = keys[0], keys[-1]

    # Single-key mapping: one input point maps to one output value.
    if len(items) == 1:
        x0, y0 = items[0]
        if abs(target - y0) <= eps:
            point = ReverseSolution(
                kind="point",
                value=x0,
                explanation=f"single-key mapping: only {x0:g} maps to {y0:g}",
            )
            return ReverseMapResult(
                target=target,
                solutions=[point],
                reachable=True,
                reachableRange=(y0, y0),
                domain=(x0, x0),
                clip=clip,
            )
        if not clip:
            # Slope-1 extrapolation on both sides of the lone key.
            tailX = target + x0 - y0
            point = ReverseSolution(
                kind="point",
                value=tailX,
                explanation=(
                    f"extrapolated from the single key {x0:g} -> {y0:g} "
                    f"(slope-1 tail)"
                ),
            )
            return ReverseMapResult(
                target=target,
                solutions=[point],
                reachable=True,
                reachableRange=(y0, y0),
                domain=(x0, x0),
                clip=False,
            )
        reason = (
            f"target {target:g} is not reached by the single-key mapping; "
            f"the only reachable output is {y0:g} at input {x0:g}"
        )
        return ReverseMapResult(
            target=target,
            solutions=[],
            reachable=False,
            reason=reason,
            reachableRange=(y0, y0),
            domain=(x0, x0),
            clip=clip,
        )

    # Reachable output ranges of the interior segments, merged.
    ranges: list[tuple[float, float]] = []
    for i in range(len(items) - 1):
        lo, hi = values[i], values[i + 1]
        if lo > hi:
            lo, hi = hi, lo
        ranges.append((lo, hi))
    reachableRange = _mergeRanges(ranges, eps)

    # Raw preimages.  Points carry an atBoundary flag: True when the target
    # is reached at a segment endpoint (a mapping knot), False for the
    # interior of a sloped segment.  The flag decides how a point merges
    # with a flat segment's interval later on.
    rawPoints: list[tuple[float, bool, str, int | None]] = []
    rawIntervals: list[tuple[float, float, str, int]] = []

    def addPoint(
        x: float, atBoundary: bool, explanation: str, segmentIndex: int | None
    ) -> None:
        for k, (px, pb, pe, ps) in enumerate(rawPoints):
            if abs(px - x) <= eps:
                # Keep one entry; the boundary flag is the OR of the two:
                # a knot reached from a flat side and a sloped side is both.
                rawPoints[k] = (px, pb or atBoundary, f"{pe}; also {explanation}", ps)
                return
        rawPoints.append((x, atBoundary, explanation, segmentIndex))

    def addInterval(lo: float, hi: float, explanation: str, segmentIndex: int) -> None:
        if hi < lo:
            lo, hi = hi, lo
        rawIntervals.append((lo, hi, explanation, segmentIndex))

    # Interior segments, including zero-length ones (duplicate keys).
    for i in range(len(items) - 1):
        a, va = keys[i], values[i]
        b, vb = keys[i + 1], values[i + 1]
        lo, hi = (va, vb) if va <= vb else (vb, va)

        if abs(vb - va) <= eps:
            # Flat (or numerically degenerate) segment: interval preimage.
            if lo - eps <= target <= hi + eps:
                addInterval(
                    a,
                    b,
                    f"flat segment #{i} [{a:g}, {b:g}] maps every input to {va:g}",
                    i,
                )
            continue

        if not (lo - eps <= target <= hi + eps):
            continue

        x = a + (target - va) * (b - a) / (vb - va)
        # Numerical safety for the segment's input bounds.
        x = min(max(x, min(a, b)), max(a, b))
        atBoundary = abs(target - va) <= eps or abs(target - vb) <= eps
        addPoint(
            x,
            atBoundary,
            f"interpolated on segment #{i} [{a:g}, {b:g}] -> [{va:g}, {vb:g}]",
            i,
        )

    # Extrapolation tails.  piecewiseLinearMap continues outside [xMin, xMax]
    # with slope 1: f(x) = x + yEnd - xEnd.  Inverting gives x = target + xEnd - yEnd.
    if not clip:
        x0, y0 = keys[0], values[0]
        tailX = target + x0 - y0
        if tailX <= xMin + eps:
            addPoint(
                min(tailX, xMin),
                abs(tailX - xMin) <= eps,
                f"extrapolated below the first key {x0:g} (slope-1 tail)",
                None,
            )
        xN, yN = keys[-1], values[-1]
        tailX = target + xN - yN
        if tailX >= xMax - eps:
            addPoint(
                max(tailX, xMax),
                abs(tailX - xMax) <= eps,
                f"extrapolated above the last key {xN:g} (slope-1 tail)",
                None,
            )

    # Normalize intervals first: merge flat segments that touch or overlap
    # (adjacent flat segments sharing a knot and mapping to the same output
    # form one continuous preimage).
    normIntervals: list[list] = []
    for ivLo, ivHi, expl, segIdx in sorted(rawIntervals):
        if normIntervals and ivLo <= normIntervals[-1][1] + eps:
            prev = normIntervals[-1]
            prev[1] = max(prev[1], ivHi)
            prev[2] = f"{prev[2]}; also {expl}"
        else:
            normIntervals.append([ivLo, ivHi, expl, segIdx])

    # Fold point preimages into the normalized intervals:
    #  - a boundary point (mapping knot) inside or on an interval already
    #    belongs to the flat segment -> drop it;
    #  - an interior point of a sloped segment touching an interval's outer
    #    edge extends the interval, because the sloped segment keeps mapping
    #    to the target beyond the knot (flat [0.25, 0.5] + sloped point 0.75
    #    -> interval [0.25, 0.75]);
    #  - anything else survives as a point solution.
    keptPoints: list[tuple[float, bool, str, int | None]] = []
    sortedPoints: list[tuple[float, bool, str, int | None]] = sorted(
        rawPoints, key=lambda p: p[0]
    )
    ptRecord: tuple[float, bool, str, int | None]
    for ptRecord in sortedPoints:
        x, atBoundary, expl, pointSegIdx = ptRecord
        matched = False
        for iv in normIntervals:
            ivLo, ivHi = iv[0], iv[1]
            if x < ivLo - eps or x > ivHi + eps:
                continue
            if not atBoundary and x > ivHi:
                iv[1] = x
                iv[2] = f"{iv[2]}; also {expl}"
            elif not atBoundary and x < ivLo:
                iv[0] = x
                iv[2] = f"{iv[2]}; also {expl}"
            # else: boundary knot already covered, or interior point inside
            # the flat segment -> redundant, drop.
            matched = True
            break
        if not matched:
            keptPoints.append((x, atBoundary, expl, pointSegIdx))

    solutions: list[ReverseSolution] = [
        ReverseSolution(
            kind="point",
            value=x,
            explanation=expl,
            segmentIndex=segIdx,
        )
        for x, _atBoundary, expl, segIdx in keptPoints
    ]
    solutions += [
        ReverseSolution(
            kind="interval",
            intervalStart=ivLo,
            intervalEnd=ivHi,
            explanation=expl,
            segmentIndex=segIdx,
        )
        for ivLo, ivHi, expl, segIdx in normIntervals
    ]
    solutions.sort(
        key=lambda s: (
            s.intervalStart if s.isInterval else s.value,
            s.intervalEnd if s.isInterval else s.value,
        )
    )

    reason = ""
    reachable = bool(solutions)
    if not reachable:
        # With clip=False the slope-1 extrapolation tails cover every target
        # outside the key domain, so an unreachable target can only mean the
        # request was clipped to the key domain.  At least two mapping keys
        # exist at this point (empty/single-key mappings returned earlier),
        # hence the output range is always defined.
        assert reachableRange is not None
        rLo, rHi = reachableRange
        reason = (
            f"target {target:g} is not reached by any input in the mapping "
            f"domain [{xMin:g}, {xMax:g}]; the map's output range over that "
            f"domain is [{rLo:g}, {rHi:g}]. Pass clip=False to also invert "
            f"the slope-1 extrapolation outside the mapping keys."
        )

    return ReverseMapResult(
        target=target,
        solutions=solutions,
        reachable=reachable,
        reason=reason,
        reachableRange=reachableRange,
        domain=(xMin, xMax),
        clip=clip,
    )


def main(args=None):
    """Normalize locations on a given designspace"""
    from fontTools import configLogger
    import argparse

    parser = argparse.ArgumentParser(
        "fonttools varLib.models",
        description=main.__doc__,
    )
    parser.add_argument(
        "--loglevel",
        metavar="LEVEL",
        default="INFO",
        help="Logging level (defaults to INFO)",
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-d", "--designspace", metavar="DESIGNSPACE", type=str)
    group.add_argument(
        "-l",
        "--locations",
        metavar="LOCATION",
        nargs="+",
        help="Master locations as comma-separate coordinates. One must be all zeros.",
    )

    args = parser.parse_args(args)

    configLogger(level=args.loglevel)
    from pprint import pprint

    if args.designspace:
        from fontTools.designspaceLib import DesignSpaceDocument

        doc = DesignSpaceDocument()
        doc.read(args.designspace)
        locs = [s.location for s in doc.sources]
        print("Original locations:")
        pprint(locs)
        doc.normalize()
        print("Normalized locations:")
        locs = [s.location for s in doc.sources]
        pprint(locs)
    else:
        axes = [chr(c) for c in range(ord("A"), ord("Z") + 1)]
        locs = [
            dict(zip(axes, (float(v) for v in s.split(",")))) for s in args.locations
        ]

    model = VariationModel(locs)
    print("Sorted locations:")
    pprint(model.locations)
    print("Supports:")
    pprint(model.supports)


if __name__ == "__main__":
    import doctest, sys

    if len(sys.argv) > 1:
        sys.exit(main())

    sys.exit(doctest.testmod().failed)
