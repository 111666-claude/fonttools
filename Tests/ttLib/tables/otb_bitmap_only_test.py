"""Support for X11 bitmap-only sfnt (``.otb``) fonts.

These fonts store their glyph pictures in ``EBLC``/``EBDT`` (or
``CBLC``/``CBDT``). Their ``glyf`` table is an intentionally zero-length
placeholder shell and ``loca`` is either a single dummy entry ``[0]``
(FontForge's ``dummyloca``) or ``numGlyphs + 1`` all-zero offsets. In both
cases ``maxp.numGlyphs`` counts the bitmap glyphs independently.

See https://github.com/fonttools/fonttools/issues/4120.

The real-world fixture ``otb-bitmap-only-terminus-u12n.otb`` is Terminus Font
(ter-u12n.otb), Copyright (c) 2010-2014 Dimitar Toshkov Zhekov, licensed under
the SIL Open Font License, Version 1.1.
"""

import os
from io import BytesIO

import pytest

from fontTools.fontBuilder import FontBuilder
from fontTools.misc.testTools import parseXmlInto
from fontTools.ttLib import TTFont, TTLibError, newTable
from fontTools.ttLib.tables._g_l_y_f import (
    BitmapOnlyError,
    BitmapOnlyGlyfError,
    Glyph,
)

CURR_DIR = os.path.dirname(os.path.abspath(__file__))
OTB_FIXTURE = os.path.normpath(
    os.path.join(CURR_DIR, "..", "data", "otb-bitmap-only-terminus-u12n.otb")
)
HAS_OTB_FIXTURE = os.path.exists(OTB_FIXTURE)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def decoded_bitmaps(font):
    """Return ``{(strikeIndex, glyphName): imageData}`` for an EBDT table."""
    out = {}
    eblc = font["EBLC"]
    ebdt = font["EBDT"]
    for strikeIndex, strike in enumerate(eblc.strikes):
        data = ebdt.strikeData[strikeIndex]
        for sub in strike.indexSubTables:
            for name in sub.names:
                glyph = data.get(name)
                if glyph is not None:
                    out[(strikeIndex, name)] = bytes(glyph.imageData)
    return out


def assert_same_terminus_font(original, reloaded):
    assert reloaded["maxp"].numGlyphs == original["maxp"].numGlyphs
    assert reloaded.getGlyphOrder() == original.getGlyphOrder()
    assert reloaded.getBestCmap() == original.getBestCmap()
    # Every loca offset is zero: glyf contains no outline records.
    assert set(reloaded["loca"].locations) == {0}
    assert len(reloaded["loca"]) == original["maxp"].numGlyphs + 1
    assert reloaded.reader.tables["glyf"].length == 0
    assert decoded_bitmaps(reloaded) == decoded_bitmaps(original)


EBLC_XML = """
<header version="2.0"/>
<strike index="0">
  <bitmapSizeTable>
    <sbitLineMetrics direction="hori">
      <ascender value="8"/><descender value="-1"/><widthMax value="2"/>
      <caretSlopeNumerator value="1"/><caretSlopeDenominator value="0"/>
      <caretOffset value="0"/><minOriginSB value="0"/><minAdvanceSB value="0"/>
      <maxBeforeBL value="8"/><minAfterBL value="-1"/><pad1 value="0"/><pad2 value="0"/>
    </sbitLineMetrics>
    <sbitLineMetrics direction="vert">
      <ascender value="0"/><descender value="0"/><widthMax value="0"/>
      <caretSlopeNumerator value="1"/><caretSlopeDenominator value="0"/>
      <caretOffset value="0"/><minOriginSB value="0"/><minAdvanceSB value="0"/>
      <maxBeforeBL value="0"/><minAfterBL value="0"/><pad1 value="0"/><pad2 value="0"/>
    </sbitLineMetrics>
    <colorRef value="0"/>
    <startGlyphIndex value="0"/><endGlyphIndex value="1"/>
    <ppemX value="8"/><ppemY value="8"/><bitDepth value="1"/><flags value="1"/>
  </bitmapSizeTable>
  <eblc_index_sub_table_1 imageFormat="2" firstGlyphIndex="0" lastGlyphIndex="1">
    <glyphLoc id="0" name=".notdef"/>
    <glyphLoc id="1" name="A"/>
  </eblc_index_sub_table_1>
</strike>
"""

EBDT_XML = """
<header version="2.0"/>
<strikedata index="0">
  <ebdt_bitmap_format_2 name=".notdef">
    <SmallGlyphMetrics>
      <height value="2"/><width value="2"/><BearingX value="0"/>
      <BearingY value="2"/><Advance value="3"/>
    </SmallGlyphMetrics>
    <rawimagedata>aa</rawimagedata>
  </ebdt_bitmap_format_2>
  <ebdt_bitmap_format_2 name="A">
    <SmallGlyphMetrics>
      <height value="2"/><width value="2"/><BearingX value="0"/>
      <BearingY value="2"/><Advance value="3"/>
    </SmallGlyphMetrics>
    <rawimagedata>f0</rawimagedata>
  </ebdt_bitmap_format_2>
</strikedata>
"""


def build_minimal_bitmap_only_font(*, shell=True, bitmaps=True):
    """Build a minimal two-glyph bitmap-only sfnt in memory."""
    fb = FontBuilder(100, isTTF=True)
    glyphOrder = [".notdef", "A"]
    fb.setupGlyphOrder(glyphOrder)
    fb.setupCharacterMap({65: "A"})
    fb.setupGlyf({name: Glyph() for name in glyphOrder})
    fb.setupHorizontalMetrics({name: (500, 0) for name in glyphOrder})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable(
        {"familyName": "MiniOTB", "styleName": "Regular", "fullName": "MiniOTB Regular"}
    )
    fb.setupOS2(
        sTypoAscender=800,
        sTypoDescender=-200,
        usWinAscent=800,
        usWinDescent=200,
    )
    fb.setupPost()
    font = fb.font

    glyf = font["glyf"]
    if shell:
        # The explicit bitmap-only selection: no outline records at all and a
        # single dummy loca entry.
        glyf.glyphs = {}
        glyf.bitmapOnly = True

    if bitmaps:
        eblc = newTable("EBLC")
        parseXmlInto(font, eblc, EBLC_XML)
        font["EBLC"] = eblc
        ebdt = newTable("EBDT")
        parseXmlInto(font, ebdt, EBDT_XML)
        font["EBDT"] = ebdt

    return font


def save_reload(font, **kwargs):
    buf = BytesIO()
    font.save(buf)
    buf.seek(0)
    return TTFont(buf, **kwargs)


# ---------------------------------------------------------------------------
# real-world OTB fixture
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_OTB_FIXTURE, reason="real OTB fixture not available")
def test_real_otb_fixture_has_bitmap_only_shell():
    font = TTFont(OTB_FIXTURE)
    assert "EBLC" in font and "EBDT" in font
    assert font.reader.tables["glyf"].length == 0
    assert font["maxp"].maxContours == 0
    # Terminus keeps numGlyphs+1 offsets, all zero.
    assert len(font["loca"]) == font["maxp"].numGlyphs + 1
    assert set(font["loca"].locations) == {0}
    # Decompiling the zero-length shell flags bitmap-only semantics.
    assert font["glyf"].bitmapOnly is True
    assert len(font["glyf"].glyphs) == font["maxp"].numGlyphs


@pytest.mark.skipif(not HAS_OTB_FIXTURE, reason="real OTB fixture not available")
def test_real_otb_modify_nonoutline_table_raw_write_path():
    # glyf/loca/EBDT/EBLC are never loaded, so the writer copies their raw
    # records straight from the source sfnt ("raw passthrough" write path).
    original = TTFont(OTB_FIXTURE)
    raw_glyf = original.reader["glyf"]
    raw_loca = original.reader["loca"]
    raw_ebdt = original.reader["EBDT"]
    raw_eblc = original.reader["EBLC"]

    original["name"].setName("Raw Path Modified", 1, 3, 1, 0x409)
    reloaded = save_reload(original, lazy=True)

    assert reloaded.reader["glyf"] == raw_glyf == b""
    assert reloaded.reader["loca"] == raw_loca
    assert reloaded.reader["EBDT"] == raw_ebdt
    assert reloaded.reader["EBLC"] == raw_eblc
    assert_same_terminus_font(TTFont(OTB_FIXTURE), reloaded)
    assert reloaded["name"].getDebugName(1) == "Raw Path Modified" or any(
        r.toUnicode() == "Raw Path Modified"
        for r in reloaded["name"].names
        if r.nameID == 1
    )


@pytest.mark.skipif(not HAS_OTB_FIXTURE, reason="real OTB fixture not available")
def test_real_otb_loaded_glyf_compile_write_path():
    # Touching glyf (or lazy=False) forces the compile write path, which must
    # preserve the zero-length shell instead of raising KeyError or emitting
    # the one-NUL-byte compatibility table.
    original = TTFont(OTB_FIXTURE, lazy=False)
    assert original["glyf"].bitmapOnly is True
    original["name"].setName("Compile Path Modified", 1, 3, 1, 0x409)

    reloaded = save_reload(original, lazy=False)
    assert_same_terminus_font(TTFont(OTB_FIXTURE, lazy=False), reloaded)

    # Saving the reloaded font once more must keep working (issue #4120 pt. 1).
    buf = BytesIO()
    reloaded.save(buf)
    buf.seek(0)
    again = TTFont(buf)
    assert again.reader.tables["glyf"].length == 0
    assert set(again["loca"].locations) == {0}


# ---------------------------------------------------------------------------
# exact single-entry loca shape (FontForge / Ambrosia style)
# ---------------------------------------------------------------------------


def test_decompile_single_entry_loca_sets_shell():
    font = TTFont(sfntVersion="\x00\x01\x00\x00")
    glyphOrder = [".notdef", "A"]
    font.setGlyphOrder(glyphOrder)
    font["maxp"] = newTable("maxp")
    font["maxp"].numGlyphs = len(glyphOrder)
    font["loca"] = newTable("loca")
    font["loca"].locations = [0]
    glyf = newTable("glyf")
    glyf.decompile(b"", font)

    assert glyf.glyphs == {}
    assert glyf.bitmapOnly is True
    # Must not raise KeyError despite glyphOrder naming both glyphs.
    assert glyf.compile(font) == b""
    assert list(font["loca"]) == [0]
    # numGlyphs still counts the bitmap glyphs.
    assert font["maxp"].numGlyphs == len(glyphOrder)


def test_single_entry_loca_roundtrip_after_save():
    font = TTFont(sfntVersion="\x00\x01\x00\x00")
    glyphOrder = [".notdef", "A"]
    font.setGlyphOrder(glyphOrder)
    head = newTable("head")
    head.decompile(b"\0" * 54, font)
    head.indexToLocFormat = 0
    font["head"] = head
    maxp = newTable("maxp")
    maxp.tableVersion = 0x00005000
    maxp.numGlyphs = len(glyphOrder)
    font["maxp"] = maxp
    font["hmtx"] = newTable("hmtx")
    font["hmtx"].metrics = {name: (600, 0) for name in glyphOrder}
    font["loca"] = newTable("loca")
    font["loca"].locations = [0]
    glyf = newTable("glyf")
    glyf.decompile(b"", font)
    font["glyf"] = glyf

    reloaded = save_reload(font)
    assert reloaded.reader.tables["glyf"].length == 0
    assert list(reloaded["loca"]) == [0]
    assert reloaded["maxp"].numGlyphs == len(glyphOrder)
    # A second save must not raise either.
    buf2 = BytesIO()
    reloaded.save(buf2)
    assert buf2.getvalue()


def test_empty_shell_ttx_roundtrip_has_no_ttglyph_records():
    from io import StringIO

    font = TTFont(sfntVersion="\x00\x01\x00\x00")
    glyphOrder = [".notdef", "A"]
    font.setGlyphOrder(glyphOrder)
    head = newTable("head")
    head.decompile(b"\0" * 54, font)
    head.indexToLocFormat = 0
    font["head"] = head
    font["maxp"] = newTable("maxp")
    font["maxp"].tableVersion = 0x00005000
    font["maxp"].numGlyphs = len(glyphOrder)
    font["loca"] = newTable("loca")
    font["loca"].locations = [0]
    glyf = newTable("glyf")
    glyf.decompile(b"", font)
    font["glyf"] = glyf

    xml = StringIO()
    font.saveXML(xml)
    glyf_xml = xml.getvalue().split("<glyf>", 1)[1].split("</glyf>", 1)[0]
    assert "<TTGlyph" not in glyf_xml

    xml.seek(0)
    restored = TTFont()
    restored.importXML(xml)
    assert restored["glyf"].glyphs == {}
    binary = save_reload(restored)
    assert binary.reader.tables["glyf"].length == 0
    assert list(binary["loca"]) == [0]
    assert binary["maxp"].numGlyphs == len(glyphOrder)


# ---------------------------------------------------------------------------
# minimal constructed bitmap-only font with real bitmap payload
# ---------------------------------------------------------------------------


def test_minimal_bitmap_only_creation_roundtrip():
    font = build_minimal_bitmap_only_font()
    # Direct table compilation.
    assert font["glyf"].compile(font) == b""
    assert list(font["loca"].locations) == [0]

    reloaded = save_reload(font, lazy=False)

    # Table directory keeps the bitmap/sfnt tables and the shell.
    for tag in ("EBLC", "EBDT", "cmap", "glyf", "loca", "head", "maxp", "hmtx"):
        assert tag in reloaded
    assert reloaded.reader.tables["glyf"].length == 0
    assert list(reloaded["loca"].locations) == [0]
    assert reloaded["maxp"].numGlyphs == 2

    # Glyph mapping survives.
    cmap = reloaded.getBestCmap()
    assert cmap[65] == "A"

    # Bitmap payload survives byte-for-byte.
    strike = reloaded["EBDT"].strikeData[0]
    assert bytes(strike[".notdef"].imageData) == bytes.fromhex("aa")
    assert bytes(strike["A"].imageData) == bytes.fromhex("f0")


def test_explicit_flag_accepts_common_spellings():
    glyf = newTable("glyf")
    for alias in (
        "bitmap_only",
        "isBitmapOnly",
        "emptyShell",
        "zeroLength",
        "zeroLengthShell",
        "onlyStrikes",
    ):
        setattr(glyf, alias, True)
        assert glyf.bitmapOnly is True
        assert getattr(glyf, alias) is True
        glyf.setBitmapOnly(False)
        assert glyf.bitmapOnly is False


def test_font_level_bitmaponly_marker_is_honoured():
    font = build_minimal_bitmap_only_font()
    # Populate with empty placeholders but select bitmap-only at font level.
    order = font.getGlyphOrder()
    font["glyf"].glyphs = {name: Glyph() for name in order}
    font["glyf"].bitmapOnly = False
    font.bitmapOnly = True
    assert font["glyf"].compile(font) == b""


# ---------------------------------------------------------------------------
# ordinary empty TrueType keeps the one-NUL-byte compatibility output
# ---------------------------------------------------------------------------


def test_normal_empty_truetype_keeps_nul_byte():
    font = build_minimal_bitmap_only_font(shell=False, bitmaps=False)
    order = font.getGlyphOrder()
    # FontBuilder already attached empty Glyph records; make this explicit.
    font["glyf"].glyphs = {name: Glyph() for name in order}
    assert font["glyf"].bitmapOnly is False

    data = font["glyf"].compile(font)
    assert data == b"\x00"
    assert list(font["loca"].locations) == [0] * (len(order) + 1)

    reloaded = save_reload(font)
    assert reloaded.reader.tables["glyf"].length == 1


# ---------------------------------------------------------------------------
# mixing outlines with the bitmap-only placeholder is a hard failure
# ---------------------------------------------------------------------------


def test_bitmaponly_with_outline_raises_recognizable_error():
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    font = build_minimal_bitmap_only_font()
    order = font.getGlyphOrder()
    # Start from empty placeholders for every glyph ...
    font["glyf"].glyphs = {name: Glyph() for name in order}
    font["glyf"].bitmapOnly = True
    # ... then give "A" a real outline.
    pen = TTGlyphPen(None)
    pen.moveTo((100, 0))
    pen.lineTo((200, 0))
    pen.lineTo((200, 300))
    pen.closePath()
    font["glyf"].glyphs["A"] = pen.glyph()

    assert BitmapOnlyError is BitmapOnlyGlyfError
    with pytest.raises(BitmapOnlyGlyfError, match="(?i)bitmap-only|outline"):
        font["glyf"].compile(font)
    # Recognisable through the standard fontTools and Python error types.
    with pytest.raises(TTLibError):
        font["glyf"].compile(font)
    with pytest.raises(ValueError):
        font["glyf"].compile(font)
    # Saving must surface the same failure rather than silently dropping data.
    with pytest.raises(BitmapOnlyGlyfError):
        font.save(BytesIO())


def test_partial_glyph_mapping_without_flag_still_raises_keyerror():
    font = TTFont()
    font.setGlyphOrder([".notdef", "space"])
    font["glyf"] = newTable("glyf")
    font["glyf"].glyphs = {".notdef": Glyph()}
    with pytest.raises(KeyError):
        font["glyf"].compile(font)
