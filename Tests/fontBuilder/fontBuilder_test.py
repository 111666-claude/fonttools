import os
import pytest
from fontTools.designspaceLib import AxisDescriptor, AxisMappingDescriptor
from fontTools.ttLib import TTFont, newTable
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.fontBuilder import FontBuilder
from fontTools.ttLib.tables.TupleVariation import TupleVariation
from fontTools.misc.psCharStrings import T2CharString
from fontTools.misc.testTools import stripVariableItemsFromTTX


def getTestData(fileName, mode="r"):
    path = os.path.join(os.path.dirname(__file__), "data", fileName)
    with open(path, mode) as f:
        return f.read()


def drawTestGlyph(pen):
    pen.moveTo((100, 100))
    pen.lineTo((100, 1000))
    pen.qCurveTo((200, 900), (400, 900), (500, 1000))
    pen.lineTo((500, 100))
    pen.closePath()


def _setupFontBuilder(isTTF, unitsPerEm=1024):
    fb = FontBuilder(unitsPerEm, isTTF=isTTF)
    fb.setupGlyphOrder([".notdef", ".null", "A", "a"])
    fb.setupCharacterMap({65: "A", 97: "a"})

    advanceWidths = {".notdef": 600, "A": 600, "a": 600, ".null": 600}

    familyName = "HelloTestFont"
    styleName = "TotallyNormal"
    nameStrings = dict(
        familyName=dict(en="HelloTestFont", nl="HalloTestFont"),
        styleName=dict(en="TotallyNormal", nl="TotaalNormaal"),
    )
    nameStrings["psName"] = familyName + "-" + styleName

    return fb, advanceWidths, nameStrings


def _setupFontBuilderFvar(fb):
    assert "name" in fb.font, "Must run setupNameTable() first."

    testAxis = AxisDescriptor()
    testAxis.name = "Test Axis"
    testAxis.tag = "TEST"
    testAxis.minimum = 0
    testAxis.default = 0
    testAxis.maximum = 100
    testAxis.map = [(0, 0), (40, 60), (100, 100)]
    axes = [testAxis]
    instances = [
        dict(location=dict(TEST=0), stylename="TotallyNormal"),
        dict(location=dict(TEST=100), stylename="TotallyTested"),
    ]
    fb.setupFvar(axes, instances)
    fb.setupAvar(axes)

    return fb


def _setupFontBuilderCFF2(fb):
    assert "fvar" in fb.font, "Must run _setupFontBuilderFvar() first."

    pen = T2CharStringPen(None, None, CFF2=True)
    drawTestGlyph(pen)
    charString = pen.getCharString()

    program = [
        200,
        200,
        -200,
        -200,
        2,
        "blend",
        "rmoveto",
        400,
        400,
        1,
        "blend",
        "hlineto",
        400,
        400,
        1,
        "blend",
        "vlineto",
        -400,
        -400,
        1,
        "blend",
        "hlineto",
    ]
    charStringVariable = T2CharString(program=program)

    charStrings = {
        ".notdef": charString,
        "A": charString,
        "a": charStringVariable,
        ".null": charString,
    }
    fb.setupCFF2(charStrings, regions=[{"TEST": (0, 1, 1)}])

    return fb


def _verifyOutput(outPath, tables=None):
    f = TTFont(outPath)
    f.saveXML(outPath + ".ttx", tables=tables)
    with open(outPath + ".ttx") as f:
        testData = stripVariableItemsFromTTX(f.read())
    refData = stripVariableItemsFromTTX(getTestData(os.path.basename(outPath) + ".ttx"))
    assert refData == testData


def _setupBeyond64kFontBuilder():
    fb = FontBuilder(1024, isTTF=True, beyond64k=True)
    fb.setupGlyphOrder([".notdef", "A"])
    fb.setupCharacterMap({65: "A"})

    pen = TTGlyphPen(None)
    emptyGlyph = pen.glyph()

    pen = TTGlyphPen(None)
    pen.moveTo((50, 0))
    pen.lineTo((50, 200))
    pen.lineTo((250, 200))
    pen.lineTo((250, 0))
    pen.closePath()
    glyph = pen.glyph()

    fb.setupGlyf({".notdef": emptyGlyph, "A": glyph})
    glyphTable = fb.font["GLYF"]
    fb.setupHorizontalMetrics(
        {
            ".notdef": (600, 0),
            "A": (500, glyphTable["A"].xMin),
        }
    )
    fb.setupHorizontalHeader(ascent=824, descent=200)
    fb.setupNameTable({"familyName": "Upper", "styleName": "Regular"})
    fb.setupOS2()
    fb.setupPost()
    return fb


def test_build_ttf(tmpdir):
    outPath = os.path.join(str(tmpdir), "test.ttf")

    fb, advanceWidths, nameStrings = _setupFontBuilder(True)

    pen = TTGlyphPen(None)
    drawTestGlyph(pen)
    glyph = pen.glyph()
    glyphs = {".notdef": glyph, "A": glyph, "a": glyph, ".null": glyph}
    fb.setupGlyf(glyphs)
    metrics = {}
    glyphTable = fb.font["glyf"]
    for gn, advanceWidth in advanceWidths.items():
        metrics[gn] = (advanceWidth, glyphTable[gn].xMin)
    fb.setupHorizontalMetrics(metrics)

    fb.setupHorizontalHeader(ascent=824, descent=200)
    fb.setupNameTable(nameStrings)
    fb.setupOS2()
    fb.addOpenTypeFeatures("feature salt { sub A by a; } salt;")
    fb.setupPost()
    fb.setupDummyDSIG()

    fb.save(outPath)

    _verifyOutput(outPath)


def test_build_beyond64k_ttf(tmpdir):
    outPath = os.path.join(str(tmpdir), "test.ttf")

    fb = _setupBeyond64kFontBuilder()

    assert {"GLYF", "LOCA", "MAXP", "HHEA", "HMTX"} <= set(fb.font.keys())
    assert not {"glyf", "loca", "maxp", "hhea", "hmtx"} & set(fb.font.keys())
    assert fb.font["OS/2"].xAvgCharWidth == 550

    fb.save(outPath)

    font = TTFont(outPath)
    assert {"GLYF", "LOCA", "MAXP", "HHEA", "HMTX"} <= set(font.keys())
    assert not {"glyf", "loca", "maxp", "hhea", "hmtx"} & set(font.keys())


def test_build_beyond64k_ttf_xml_round_trip(tmpdir):
    xmlPath = os.path.join(str(tmpdir), "test.ttx")
    outPath = os.path.join(str(tmpdir), "test.ttf")

    fb = _setupBeyond64kFontBuilder()
    fb.font.saveXML(xmlPath)

    font = TTFont()
    font.importXML(xmlPath)
    assert {"GLYF", "LOCA", "MAXP", "HHEA", "HMTX"} <= set(font.keys())
    assert not {"glyf", "loca", "maxp", "hhea", "hmtx"} & set(font.keys())

    font.save(outPath)
    font = TTFont(outPath)
    assert font.getGlyphOrder() == [".notdef", "A"]
    assert font["HMTX"]["A"] == (500, 50)
    assert font["GLYF"]["A"].xMin == 50


def test_setupGvar_uses_selected_table_family():
    fb = FontBuilder(1024, isTTF=True)
    fb.setupGvar({})
    assert "gvar" in fb.font
    assert "GVAR" not in fb.font

    fb = FontBuilder(1024, isTTF=True, beyond64k=True)
    fb.setupGvar({})
    assert "GVAR" in fb.font
    assert "gvar" not in fb.font
    assert not hasattr(fb, "setupGVAR")


def test_setupAvar_mappings():
    fb, _, nameStrings = _setupFontBuilder(True)
    fb.setupNameTable(nameStrings)

    weight = AxisDescriptor()
    weight.name = "Weight"
    weight.tag = "wght"
    weight.minimum = 100
    weight.default = 400
    weight.maximum = 900
    width = AxisDescriptor()
    width.name = "Width"
    width.tag = "wdth"
    width.minimum = 50
    width.default = 100
    width.maximum = 200
    axes = [weight, width]
    fb.setupFvar(axes, [])

    # Mapping locations are keyed by axis name, as in designspace documents.
    mapping = AxisMappingDescriptor(
        inputLocation={"Weight": 900, "Width": 50},
        outputLocation={"Weight": 700},
    )
    fb.setupAvar(axes, [mapping])

    from fontTools.varLib.avar.map import map as mapLocation

    font = fb.font
    assert font["avar"].majorVersion == 2
    assert mapLocation(font, {"wght": 900, "wdth": 50}) == pytest.approx(
        {"wght": 700, "wdth": 50}, abs=0.1
    )
    assert mapLocation(font, {"wght": 900, "wdth": 100}) == {"wght": 900, "wdth": 100}


def test_build_cubic_ttf(tmp_path):
    pen = TTGlyphPen(None)
    pen.moveTo((100, 100))
    pen.curveTo((200, 200), (300, 300), (400, 400))
    pen.closePath()
    glyph = pen.glyph()
    glyphs = {"A": glyph}

    # cubic outlines are not allowed in the glyf table
    fb = FontBuilder(1000, isTTF=True)
    with pytest.raises(ValueError, match="Glyph 'A' has cubic Bezier outlines"):
        fb.setupGlyf(glyphs)


def test_build_cubic_beyond64k_ttf(tmp_path):
    from fontTools.pens.recordingPen import RecordingPen

    fb = _setupBeyond64kFontBuilder()
    pen = TTGlyphPen(None)
    pen.moveTo((100, 100))
    pen.curveTo((200, 300), (300, 300), (400, 100))
    pen.closePath()
    fb.setupGlyf({".notdef": fb.font["GLYF"][".notdef"], "A": pen.glyph()})

    path = tmp_path / "cubic.ttf"
    fb.save(path)
    font = TTFont(path)
    pen = RecordingPen()
    font["GLYF"]["A"].draw(pen, font["GLYF"])
    assert pen.value == [
        ("moveTo", ((100, 100),)),
        ("curveTo", ((200, 300), (300, 300), (400, 100))),
        ("closePath", ()),
    ]


def test_build_otf(tmpdir):
    outPath = os.path.join(str(tmpdir), "test.otf")

    fb, advanceWidths, nameStrings = _setupFontBuilder(False)

    pen = T2CharStringPen(600, None)
    drawTestGlyph(pen)
    charString = pen.getCharString()
    charStrings = {
        ".notdef": charString,
        "A": charString,
        "a": charString,
        ".null": charString,
    }
    fb.setupCFF(
        nameStrings["psName"], {"FullName": nameStrings["psName"]}, charStrings, {}
    )

    lsb = {gn: cs.calcBounds(None)[0] for gn, cs in charStrings.items()}
    metrics = {}
    for gn, advanceWidth in advanceWidths.items():
        metrics[gn] = (advanceWidth, lsb[gn])
    fb.setupHorizontalMetrics(metrics)

    fb.setupHorizontalHeader(ascent=824, descent=200)
    fb.setupNameTable(nameStrings)
    fb.setupOS2()
    fb.addOpenTypeFeatures("feature kern { pos A a -50; } kern;")
    fb.setupPost()
    fb.setupDummyDSIG()

    fb.save(outPath)

    _verifyOutput(outPath)


def test_build_var(tmpdir):
    outPath = os.path.join(str(tmpdir), "test_var.ttf")

    fb, advanceWidths, nameStrings = _setupFontBuilder(True)

    pen = TTGlyphPen(None)
    pen.moveTo((100, 0))
    pen.lineTo((100, 400))
    pen.lineTo((500, 400))
    pen.lineTo((500, 000))
    pen.closePath()
    glyph1 = pen.glyph()

    pen = TTGlyphPen(None)
    pen.moveTo((50, 0))
    pen.lineTo((50, 200))
    pen.lineTo((250, 200))
    pen.lineTo((250, 0))
    pen.closePath()
    glyph2 = pen.glyph()

    pen = TTGlyphPen(None)
    emptyGlyph = pen.glyph()

    glyphs = {".notdef": emptyGlyph, "A": glyph1, "a": glyph2, ".null": emptyGlyph}
    fb.setupGlyf(glyphs)
    metrics = {}
    glyphTable = fb.font["glyf"]
    for gn, advanceWidth in advanceWidths.items():
        metrics[gn] = (advanceWidth, glyphTable[gn].xMin)
    fb.setupHorizontalMetrics(metrics)

    fb.setupHorizontalHeader(ascent=824, descent=200)
    fb.setupNameTable(nameStrings, mac=False)

    axes = [
        ("LEFT", 0, 0, 100, "Left"),
        ("RGHT", 0, 0, 100, "Right"),
        ("UPPP", 0, 0, 100, "Up"),
        ("DOWN", 0, 0, 100, "Down"),
    ]
    instances = [
        dict(location=dict(LEFT=0, RGHT=0, UPPP=0, DOWN=0), stylename="TotallyNormal"),
        dict(location=dict(LEFT=0, RGHT=100, UPPP=100, DOWN=0), stylename="Right Up"),
    ]
    fb.setupFvar(axes, instances)
    variations = {}
    # Four (x, y) pairs and four phantom points:
    leftDeltas = [(-200, 0), (-200, 0), (0, 0), (0, 0), None, None, None, None]
    rightDeltas = [(0, 0), (0, 0), (200, 0), (200, 0), None, None, None, None]
    upDeltas = [(0, 0), (0, 200), (0, 200), (0, 0), None, None, None, None]
    downDeltas = [(0, -200), (0, 0), (0, 0), (0, -200), None, None, None, None]
    variations["a"] = [
        TupleVariation(dict(RGHT=(0, 1, 1)), rightDeltas),
        TupleVariation(dict(LEFT=(0, 1, 1)), leftDeltas),
        TupleVariation(dict(UPPP=(0, 1, 1)), upDeltas),
        TupleVariation(dict(DOWN=(0, 1, 1)), downDeltas),
    ]
    fb.setupGvar(variations)

    fb.addFeatureVariations(
        [
            (
                [
                    {"LEFT": (0.8, 1), "DOWN": (0.8, 1)},
                    {"RGHT": (0.8, 1), "UPPP": (0.8, 1)},
                ],
                {"A": "a"},
            )
        ],
        featureTag="rclt",
    )

    statAxes = []
    for tag, minVal, defaultVal, maxVal, name in axes:
        values = [
            dict(name="Neutral", value=defaultVal, flags=0x2),
            dict(name=name, value=maxVal),
        ]
        statAxes.append(dict(tag=tag, name=name, values=values))
    fb.setupStat(statAxes)

    fb.setupOS2()
    fb.setupPost()
    fb.setupDummyDSIG()

    fb.save(outPath)

    _verifyOutput(outPath)


def test_build_cff2(tmpdir):
    outPath = os.path.join(str(tmpdir), "test_var.otf")

    fb, advanceWidths, nameStrings = _setupFontBuilder(False, 1000)
    fb.setupNameTable(nameStrings)
    fb = _setupFontBuilderFvar(fb)
    fb = _setupFontBuilderCFF2(fb)

    metrics = {gn: (advanceWidth, 0) for gn, advanceWidth in advanceWidths.items()}
    fb.setupHorizontalMetrics(metrics)

    fb.setupHorizontalHeader(ascent=824, descent=200)
    fb.setupOS2(
        sTypoAscender=825, sTypoDescender=200, usWinAscent=824, usWinDescent=200
    )
    fb.setupPost()

    fb.save(outPath)

    _verifyOutput(outPath)


def test_build_cff_to_cff2(tmpdir):
    fb, _, _ = _setupFontBuilder(False, 1000)

    pen = T2CharStringPen(600, None)
    drawTestGlyph(pen)
    charString = pen.getCharString()
    charStrings = {
        ".notdef": charString,
        "A": charString,
        "a": charString,
        ".null": charString,
    }
    fb.setupCFF("TestFont", {}, charStrings, {})

    from fontTools.cffLib.CFFToCFF2 import convertCFFToCFF2

    convertCFFToCFF2(fb.font)


def test_setupNameTable_no_mac():
    fb, _, nameStrings = _setupFontBuilder(True)
    fb.setupNameTable(nameStrings, mac=False)

    assert all(n for n in fb.font["name"].names if n.platformID == 3)
    assert not any(n for n in fb.font["name"].names if n.platformID == 1)


def test_setupNameTable_no_windows():
    fb, _, nameStrings = _setupFontBuilder(True)
    fb.setupNameTable(nameStrings, windows=False)

    assert all(n for n in fb.font["name"].names if n.platformID == 1)
    assert not any(n for n in fb.font["name"].names if n.platformID == 3)


@pytest.mark.parametrize(
    "is_ttf, keep_glyph_names, make_cff2, post_format",
    [
        (True, True, False, 2),  # TTF with post table format 2.0
        (True, False, False, 3),  # TTF with post table format 3.0
        (False, True, False, 3),  # CFF with post table format 3.0
        (False, False, False, 3),  # CFF with post table format 3.0
        (False, True, True, 2),  # CFF2 with post table format 2.0
        (False, False, True, 3),  # CFF2 with post table format 3.0
    ],
)
def test_setupPost(is_ttf, keep_glyph_names, make_cff2, post_format):
    fb, _, nameStrings = _setupFontBuilder(is_ttf)

    if make_cff2:
        fb.setupNameTable(nameStrings)
        fb = _setupFontBuilderCFF2(_setupFontBuilderFvar(fb))

    if keep_glyph_names:
        fb.setupPost()
    else:
        fb.setupPost(keepGlyphNames=keep_glyph_names)

    assert fb.isTTF is is_ttf
    assert ("CFF2" in fb.font) is make_cff2
    assert fb.font["post"].formatType == post_format


@pytest.mark.parametrize("count", [0xFFFF, 0x10000, 0x10001])
@pytest.mark.parametrize("cff2", [False, True])
def test_setupPost_beyond64k_count_limit(count, cff2):
    fb = FontBuilder(1024, isTTF=not cff2, beyond64k=True)
    order = [".notdef"] + [f"glyph{i}" for i in range(1, count)]
    fb.setupGlyphOrder(order)
    if cff2:
        fb.font["CFF2"] = newTable("CFF2")

    fb.setupPost()

    post = fb.font["post"]
    assert post.formatType == (2 if count <= 0xFFFF else 3)
    fb.font["MAXP"].numGlyphs = count
    if post.formatType == 2:
        # Isolate the glyph-count boundary from post's separate name-index limit.
        post.mapping = {name: "space" for name in order}
    data = post.compile(fb.font)
    reloaded = newTable("post")
    reloaded.decompile(data, fb.font)
    assert reloaded.formatType == post.formatType


@pytest.mark.parametrize("supplementary", [False, True])
@pytest.mark.parametrize("gid", [0xFFFF, 0x10000, 0x10001])
def test_character_map_high_glyph_ids(gid, supplementary):
    fb = FontBuilder(1024, beyond64k=True)
    order = [".notdef"] + [f"glyph{i}" for i in range(1, gid + 1)]
    fb.setupGlyphOrder(order)
    mapping = {65: order[gid], 66: order[1]}
    if supplementary:
        mapping[0x10000] = order[gid]

    fb.setupCharacterMap(mapping)

    cmap = fb.font["cmap"]
    reloaded = newTable("cmap")
    reloaded.decompile(cmap.compile(fb.font), fb.font)
    assert reloaded.getBestCmap() == mapping
    if gid > 0xFFFF:
        assert {(sub.platformID, sub.platEncID, sub.format) for sub in cmap.tables} == {
            (3, 10, 12),
            (0, 4, 12),
        }


@pytest.mark.parametrize("default", [False, True])
@pytest.mark.parametrize("gid", [0xFFFF, 0x10000, 0x10001])
def test_unicodeVariationSequences_high_glyph_ids(gid, default):
    fb = FontBuilder(1024, beyond64k=True)
    order = [".notdef"] + [f"glyph{i}" for i in range(1, gid + 1)]
    fb.setupGlyphOrder(order)
    mapping = {65: order[gid] if default else order[1]}
    fb.setupCharacterMap(mapping, [(65, 0xFE00, order[gid])])

    uvs = fb.font["cmap"].tables[-1]
    assert uvs.format == (15 if gid > 0xFFFF and not default else 14)
    reloaded = newTable("cmap")
    reloaded.decompile(fb.font["cmap"].compile(fb.font), fb.font)
    assert reloaded.getcmap(0, 5).uvsDict == {
        0xFE00: [(65, None if default else order[gid])]
    }


def test_unicodeVariationSequences(tmpdir):
    familyName = "UVSTestFont"
    styleName = "Regular"
    nameStrings = dict(familyName=familyName, styleName=styleName)
    nameStrings["psName"] = familyName + "-" + styleName
    glyphOrder = [".notdef", "space", "zero", "zero.slash"]
    cmap = {ord(" "): "space", ord("0"): "zero"}
    uvs = [
        (0x0030, 0xFE00, "zero.slash"),
        (0x0030, 0xFE01, None),  # not an official sequence, just testing
    ]
    metrics = {gn: (600, 0) for gn in glyphOrder}
    pen = TTGlyphPen(None)
    glyph = pen.glyph()  # empty placeholder
    glyphs = {gn: glyph for gn in glyphOrder}

    fb = FontBuilder(1024, isTTF=True)
    fb.setupGlyphOrder(glyphOrder)
    fb.setupCharacterMap(cmap, uvs)
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=824, descent=200)
    fb.setupNameTable(nameStrings)
    fb.setupOS2()
    fb.setupPost()

    outPath = os.path.join(str(tmpdir), "test_uvs.ttf")
    fb.save(outPath)
    _verifyOutput(outPath, tables=["cmap"])

    uvs = [
        (0x0030, 0xFE00, "zero.slash"),
        (
            0x0030,
            0xFE01,
            "zero",
        ),  # should result in the exact same subtable data, due to cmap[0x0030] == "zero"
    ]
    fb.setupCharacterMap(cmap, uvs)
    fb.save(outPath)
    _verifyOutput(outPath, tables=["cmap"])


def test_setupPanose():
    from fontTools.ttLib.tables.O_S_2f_2 import Panose

    fb, advanceWidths, nameStrings = _setupFontBuilder(True)

    pen = TTGlyphPen(None)
    drawTestGlyph(pen)
    glyph = pen.glyph()
    glyphs = {".notdef": glyph, "A": glyph, "a": glyph, ".null": glyph}
    fb.setupGlyf(glyphs)
    metrics = {}
    glyphTable = fb.font["glyf"]
    for gn, advanceWidth in advanceWidths.items():
        metrics[gn] = (advanceWidth, glyphTable[gn].xMin)
    fb.setupHorizontalMetrics(metrics)

    fb.setupHorizontalHeader(ascent=824, descent=200)
    fb.setupNameTable(nameStrings)
    fb.setupOS2()
    fb.setupPost()

    panoseValues = {  # sample value of Times New Roman from https://www.w3.org/Printing/stevahn.html
        "bFamilyType": 2,
        "bSerifStyle": 2,
        "bWeight": 6,
        "bProportion": 3,
        "bContrast": 5,
        "bStrokeVariation": 4,
        "bArmStyle": 5,
        "bLetterForm": 2,
        "bMidline": 3,
        "bXHeight": 4,
    }
    panoseObj = Panose(**panoseValues)

    for name in panoseValues:
        assert getattr(fb.font["OS/2"].panose, name) == 0

    fb.setupOS2(panose=panoseObj)
    fb.setupPost()

    for name, value in panoseValues.items():
        assert getattr(fb.font["OS/2"].panose, name) == value


# ---------------------------------------------------------------------------
# setupLigatureSubst
# ---------------------------------------------------------------------------

LIGATURE_GLYPHS = [".notdef", "space", "f", "i", "l", "t", "fi", "fl", "ffi", "ft"]


def _setupLigatureFont(glyphs=None):
    glyphs = glyphs if glyphs is not None else LIGATURE_GLYPHS
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder(glyphs)
    fb.setupCharacterMap({0x20: "space", 0x66: "f", 0x69: "i", 0x6C: "l", 0x74: "t"})
    pen = TTGlyphPen(None)
    glyph = pen.glyph()
    fb.setupGlyf({name: glyph for name in glyphs})
    fb.setupHorizontalMetrics({name: (500, 0) for name in glyphs})
    fb.setupHorizontalHeader()
    fb.setupNameTable({"familyName": "LigaTest", "styleName": "Regular"})
    fb.setupOS2()
    fb.setupPost()
    return fb


def _ligatureSubst(font):
    lookup = font["GSUB"].table.LookupList.Lookup[-1]
    assert lookup.LookupType == 4
    assert lookup.SubTableCount == 1
    return lookup.SubTable[0]


def test_setupLigatureSubst_basic():
    fb = _setupLigatureFont()
    fb.setupLigatureSubst({("f", "i"): "fi", ("f", "l"): "fl"})

    gsub = fb.font["GSUB"].table
    assert gsub.Version == 0x00010000
    assert len(gsub.LookupList.Lookup) == 1
    assert gsub.LookupList.Lookup[0].LookupType == 4

    featureRecord = gsub.FeatureList.FeatureRecord[0]
    assert featureRecord.FeatureTag == "liga"
    assert featureRecord.Feature.LookupListIndex == [0]

    scriptRecord = gsub.ScriptList.ScriptRecord[0]
    assert scriptRecord.ScriptTag == "DFLT"
    assert scriptRecord.Script.LangSysCount == 0
    assert scriptRecord.Script.DefaultLangSys.FeatureIndex == [0]
    assert scriptRecord.Script.DefaultLangSys.ReqFeatureIndex == 0xFFFF

    ligatures = _ligatureSubst(fb.font).ligatures
    assert set(ligatures) == {"f"}
    assert [(lig.Component, lig.LigGlyph) for lig in ligatures["f"]] == [
        (("i",), "fi"),
        (("l",), "fl"),
    ]
    # the longest context the shaping engine may need to look at
    assert fb.font["OS/2"].usMaxContext == 2


def test_setupLigatureSubst_commonPrefixAndOrdering():
    rules = {
        ("f", "i"): "fi",
        ("f", "l"): "fl",
        ("f", "f", "i"): "ffi",
        ("f", "t"): "ft",
    }
    # The resulting lookup must not depend on the input mapping order.
    for permutation in (
        rules,
        dict(reversed(list(rules.items()))),
        {("f", "t"): "ft", ("f", "f", "i"): "ffi", ("f", "l"): "fl", ("f", "i"): "fi"},
    ):
        fb = _setupLigatureFont()
        fb.setupLigatureSubst(permutation)
        ligatures = _ligatureSubst(fb.font).ligatures
        assert list(ligatures) == ["f"]
        # the three-glyph rule must come before the two-glyph rules, and
        # equal-length rules keep a deterministic content-based order
        assert [(lig.Component, lig.LigGlyph) for lig in ligatures["f"]] == [
            (("f", "i"), "ffi"),
            (("i",), "fi"),
            (("l",), "fl"),
            (("t",), "ft"),
        ]
    assert fb.font["OS/2"].usMaxContext == 3


def test_setupLigatureSubst_matchesFeatureFileCompile():
    from fontTools.misc.testTools import getXML

    rules = {("f", "i"): "fi", ("f", "l"): "fl", ("f", "f", "i"): "ffi"}

    builderFont = _setupLigatureFont()
    builderFont.setupLigatureSubst(dict(reversed(list(rules.items()))))

    feaFont = _setupLigatureFont()
    feaFont.addOpenTypeFeatures("""
        languagesystem DFLT dflt;
        feature liga {
          sub f i by fi;
          sub f l by fl;
          sub f f i by ffi;
        } liga;
        """)

    assert getXML(builderFont.font["GSUB"].toXML, builderFont.font) == getXML(
        feaFont.font["GSUB"].toXML, feaFont.font
    )


def test_setupLigatureSubst_roundTrip(tmp_path):
    fb = _setupLigatureFont()
    fb.setupLigatureSubst({("f", "i"): "fi", ("f", "l"): "fl", ("f", "f", "i"): "ffi"})
    out = tmp_path / "liga.ttf"
    fb.save(out)

    reopened = TTFont(out)
    assert len(reopened["GSUB"].table.LookupList.Lookup) == 1
    ligatures = reopened["GSUB"].table.LookupList.Lookup[0].SubTable[0].ligatures
    assert [lig.LigGlyph for lig in ligatures["f"]] == ["ffi", "fi", "fl"]


def test_setupLigatureSubst_duplicates():
    fb = _setupLigatureFont()
    # exact duplicates are collapsed
    fb.setupLigatureSubst({("f", "i"): "fi", ("f", "i"): "fi"})
    ligatures = _ligatureSubst(fb.font).ligatures
    assert len(ligatures["f"]) == 1

    # conflicting duplicates within one call are rejected and leave no trace
    conflictFont = _setupLigatureFont()

    # a plain dict cannot retain duplicate keys, so emulate a mapping that does
    class ConflictingMapping:
        def __bool__(self):
            return True

        def items(self):
            return [(("f", "i"), "fi"), (("f", "i"), "fl")]

    with pytest.raises(ValueError, match="conflicting ligature rules"):
        conflictFont.setupLigatureSubst(ConflictingMapping())
    assert "GSUB" not in conflictFont.font
    assert len(fb.font["GSUB"].table.LookupList.Lookup) == 1


@pytest.mark.parametrize(
    "rules, message",
    [
        ({("f",): "fi"}, "at least two glyphs"),
        ({("fi",): "fi"}, "at least two glyphs"),
        ({("f", "i"): "missing"}, "glyphs missing from the font"),
        ({("f", "missing"): "fi"}, "glyphs missing from the font"),
        ({("f", "i"): 5}, "output glyph name must be a string"),
        ({("f", 1): "fi"}, "tuple of glyph name strings"),
        ({}, "must not be empty"),
    ],
)
def test_setupLigatureSubst_invalidInput(rules, message):
    fb = _setupLigatureFont()
    with pytest.raises(ValueError, match=message):
        fb.setupLigatureSubst(rules)
    # validation happens before the font is modified
    assert "GSUB" not in fb.font


def test_setupLigatureSubst_invalidTags():
    fb = _setupLigatureFont()
    rules = {("f", "i"): "fi"}
    with pytest.raises(ValueError, match="featureTag"):
        fb.setupLigatureSubst(rules, featureTag="x")
    with pytest.raises(ValueError, match="scriptTag"):
        fb.setupLigatureSubst(rules, scriptTag="latnX")
    with pytest.raises(ValueError, match="langSysTag"):
        fb.setupLigatureSubst(rules, langSysTag="en")
    assert "GSUB" not in fb.font


def test_setupLigatureSubst_coexistsWithExistingGSUB():
    fb = _setupLigatureFont()
    fb.addOpenTypeFeatures("""
        languagesystem latn dflt;
        languagesystem latn ENG;
        feature rlig { sub f by t; } rlig;
        """)
    gsub = fb.font["GSUB"].table
    assert [lookup.LookupType for lookup in gsub.LookupList.Lookup] == [1]

    fb.setupLigatureSubst(
        {("f", "i"): "fi", ("f", "l"): "fl"},
        featureTag="liga",
        scriptTag="latn",
    )
    gsub = fb.font["GSUB"].table

    # the original lookup survives and the new one is appended
    assert [lookup.LookupType for lookup in gsub.LookupList.Lookup] == [1, 4]
    assert [record.FeatureTag for record in gsub.FeatureList.FeatureRecord] == [
        "liga",
        "rlig",
    ]
    rlig = next(
        record
        for record in gsub.FeatureList.FeatureRecord
        if record.FeatureTag == "rlig"
    )
    assert rlig.Feature.LookupListIndex == [0]
    liga = next(
        record
        for record in gsub.FeatureList.FeatureRecord
        if record.FeatureTag == "liga"
    )
    assert liga.Feature.LookupListIndex == [1]

    # both the default and the explicit language system reach both features
    script = next(
        record for record in gsub.ScriptList.ScriptRecord if record.ScriptTag == "latn"
    )
    assert script.Script.DefaultLangSys.FeatureIndex == [0, 1]
    eng = next(
        record for record in script.Script.LangSysRecord if record.LangSysTag == "ENG "
    )
    assert eng.LangSys.FeatureIndex == [0, 1]


def test_setupLigatureSubst_reusesFeatureAndAddsScriptsAndLangSys():
    fb = _setupLigatureFont()
    fb.setupLigatureSubst({("f", "i"): "fi"}, featureTag="liga", scriptTag="latn")
    # a second call with the same feature reuses it instead of duplicating it
    fb.setupLigatureSubst({("f", "l"): "fl"}, featureTag="liga", scriptTag="latn")
    gsub = fb.font["GSUB"].table
    assert len(gsub.FeatureList.FeatureRecord) == 1
    assert gsub.FeatureList.FeatureRecord[0].Feature.LookupListIndex == [0, 1]
    assert len(gsub.LookupList.Lookup) == 2
    assert gsub.ScriptList.ScriptRecord[0].Script.DefaultLangSys.FeatureIndex == [0]

    # another script gets wired to the same feature record
    fb.setupLigatureSubst({("f", "i"): "fi"}, featureTag="liga", scriptTag="cyrl")
    gsub = fb.font["GSUB"].table
    assert [record.ScriptTag for record in gsub.ScriptList.ScriptRecord] == [
        "cyrl",
        "latn",
    ]
    cyrl = next(
        record for record in gsub.ScriptList.ScriptRecord if record.ScriptTag == "cyrl"
    )
    assert cyrl.Script.DefaultLangSys.FeatureIndex == [0]

    # an explicit language system leaves the default language system alone
    fb.setupLigatureSubst(
        {("f", "i"): "fi"},
        featureTag="clig",
        scriptTag="grek",
        langSysTag="ELL ",
    )
    gsub = fb.font["GSUB"].table
    grek = next(
        record for record in gsub.ScriptList.ScriptRecord if record.ScriptTag == "grek"
    )
    assert grek.Script.DefaultLangSys is None
    assert grek.Script.LangSysRecord[0].LangSysTag == "ELL "
    cligIndex = next(
        index
        for index, record in enumerate(gsub.FeatureList.FeatureRecord)
        if record.FeatureTag == "clig"
    )
    assert grek.Script.LangSysRecord[0].LangSys.FeatureIndex == [cligIndex]
