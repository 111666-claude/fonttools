"""Tests for compiling and decompiling CFF2 Private DICT blend arguments,
especially when the blend operands have to be split into several blend
groups because they exceed the operand stack limit."""

import os
import sys
from io import BytesIO

import pytest

libdir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))),
    "Lib",
)
sys.path.insert(0, libdir)

from fontTools.cffLib import PrivateDict, maxStackLimit
from fontTools.misc.psCharStrings import (
    CFFDictReadError,
    cffDictOperandEncoding,
    encodeIntCFF,
)
from fontTools.misc.roundTools import otRound
from fontTools.ttLib import TTFont

blendOp = 23


class FakeVarStore(object):
    """Just enough VarStore for PrivateDict.getNumRegions()."""

    def __init__(self, numRegions):
        self.numRegions = numRegions

    def getNumRegions(self, vsIndex):
        return self.numRegions


def makePrivateDict(values=None, numRegions=0, key="BlueValues"):
    pd = PrivateDict()
    pd.vstore = FakeVarStore(numRegions)
    if values is not None:
        setattr(pd, key, values)
    return pd


def compilePrivate(pd):
    compiler = pd.getCompiler(None, None, isCFF2=True)
    return compiler.compile("test")


def roundTrip(values, numRegions, key="BlueValues"):
    pd = makePrivateDict(values, numRegions, key)
    data = compilePrivate(pd)
    pd2 = makePrivateDict(numRegions=numRegions, key=key)
    pd2.decompile(data)
    return data, getattr(pd2, key)


def parseDictOperands(data, numMasters):
    """Simulate the operand stack of a compiled Private DICT.

    Returns (max stack depth, number of blend operators).
    """
    stack = []
    maxDepth = 0
    numBlendOps = 0
    index = 0
    while index < len(data):
        b0 = data[index]
        index += 1
        if b0 == blendOp:
            numBlendOps += 1
            numBlends = stack.pop()
            del stack[-numBlends * numMasters :]
            stack.extend([0] * numBlends)
        elif b0 == 12:
            index += 1  # two-byte operator: consumes all operands
            stack.clear()
        elif b0 <= 21:
            stack.clear()  # operator: consumes all operands
        else:
            handler = cffDictOperandEncoding[b0]
            value, index = handler(None, b0, data, index)
            if value is not None:
                stack.append(value)
        maxDepth = max(maxDepth, len(stack))
    return maxDepth, numBlendOps


def blendValues(count, numMasters, start=-250, step=10):
    return [
        [start + i * step] + [((i + 1) * (m + 1)) % 7 - 3 for m in range(numMasters - 1)]
        for i in range(count)
    ]


@pytest.mark.parametrize("numRegions", [1, 2, 7])
def test_single_blend_group_round_trip(numRegions):
    numMasters = numRegions + 1
    values = blendValues(6, numMasters)
    data, result = roundTrip(values, numRegions)
    assert result == values
    maxDepth, numBlendOps = parseDictOperands(data, numMasters)
    assert numBlendOps == 1
    assert maxDepth <= maxStackLimit


@pytest.mark.parametrize("numRegions", [1, 2, 7])
def test_split_blend_groups_round_trip(numRegions):
    numMasters = numRegions + 1
    # (numBlends * numMasters) + 1 must exceed the stack limit so that the
    # operands are split into several blend groups.
    numBlends = maxStackLimit // numMasters + 13
    values = blendValues(numBlends, numMasters)
    data, result = roundTrip(values, numRegions)
    assert result == values
    maxDepth, numBlendOps = parseDictOperands(data, numMasters)
    assert numBlendOps > 1
    assert maxDepth <= maxStackLimit


@pytest.mark.parametrize("numRegions", [1, 2, 7])
def test_split_blend_groups_with_constants(numRegions):
    numMasters = numRegions + 1
    numBlends = maxStackLimit // numMasters + 5
    values = (
        [-300, -290]  # constant prefix
        + blendValues(numBlends, numMasters, start=-280)
        + [1000, 1010]  # constants in the middle
        + blendValues(20, numMasters, start=1020)
        + [5000]  # constant suffix
    )
    data, result = roundTrip(values, numRegions)
    assert result == values
    maxDepth, numBlendOps = parseDictOperands(data, numMasters)
    assert numBlendOps > 1
    assert maxDepth <= maxStackLimit


@pytest.mark.parametrize("numRegions", [1, 2])
def test_at_stack_limit_is_not_split(numRegions):
    numMasters = numRegions + 1
    # Exactly at the limit: (numBlends * numMasters) + 1 == maxStackLimit.
    numBlends = (maxStackLimit - 1) // numMasters
    values = blendValues(numBlends, numMasters)
    data, result = roundTrip(values, numRegions)
    assert result == values
    maxDepth, numBlendOps = parseDictOperands(data, numMasters)
    assert numBlendOps == 1
    assert maxDepth <= maxStackLimit
    # One more value forces a split.
    values = blendValues(numBlends + 1, numMasters)
    data, result = roundTrip(values, numRegions)
    assert result == values
    maxDepth, numBlendOps = parseDictOperands(data, numMasters)
    assert numBlendOps == 2
    assert maxDepth <= maxStackLimit


def test_constants_only_near_stack_limit():
    # A long run of constants followed by a blend group: the constants
    # occupy stack slots, so the blend group must be split earlier.
    numRegions = 1
    numMasters = 2
    numConstants = maxStackLimit - 30
    values = [i * 2 for i in range(numConstants)] + blendValues(25, numMasters, 2000)
    data, result = roundTrip(values, numRegions)
    assert result == values
    maxDepth, numBlendOps = parseDictOperands(data, numMasters)
    assert numBlendOps > 1
    assert maxDepth <= maxStackLimit


def test_unencodable_blend_raises():
    # A single blend value needs numMasters + 1 stack slots; if even that
    # does not fit, compilation must fail explicitly.
    pd = makePrivateDict(blendValues(3, 4), 3)
    compiler = pd.getCompiler(None, None, isCFF2=True)
    compiler.maxBlendStack = 4  # numMasters + 1 == 5 > 4
    with pytest.raises(ValueError, match="operand stack limit"):
        compiler.compile("test")


def test_unencodable_after_constants_raises():
    # Constants fill the stack so that no blend value fits anymore.
    pd = makePrivateDict([1, 2, 3] + blendValues(2, 2), 1)
    compiler = pd.getCompiler(None, None, isCFF2=True)
    compiler.maxBlendStack = 5  # 3 constants + 2 masters + 1 > 5
    with pytest.raises(ValueError, match="operand stack limit"):
        compiler.compile("test")


def test_zero_max_blend_stack_raises():
    # DictCompiler.maxBlendStack defaults to 0 (e.g. TopDictCompiler):
    # blend args used to be silently dropped, now this must fail.
    pd = makePrivateDict(blendValues(3, 2), 1)
    compiler = pd.getCompiler(None, None, isCFF2=True)
    compiler.maxBlendStack = 0
    with pytest.raises(ValueError, match="operand stack limit"):
        compiler.compile("test")


def test_mismatched_master_counts_raise():
    values = [[10, 1, 2], [20, 1, 2, 3]]
    pd = makePrivateDict(values, 2)
    with pytest.raises(ValueError, match="same number of masters"):
        compilePrivate(pd)


def test_malformed_blend_raises_on_decompile():
    # A blend op asking for more operands than are on the stack.
    pd = makePrivateDict(numRegions=2)
    data = encodeIntCFF(5) + encodeIntCFF(2) + bytes([blendOp, 6])
    with pytest.raises(CFFDictReadError):
        pd.decompile(data)


def test_non_split_blend_encoding_is_unchanged():
    # Pin the exact binary encoding of a single blend group: default values
    # delta-encoded, then the deltas row by row, numBlends, blend op.
    values = [[-12, 1, 2], [100, 3, 4]]
    pd = makePrivateDict(values, 2)
    data = compilePrivate(pd)
    expected = (
        encodeIntCFF(-12)  # first default value, relative to 0
        + encodeIntCFF(112)  # second default value, relative to the first
        + encodeIntCFF(1)
        + encodeIntCFF(2)
        + encodeIntCFF(3)
        + encodeIntCFF(4)
        + encodeIntCFF(2)  # numBlends
        + bytes([blendOp])
        + bytes([6])  # BlueValues operator
    )
    assert data == expected


def test_plain_cff_delta_encoding_is_unchanged():
    # Plain (non-variable) delta arrays must compile exactly as before.
    pd = makePrivateDict([-250, -240, 500, 600])
    data = compilePrivate(pd)
    expected = (
        encodeIntCFF(-250)
        + encodeIntCFF(10)
        + encodeIntCFF(740)
        + encodeIntCFF(100)
        + bytes([6])  # BlueValues operator
    )
    assert data == expected
    # ... and round-trip.
    pd2 = makePrivateDict()
    pd2.decompile(data)
    assert pd2.BlueValues == [-250, -240, 500, 600]


def test_mixed_delta_encoding():
    # Constants and blend groups share one continuous delta chain.
    values = [10, [20, 1, 2], [30, 3, 4], 100]
    pd = makePrivateDict(values, 2)
    data = compilePrivate(pd)
    expected = (
        encodeIntCFF(10)  # constant, relative to 0
        + encodeIntCFF(10)  # first blend default, relative to the constant
        + encodeIntCFF(10)  # second blend default, relative to the first
        + encodeIntCFF(1)
        + encodeIntCFF(2)
        + encodeIntCFF(3)
        + encodeIntCFF(4)
        + encodeIntCFF(2)  # numBlends
        + bytes([blendOp])
        + encodeIntCFF(70)  # trailing constant, relative to 30
        + bytes([6])  # BlueValues operator
    )
    assert data == expected
    pd2 = makePrivateDict(numRegions=2)
    pd2.decompile(data)
    assert pd2.BlueValues == values


def test_all_blend_fields_round_trip():
    for key in (
        "BlueValues",
        "OtherBlues",
        "FamilyBlues",
        "FamilyOtherBlues",
        "StemSnapH",
        "StemSnapV",
    ):
        values = blendValues(maxStackLimit // 3 + 7, 3)
        data, result = roundTrip(values, 2, key)
        assert result == values, key


def test_xml_round_trip_mixed_and_single_entry():
    from fontTools.cffLib import ArrayConverter
    from fontTools.misc.xmlWriter import XMLWriter
    from fontTools.misc.testTools import parseXML

    conv = ArrayConverter()

    def toXML(value):
        writer = XMLWriter(BytesIO())
        conv.xmlWrite(writer, "BlueValues", value)
        xml = writer.file.getvalue().decode("utf-8")
        return xml[xml.index("<BlueValues") :]

    def fromXML(xml, value):
        for element in parseXML(xml):
            name, attrs, content = element
            assert name == "BlueValues"
            return conv.xmlRead(name, attrs, content, None)

    # Mixed constants and blend lists.
    values = [10, [20, 1, 2], [30, 3, 4], 100]
    assert fromXML(toXML(values), values) == values
    # A single blend entry must stay a list of blend lists.
    values = [[46, -23, 17]]
    assert fromXML(toXML(values), values) == values
    # Plain arrays are written as a flat value attribute, as before.
    values = [-250, -240, 500]
    xml = toXML(values)
    assert 'value="-250 -240 500"' in xml
    assert fromXML(xml, values) == values


CFF2_VF_TTX = os.path.join(
    os.path.dirname(__file__),
    "..",
    "varLib",
    "instancer",
    "data",
    "CFF2Instancer-VF-1.ttx",
)


def importCFF2TestFont():
    font = TTFont(recalcBBoxes=False, recalcTimestamp=False)
    font.importXML(CFF2_VF_TTX)
    return font


def charStringPrograms(font):
    topDict = font["CFF2"].cff.topDictIndex[0]
    charStrings = topDict.CharStrings
    programs = {}
    for name in font.getGlyphOrder():
        charString = charStrings[name]
        charString.decompile()
        programs[name] = charString.program
    return programs


def drawGlyphs(font):
    from fontTools.pens.recordingPen import RecordingPen

    glyphSet = font.getGlyphSet()
    drawings = {}
    for name in font.getGlyphOrder():
        pen = RecordingPen()
        glyphSet[name].draw(pen)
        drawings[name] = pen.value
    return drawings


@pytest.mark.filterwarnings("ignore:.*instantiateVariableFont.*:UserWarning")
def test_full_font_split_blend_round_trip_and_instancing():
    from fontTools.varLib import mutator
    from fontTools.varLib.varStore import VarStoreInstancer

    numRegions = 1  # the CFF2 VarStore of this font has a single region.
    numMasters = numRegions + 1
    numBlends = maxStackLimit // numMasters + 11
    blueValues = blendValues(numBlends, numMasters)
    location = {"wght": 500}

    font = importCFF2TestFont()
    topDict = font["CFF2"].cff.topDictIndex[0]
    private = topDict.FDArray[0].Private
    private.BlueValues = blueValues
    programsBefore = charStringPrograms(font)

    # Expected values at the target axis position, computed from the
    # original blend lists. The location must go through the same
    # normalization, avar mapping and F2Dot14 quantization that
    # instantiateVariableFont applies.
    from fontTools.misc.fixedTools import floatToFixedToFloat
    from fontTools.varLib.models import normalizeLocation, piecewiseLinearMap

    axes = {a.axisTag: (a.minValue, a.defaultValue, a.maxValue) for a in font["fvar"].axes}
    normalizedLocation = normalizeLocation(location, axes)
    if "avar" in font:
        maps = font["avar"].segments
        normalizedLocation = {
            k: piecewiseLinearMap(v, maps[k]) for k, v in normalizedLocation.items()
        }
    normalizedLocation = {
        k: floatToFixedToFloat(v, 14) for k, v in normalizedLocation.items()
    }
    vsInstancer = VarStoreInstancer(
        topDict.VarStore.otVarStore, font["fvar"].axes, normalizedLocation
    )
    expectedAtLocation = []
    delta = 0
    for valList in blueValues:
        delta += otRound(vsInstancer.interpolateFromDeltas(0, valList[1:]))
        expectedAtLocation.append(valList[0] + delta)

    # Compile to binary and re-open: the Private DICT values must survive
    # the split into multiple blend groups unchanged.
    buf = BytesIO()
    font.save(buf)
    buf.seek(0)
    font2 = TTFont(buf, recalcBBoxes=False, recalcTimestamp=False)
    topDict2 = font2["CFF2"].cff.topDictIndex[0]
    private2 = topDict2.FDArray[0].Private
    assert private2.BlueValues == blueValues

    # The CharStrings must be untouched by the Private DICT recompilation.
    assert charStringPrograms(font2) == programsBefore

    # The values at the target axis position must match the interpolation
    # of the original blend lists, both for the in-memory font and for the
    # re-opened one.
    static1 = mutator.instantiateVariableFont(font, location)
    staticPrivate1 = static1["CFF2"].cff.topDictIndex[0].FDArray[0].Private
    assert staticPrivate1.BlueValues == expectedAtLocation

    static2 = mutator.instantiateVariableFont(font2, location)
    staticPrivate2 = static2["CFF2"].cff.topDictIndex[0].FDArray[0].Private
    assert staticPrivate2.BlueValues == expectedAtLocation

    # Drawing regression: glyphs drawn from the instantiated re-opened font
    # must be identical to those drawn from the instantiated original.
    assert drawGlyphs(static1) == drawGlyphs(static2)


if __name__ == "__main__":
    sys.exit(pytest.main(sys.argv))
