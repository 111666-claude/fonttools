from fontTools.varLib.models import (
    normalizeLocation,
    supportScalar,
    piecewiseLinearMap,
    reversePiecewiseLinearMap,
    ReverseSolution,
    VariationModel,
    VariationModelError,
)
import pytest


def test_normalizeLocation():
    axes = {"wght": (100, 400, 900)}
    assert normalizeLocation({"wght": 400}, axes) == {"wght": 0.0}
    assert normalizeLocation({"wght": 100}, axes) == {"wght": -1.0}
    assert normalizeLocation({"wght": 900}, axes) == {"wght": 1.0}
    assert normalizeLocation({"wght": 650}, axes) == {"wght": 0.5}
    assert normalizeLocation({"wght": 1000}, axes) == {"wght": 1.0}
    assert normalizeLocation({"wght": 0}, axes) == {"wght": -1.0}

    axes = {"wght": (0, 0, 1000)}
    assert normalizeLocation({"wght": 0}, axes) == {"wght": 0.0}
    assert normalizeLocation({"wght": -1}, axes) == {"wght": 0.0}
    assert normalizeLocation({"wght": 1000}, axes) == {"wght": 1.0}
    assert normalizeLocation({"wght": 500}, axes) == {"wght": 0.5}
    assert normalizeLocation({"wght": 1001}, axes) == {"wght": 1.0}

    axes = {"wght": (0, 1000, 1000)}
    assert normalizeLocation({"wght": 0}, axes) == {"wght": -1.0}
    assert normalizeLocation({"wght": -1}, axes) == {"wght": -1.0}
    assert normalizeLocation({"wght": 500}, axes) == {"wght": -0.5}
    assert normalizeLocation({"wght": 1000}, axes) == {"wght": 0.0}
    assert normalizeLocation({"wght": 1001}, axes) == {"wght": 0.0}


@pytest.mark.parametrize(
    "axes, location, expected",
    [
        # lower != default != upper
        ({"wght": (100, 400, 900)}, {"wght": 1000}, {"wght": 1.2}),
        ({"wght": (100, 400, 900)}, {"wght": 900}, {"wght": 1.0}),
        ({"wght": (100, 400, 900)}, {"wght": 650}, {"wght": 0.5}),
        ({"wght": (100, 400, 900)}, {"wght": 400}, {"wght": 0.0}),
        ({"wght": (100, 400, 900)}, {"wght": 250}, {"wght": -0.5}),
        ({"wght": (100, 400, 900)}, {"wght": 100}, {"wght": -1.0}),
        ({"wght": (100, 400, 900)}, {"wght": 25}, {"wght": -1.25}),
        # lower == default != upper
        (
            {"wght": (400, 400, 900), "wdth": (100, 100, 150)},
            {"wght": 1000, "wdth": 200},
            {"wght": 1.2, "wdth": 2.0},
        ),
        (
            {"wght": (400, 400, 900), "wdth": (100, 100, 150)},
            {"wght": 25, "wdth": 25},
            {"wght": -0.75, "wdth": -1.5},
        ),
        # lower != default == upper
        (
            {"wght": (100, 400, 400), "wdth": (50, 100, 100)},
            {"wght": 700, "wdth": 150},
            {"wght": 1.0, "wdth": 1.0},
        ),
        (
            {"wght": (100, 400, 400), "wdth": (50, 100, 100)},
            {"wght": -50, "wdth": 25},
            {"wght": -1.5, "wdth": -1.5},
        ),
        # degenerate case with lower == default == upper, normalized location always 0
        ({"wght": (400, 400, 400)}, {"wght": 100}, {"wght": 0.0}),
        ({"wght": (400, 400, 400)}, {"wght": 400}, {"wght": 0.0}),
        ({"wght": (400, 400, 400)}, {"wght": 700}, {"wght": 0.0}),
    ],
)
def test_normalizeLocation_extrapolate(axes, location, expected):
    assert normalizeLocation(location, axes, extrapolate=True) == expected


def test_supportScalar():
    assert supportScalar({}, {}) == 1.0
    assert supportScalar({"wght": 0.2}, {}) == 1.0
    assert supportScalar({"wght": 0.2}, {"wght": (0, 2, 3)}) == 0.1
    assert supportScalar({"wght": 2.5}, {"wght": (0, 2, 4)}) == 0.75
    assert supportScalar({"wght": 3}, {"wght": (0, 2, 2)}) == 0.0
    assert (
        supportScalar(
            {"wght": 3},
            {"wght": (0, 2, 2)},
            extrapolate=True,
            axisRanges={"wght": (0, 2)},
        )
        == 1.5
    )
    assert (
        supportScalar(
            {"wght": -1},
            {"wght": (0, 2, 2)},
            extrapolate=True,
            axisRanges={"wght": (0, 2)},
        )
        == -0.5
    )
    assert (
        supportScalar(
            {"wght": 3},
            {"wght": (0, 1, 2)},
            extrapolate=True,
            axisRanges={"wght": (0, 2)},
        )
        == -1.0
    )
    assert (
        supportScalar(
            {"wght": -1},
            {"wght": (0, 1, 2)},
            extrapolate=True,
            axisRanges={"wght": (0, 2)},
        )
        == -1.0
    )
    assert (
        supportScalar(
            {"wght": 2},
            {"wght": (0, 0.75, 1)},
            extrapolate=True,
            axisRanges={"wght": (0, 1)},
        )
        == -4.0
    )
    with pytest.raises(TypeError):
        supportScalar(
            {"wght": 2}, {"wght": (0, 0.75, 1)}, extrapolate=True, axisRanges=None
        )


def test_model_extrapolate():
    locations = [{}, {"a": 1}, {"b": 1}, {"a": 1, "b": 1}]
    model = VariationModel(locations, extrapolate=True)
    masterValues = [100, 200, 300, 400]
    testLocsAndValues = [
        ({"a": -1, "b": -1}, -200),
        ({"a": -1, "b": 0}, 0),
        ({"a": -1, "b": 1}, 200),
        ({"a": -1, "b": 2}, 400),
        ({"a": 0, "b": -1}, -100),
        ({"a": 0, "b": 0}, 100),
        ({"a": 0, "b": 1}, 300),
        ({"a": 0, "b": 2}, 500),
        ({"a": 1, "b": -1}, 0),
        ({"a": 1, "b": 0}, 200),
        ({"a": 1, "b": 1}, 400),
        ({"a": 1, "b": 2}, 600),
        ({"a": 2, "b": -1}, 100),
        ({"a": 2, "b": 0}, 300),
        ({"a": 2, "b": 1}, 500),
        ({"a": 2, "b": 2}, 700),
    ]
    for loc, expectedValue in testLocsAndValues:
        assert expectedValue == model.interpolateFromMasters(loc, masterValues)


@pytest.mark.parametrize(
    "numLocations, numSamples",
    [
        pytest.param(127, 509, marks=pytest.mark.slow),
        (31, 251),
    ],
)
def test_modeling_error(numLocations, numSamples):
    # https://github.com/fonttools/fonttools/issues/2213
    locations = [{"axis": float(i) / numLocations} for i in range(numLocations)]
    masterValues = [100.0 if i else 0.0 for i in range(numLocations)]

    model = VariationModel(locations)

    for i in range(numSamples):
        loc = {"axis": float(i) / numSamples}
        scalars = model.getScalars(loc)

        deltas_float = model.getDeltas(masterValues)
        deltas_round = model.getDeltas(masterValues, round=round)

        expected = model.interpolateFromDeltasAndScalars(deltas_float, scalars)
        actual = model.interpolateFromDeltasAndScalars(deltas_round, scalars)

        err = abs(actual - expected)
        assert err <= 0.5, (i, err)

        # This is how NOT to round deltas.
        # deltas_late_round = [round(d) for d in deltas_float]
        # bad = model.interpolateFromDeltasAndScalars(deltas_late_round, scalars)
        # err_bad = abs(bad - expected)
        # if err != err_bad:
        #    print("{:d}	{:.2}	{:.2}".format(i, err, err_bad))


locationsA = [{}, {"wght": 1}, {"wdth": 1}]
locationsB = [{}, {"wght": 1}, {"wdth": 1}, {"wght": 1, "wdth": 1}]
locationsC = [
    {},
    {"wght": 0.5},
    {"wght": 1},
    {"wdth": 1},
    {"wght": 1, "wdth": 1},
]


class VariationModelTest(object):
    @pytest.mark.parametrize(
        "locations, axisOrder, sortedLocs, supports, deltaWeights",
        [
            (
                [
                    {"wght": 0.55, "wdth": 0.0},
                    {"wght": -0.55, "wdth": 0.0},
                    {"wght": -1.0, "wdth": 0.0},
                    {"wght": 0.0, "wdth": 1.0},
                    {"wght": 0.66, "wdth": 1.0},
                    {"wght": 0.66, "wdth": 0.66},
                    {"wght": 0.0, "wdth": 0.0},
                    {"wght": 1.0, "wdth": 1.0},
                    {"wght": 1.0, "wdth": 0.0},
                ],
                ["wght"],
                [
                    {},
                    {"wght": -0.55},
                    {"wght": -1.0},
                    {"wght": 0.55},
                    {"wght": 1.0},
                    {"wdth": 1.0},
                    {"wdth": 1.0, "wght": 1.0},
                    {"wdth": 1.0, "wght": 0.66},
                    {"wdth": 0.66, "wght": 0.66},
                ],
                [
                    {},
                    {"wght": (-1.0, -0.55, 0)},
                    {"wght": (-1.0, -1.0, -0.55)},
                    {"wght": (0, 0.55, 1.0)},
                    {"wght": (0.55, 1.0, 1.0)},
                    {"wdth": (0, 1.0, 1.0)},
                    {"wdth": (0, 1.0, 1.0), "wght": (0, 1.0, 1.0)},
                    {"wdth": (0, 1.0, 1.0), "wght": (0, 0.66, 1.0)},
                    {"wdth": (0, 0.66, 1.0), "wght": (0, 0.66, 1.0)},
                ],
                [
                    {},
                    {0: 1.0},
                    {0: 1.0},
                    {0: 1.0},
                    {0: 1.0},
                    {0: 1.0},
                    {0: 1.0, 4: 1.0, 5: 1.0},
                    {
                        0: 1.0,
                        3: 0.7555555555555555,
                        4: 0.24444444444444444,
                        5: 1.0,
                        6: 0.66,
                    },
                    {
                        0: 1.0,
                        3: 0.7555555555555555,
                        4: 0.24444444444444444,
                        5: 0.66,
                        6: 0.43560000000000004,
                        7: 0.66,
                    },
                ],
            ),
            (
                [
                    {},
                    {"bar": 0.5},
                    {"bar": 1.0},
                    {"foo": 1.0},
                    {"bar": 0.5, "foo": 1.0},
                    {"bar": 1.0, "foo": 1.0},
                ],
                None,
                [
                    {},
                    {"bar": 0.5},
                    {"bar": 1.0},
                    {"foo": 1.0},
                    {"bar": 0.5, "foo": 1.0},
                    {"bar": 1.0, "foo": 1.0},
                ],
                [
                    {},
                    {"bar": (0, 0.5, 1.0)},
                    {"bar": (0.5, 1.0, 1.0)},
                    {"foo": (0, 1.0, 1.0)},
                    {"bar": (0, 0.5, 1.0), "foo": (0, 1.0, 1.0)},
                    {"bar": (0.5, 1.0, 1.0), "foo": (0, 1.0, 1.0)},
                ],
                [
                    {},
                    {0: 1.0},
                    {0: 1.0},
                    {0: 1.0},
                    {0: 1.0, 1: 1.0, 3: 1.0},
                    {0: 1.0, 2: 1.0, 3: 1.0},
                ],
            ),
            (
                [
                    {},
                    {"foo": 0.25},
                    {"foo": 0.5},
                    {"foo": 0.75},
                    {"foo": 1.0},
                    {"bar": 0.25},
                    {"bar": 0.75},
                    {"bar": 1.0},
                ],
                None,
                [
                    {},
                    {"bar": 0.25},
                    {"bar": 0.75},
                    {"bar": 1.0},
                    {"foo": 0.25},
                    {"foo": 0.5},
                    {"foo": 0.75},
                    {"foo": 1.0},
                ],
                [
                    {},
                    {"bar": (0.0, 0.25, 1.0)},
                    {"bar": (0.25, 0.75, 1.0)},
                    {"bar": (0.75, 1.0, 1.0)},
                    {"foo": (0.0, 0.25, 1.0)},
                    {"foo": (0.25, 0.5, 1.0)},
                    {"foo": (0.5, 0.75, 1.0)},
                    {"foo": (0.75, 1.0, 1.0)},
                ],
                [
                    {},
                    {0: 1.0},
                    {0: 1.0, 1: 0.3333333333333333},
                    {0: 1.0},
                    {0: 1.0},
                    {0: 1.0, 4: 0.6666666666666666},
                    {0: 1.0, 4: 0.3333333333333333, 5: 0.5},
                    {0: 1.0},
                ],
            ),
            (
                [
                    {},
                    {"foo": 0.25},
                    {"foo": 0.5},
                    {"foo": 0.75},
                    {"foo": 1.0},
                    {"bar": 0.25},
                    {"bar": 0.75},
                    {"bar": 1.0},
                ],
                None,
                [
                    {},
                    {"bar": 0.25},
                    {"bar": 0.75},
                    {"bar": 1.0},
                    {"foo": 0.25},
                    {"foo": 0.5},
                    {"foo": 0.75},
                    {"foo": 1.0},
                ],
                [
                    {},
                    {"bar": (0, 0.25, 1.0)},
                    {"bar": (0.25, 0.75, 1.0)},
                    {"bar": (0.75, 1.0, 1.0)},
                    {"foo": (0, 0.25, 1.0)},
                    {"foo": (0.25, 0.5, 1.0)},
                    {"foo": (0.5, 0.75, 1.0)},
                    {"foo": (0.75, 1.0, 1.0)},
                ],
                [
                    {},
                    {0: 1.0},
                    {0: 1.0, 1: 0.3333333333333333},
                    {0: 1.0},
                    {0: 1.0},
                    {0: 1.0, 4: 0.6666666666666666},
                    {0: 1.0, 4: 0.3333333333333333, 5: 0.5},
                    {0: 1.0},
                ],
            ),
        ],
    )
    def test_init(self, locations, axisOrder, sortedLocs, supports, deltaWeights):
        model = VariationModel(locations, axisOrder=axisOrder)

        assert model.locations == sortedLocs
        assert model.supports == supports
        assert model.deltaWeights == deltaWeights

    def test_init_duplicate_locations(self):
        with pytest.raises(VariationModelError, match="Locations must be unique."):
            VariationModel(
                [
                    {"foo": 0.0, "bar": 0.0},
                    {"foo": 1.0, "bar": 1.0},
                    {"bar": 1.0, "foo": 1.0},
                ]
            )

    def test_init_duplicate_locations_after_stripping_zero_axes(self):
        with pytest.raises(VariationModelError, match="Locations must be unique."):
            VariationModel([{}, {"foo": 0.0}])

    def test_getSubModel_preserves_extrapolate_and_axisRanges(self):
        axisRanges = {"foo": (-2.0, 2.0)}
        model = VariationModel(
            [{}, {"foo": 1.0}, {"foo": 2.0}],
            extrapolate=True,
            axisRanges=axisRanges,
        )

        subModel, items = model.getSubModel([1, None, 3])

        assert items == [1, 3]
        assert subModel.extrapolate is True
        assert subModel.axisRanges == axisRanges
        assert subModel.interpolateFromMasters({"foo": 3.0}, [100, 200]) == 250

    @pytest.mark.parametrize(
        "locations, axisOrder, masterValues, instanceLocation, expectedValue, masterScalars",
        [
            (
                [
                    {},
                    {"axis_A": 1.0},
                    {"axis_B": 1.0},
                    {"axis_A": 1.0, "axis_B": 1.0},
                    {"axis_A": 0.5, "axis_B": 1.0},
                    {"axis_A": 1.0, "axis_B": 0.5},
                ],
                ["axis_A", "axis_B"],
                [
                    0,
                    10,
                    20,
                    70,
                    50,
                    60,
                ],
                {
                    "axis_A": 0.5,
                    "axis_B": 0.5,
                },
                37.5,
                [0.25, 0.0, 0.0, -0.25, 0.5, 0.5],
            ),
        ],
    )
    def test_interpolation(
        self,
        locations,
        axisOrder,
        masterValues,
        instanceLocation,
        expectedValue,
        masterScalars,
    ):
        model = VariationModel(locations, axisOrder=axisOrder)

        interpolatedValue = model.interpolateFromMasters(instanceLocation, masterValues)
        assert interpolatedValue == expectedValue

        assert masterScalars == model.getMasterScalars(instanceLocation)

        assert model.interpolateFromValuesAndScalars(
            masterValues, masterScalars
        ) == pytest.approx(interpolatedValue)

    @pytest.mark.parametrize(
        "masterLocations, location, expected",
        [
            (locationsA, {"wght": 0, "wdth": 0}, [1, 0, 0]),
            (
                locationsA,
                {"wght": 0.5, "wdth": 0},
                [0.5, 0.5, 0],
            ),
            (locationsA, {"wght": 1, "wdth": 0}, [0, 1, 0]),
            (
                locationsA,
                {"wght": 0, "wdth": 0.5},
                [0.5, 0, 0.5],
            ),
            (locationsA, {"wght": 0, "wdth": 1}, [0, 0, 1]),
            (locationsA, {"wght": 1, "wdth": 1}, [-1, 1, 1]),
            (
                locationsA,
                {"wght": 0.5, "wdth": 0.5},
                [0, 0.5, 0.5],
            ),
            (
                locationsA,
                {"wght": 0.75, "wdth": 0.75},
                [-0.5, 0.75, 0.75],
            ),
            (
                locationsB,
                {"wght": 1, "wdth": 1},
                [0, 0, 0, 1],
            ),
            (
                locationsB,
                {"wght": 0.5, "wdth": 0},
                [0.5, 0.5, 0, 0],
            ),
            (
                locationsB,
                {"wght": 1, "wdth": 0.5},
                [0, 0.5, 0, 0.5],
            ),
            (
                locationsB,
                {"wght": 0.5, "wdth": 0.5},
                [0.25, 0.25, 0.25, 0.25],
            ),
            (
                locationsC,
                {"wght": 0.5, "wdth": 0},
                [0, 1, 0, 0, 0],
            ),
            (
                locationsC,
                {"wght": 0.25, "wdth": 0},
                [0.5, 0.5, 0, 0, 0],
            ),
            (
                locationsC,
                {"wght": 0.75, "wdth": 0},
                [0, 0.5, 0.5, 0, 0],
            ),
            (
                locationsC,
                {"wght": 0.5, "wdth": 1},
                [-0.5, 1, -0.5, 0.5, 0.5],
            ),
            (
                locationsC,
                {"wght": 0.75, "wdth": 1},
                [-0.25, 0.5, -0.25, 0.25, 0.75],
            ),
        ],
    )
    def test_getMasterScalars(self, masterLocations, location, expected):
        model = VariationModel(masterLocations)
        assert model.getMasterScalars(location) == expected


# ---------------------------------------------------------------------------
# reversePiecewiseLinearMap
# ---------------------------------------------------------------------------

# Fixed acceptance mapping: contains a plateau ([0.25, 0.5] -> 0.5), a
# non-monotone hump later on, and the standard -1/0/1 endpoints.
FIXED_MAPPING = {
    -1.0: -1.0,
    0.0: 0.0,
    0.25: 0.5,
    0.5: 0.5,
    0.75: 0.25,
    1.0: 1.0,
}


def _forwardCheck(result, mapping, tolerance=1e-10):
    """Feed every returned solution back through the forward map."""
    assert result.reachable
    for solution in result.solutions:
        if solution.isInterval:
            probes = (
                solution.intervalStart,
                (solution.intervalStart + solution.intervalEnd) / 2,
                solution.intervalEnd,
            )
        else:
            probes = (solution.value,)
        for x in probes:
            assert abs(piecewiseLinearMap(x, mapping) - result.target) <= tolerance


def test_reverse_empty_mapping_is_identity():
    result = reversePiecewiseLinearMap(0.3, {})
    assert result.reachable
    assert len(result.solutions) == 1
    assert result.solutions[0].kind == "point"
    assert result.solutions[0].value == 0.3
    assert result.domain is None
    assert result.reachableRange is None


def test_reverse_single_key_mapping():
    mapping = {0.0: 0.0}

    hit = reversePiecewiseLinearMap(0.0, mapping)
    assert [(s.kind, s.value) for s in hit.solutions] == [("point", 0.0)]

    missed = reversePiecewiseLinearMap(0.5, mapping)
    assert not missed.reachable
    assert missed.reachableRange == (0.0, 0.0)

    # Slope-1 extrapolation on both sides of the lone key.
    assert reversePiecewiseLinearMap(0.5, mapping, clip=False).points[0].value == 0.5
    assert reversePiecewiseLinearMap(-0.5, mapping, clip=False).points[0].value == -0.5


def test_reverse_monotone_interior_target():
    mapping = {-1.0: -1.0, 0.0: 0.0, 0.5: 0.25, 1.0: 1.0}
    result = reversePiecewiseLinearMap(0.25, mapping)
    assert len(result.solutions) == 1
    assert result.solutions[0].kind == "point"
    assert result.solutions[0].value == 0.5
    _forwardCheck(result, mapping)


def test_reverse_plateau_returns_interval():
    # Use a mapping whose plateau is the only preimage of 0.5.
    mapping = {-1.0: -1.0, 0.0: 0.0, 0.25: 0.5, 0.5: 0.5, 1.0: 1.0}
    result = reversePiecewiseLinearMap(0.5, mapping)
    assert len(result.solutions) == 1
    solution = result.solutions[0]
    assert solution.kind == "interval"
    assert (solution.intervalStart, solution.intervalEnd) == (0.25, 0.5)
    assert solution.explanation  # human-readable, non-empty
    _forwardCheck(result, mapping)


def test_reverse_endpoint_coincidence_deduplicates_to_single_point():
    # Target 0.0 is reached at the shared knot of two sloped segments;
    # it must come back as one point, not two near-equal floats.
    result = reversePiecewiseLinearMap(0.0, FIXED_MAPPING)
    points = result.points
    assert len(points) == 1
    assert points[0].value == 0.0
    _forwardCheck(result, FIXED_MAPPING)


def test_reverse_non_monotone_returns_all_hits_sorted():
    # The hump [0.5 -> 0.5, 0.75 -> 0.25, 1.0 -> 1.0] crosses 0.5 again
    # on its way back up, so after the plateau there is one more point
    # preimage in addition to the plateau interval.
    result = reversePiecewiseLinearMap(0.5, FIXED_MAPPING)
    assert len(result.intervals) == 1
    assert (result.intervals[0].intervalStart, result.intervals[0].intervalEnd) == (
        0.25,
        0.5,
    )
    pointValues = [p.value for p in result.points]
    assert pointValues == sorted(pointValues)
    # segment [0.75, 1.0] -> [0.25, 1.0]: x = 0.75 + (0.5-0.25)/0.75 * 0.25
    expected = 0.75 + 0.25 * (0.25 / 0.75)
    assert pointValues == [pytest.approx(expected, abs=1e-12)]
    _forwardCheck(result, FIXED_MAPPING)


def test_reverse_unreachable_target_is_clipped():
    # FIXED_MAPPING's output range over [-1, 1] is [-1, 1], so 1.5 is
    # unreachable while clipping is enabled.
    result = reversePiecewiseLinearMap(1.5, FIXED_MAPPING)
    assert not result.reachable
    assert result.solutions == []
    assert "1.5" in result.reason
    assert result.reachableRange == (-1.0, 1.0)
    assert result.domain == (-1.0, 1.0)


def test_reverse_extrapolation_tails():
    result = reversePiecewiseLinearMap(1.5, FIXED_MAPPING, clip=False)
    assert result.reachable
    # Right tail: f(x) = x + 1 - 1 = x above x=1, so preimage is 1.5.
    assert result.points[-1].value == 1.5
    _forwardCheck(result, FIXED_MAPPING)

    left = reversePiecewiseLinearMap(-1.25, FIXED_MAPPING, clip=False)
    assert left.points[0].value == -1.25
    _forwardCheck(left, FIXED_MAPPING)


def test_reverse_flat_mapping_whole_domain():
    mapping = {-1.0: 0.3, 0.0: 0.3, 1.0: 0.3}
    hit = reversePiecewiseLinearMap(0.3, mapping)
    assert len(hit.solutions) == 1
    assert hit.solutions[0].kind == "interval"
    assert (hit.solutions[0].intervalStart, hit.solutions[0].intervalEnd) == (-1.0, 1.0)

    miss = reversePiecewiseLinearMap(0.9, mapping)
    assert not miss.reachable


def test_reverse_adjacent_flat_segments_merge_into_one_interval():
    mapping = {
        0.0: 0.0,
        0.2: 0.5,
        0.4: 0.5,
        0.6: 0.5,
        0.8: 0.8,
        1.0: 1.0,
    }
    result = reversePiecewiseLinearMap(0.5, mapping)
    assert len(result.intervals) == 1
    assert (result.intervals[0].intervalStart, result.intervals[0].intervalEnd) == (
        0.2,
        0.6,
    )
    _forwardCheck(result, mapping)


def test_reverse_solutions_sorted_and_deduplicated():
    mapping = {0.0: 0.0, 0.25: 0.8, 0.5: 0.2, 0.75: 0.9, 1.0: 0.1}
    result = reversePiecewiseLinearMap(0.5, mapping)
    values = [p.value for p in result.points]
    assert values == sorted(values)
    assert len(values) == len({round(v, 12) for v in values})
    _forwardCheck(result, mapping)


@pytest.mark.parametrize(
    "mapping,lo,hi",
    [
        (FIXED_MAPPING, -1.0, 1.0),
        ({-1.0: -1.0, 0.0: 0.0, 0.5: 0.25, 1.0: 1.0}, -1.0, 1.0),
        ({0.0: 0.0, 0.5: 1.0, 1.0: 0.0}, 0.0, 1.0),
        ({0.0: 1.0, 1.0: 0.0}, 0.0, 1.0),
        ({-1.0: 0.3, 0.0: 0.3, 1.0: 0.3}, -1.0, 1.0),
        (
            {0.0: 0.0, 0.25: 0.8, 0.5: 0.2, 0.75: 0.9, 1.0: 0.1},
            0.0,
            1.0,
        ),
        (
            {0.0: 0.0, 0.2: 0.5, 0.4: 0.5, 0.6: 0.8, 0.8: 0.8, 1.0: 1.0},
            0.0,
            1.0,
        ),
        ({-1.0: -1.0, -0.5: -1.0, 0.0: 0.0, 1.0: 1.0}, -1.0, 1.0),
    ],
)
def test_reverse_dense_forward_verification(mapping, lo, hi):
    """Every dense-grid input whose forward image rounds to a target must
    be covered by a returned solution, and every returned solution must
    forward-map back to the target."""
    n = 1000
    grid = [lo + (hi - lo) * k / n for k in range(n + 1)]
    byTarget = {}
    for x in grid:
        byTarget.setdefault(round(piecewiseLinearMap(x, mapping), 10), []).append(x)

    for target, xsForTarget in byTarget.items():
        result = reversePiecewiseLinearMap(target, mapping)
        assert result.reachable, (target, result.reason)
        for x in xsForTarget:
            assert any(
                (solution.kind == "point" and abs(solution.value - x) <= 1e-8)
                or (
                    solution.kind == "interval"
                    and solution.intervalStart - 1e-8
                    <= x
                    <= solution.intervalEnd + 1e-8
                )
                for solution in result.solutions
            ), (target, x, result.solutions)
        _forwardCheck(result, mapping)


def test_reverse_solution_is_frozen_dataclass():
    from dataclasses import FrozenInstanceError

    result = reversePiecewiseLinearMap(0.5, FIXED_MAPPING)
    with pytest.raises(FrozenInstanceError):
        result.solutions[0].kind = "point"
    assert isinstance(result.solutions[0], ReverseSolution)
