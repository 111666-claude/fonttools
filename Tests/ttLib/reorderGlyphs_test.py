import pytest

from io import BytesIO
from pathlib import Path
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.ttLib import TTFont
from fontTools.ttLib.reorderGlyphs import reorderGlyphs

DATA_DIR = Path(__file__).parent / "data"


@pytest.mark.parametrize("lazy", [True, False, None])
def test_reorder_lazy_ligatures(lazy):
    fb = FontBuilder(1000)
    fb.setupGlyphOrder([".notdef", "a", "b", "a_b", "unused"])
    fb.setupPost()
    addOpenTypeFeaturesFromString(fb.font, "feature liga { sub a b by a_b; } liga;")
    data = BytesIO()
    fb.font.save(data)
    font = TTFont(BytesIO(data.getvalue()), lazy=lazy)
    order = font.getGlyphOrder()
    reorderGlyphs(font, order[:1] + list(reversed(order[1:])))
    output = BytesIO()
    font.save(output)
    font = TTFont(BytesIO(output.getvalue()))
    ligature = font["GSUB"].table.LookupList.Lookup[0].SubTable[0].ligatures["a"][0]
    assert ligature.Component == ["b"]
    assert ligature.LigGlyph == "a_b"


def test_ensure_decompiled_high_level_ligatures():
    from fontTools.ttLib.tables import otTables

    subtable = otTables.LigatureSubst()
    subtable.ensureDecompiled(recurse=True)
    subtable.ligatures = {("a", "b"): "a_b"}
    subtable.ensureDecompiled(recurse=True)
    assert subtable.ligatures == {("a", "b"): "a_b"}


@pytest.mark.parametrize("lazy", [True, False, None])
def test_reorder_glyphs(lazy):
    font_path = DATA_DIR / "Test-Regular.ttf"
    font = TTFont(str(font_path), lazy=lazy)
    old_coverage1 = list(
        font["GSUB"].table.LookupList.Lookup[0].SubTable[0].Coverage[0].glyphs
    )
    old_coverage2 = list(
        font["GPOS"].table.LookupList.Lookup[0].SubTable[0].Coverage.glyphs
    )

    ga = font.getGlyphOrder()
    ga = [ga[0]] + list(reversed(ga[1:]))
    reorderGlyphs(font, ga)

    new_coverage1 = list(
        font["GSUB"].table.LookupList.Lookup[0].SubTable[0].Coverage[0].glyphs
    )
    new_coverage2 = list(
        font["GPOS"].table.LookupList.Lookup[0].SubTable[0].Coverage.glyphs
    )

    assert list(reversed(old_coverage1)) == new_coverage1
    assert list(reversed(old_coverage2)) == new_coverage2


def test_ttfont_reorder_glyphs():
    font_path = DATA_DIR / "Test-Regular.ttf"
    font = TTFont(str(font_path))
    ga = font.getGlyphOrder()
    ga = [ga[0]] + list(reversed(ga[1:]))

    old_coverage1 = list(
        font["GSUB"].table.LookupList.Lookup[0].SubTable[0].Coverage[0].glyphs
    )
    old_coverage2 = list(
        font["GPOS"].table.LookupList.Lookup[0].SubTable[0].Coverage.glyphs
    )

    font.reorderGlyphs(ga)

    new_coverage1 = list(
        font["GSUB"].table.LookupList.Lookup[0].SubTable[0].Coverage[0].glyphs
    )
    new_coverage2 = list(
        font["GPOS"].table.LookupList.Lookup[0].SubTable[0].Coverage.glyphs
    )

    assert list(reversed(old_coverage1)) == new_coverage1
    assert list(reversed(old_coverage2)) == new_coverage2


def test_reorder_glyphs_cff():
    font_path = DATA_DIR / "TestVGID-Regular.otf"
    font = TTFont(str(font_path))
    ga = font.getGlyphOrder()
    ga = list(reversed(ga))
    reorderGlyphs(font, ga)

    assert list(font["CFF "].cff.topDictIndex[0].CharStrings.charStrings.keys()) == ga
    assert font["CFF "].cff.topDictIndex[0].charset == ga


# ---------------------------------------------------------------------------
# CFF/CFF2 fonts with multiple FontDicts: the FDSelect table, the CharStrings
# INDEX and the charset are all parallel to the glyph order and must stay in
# sync when glyphs are reordered.
# ---------------------------------------------------------------------------

CFF_GLYPH_ORDER = [".notdef", "A", "B", "C", "D", "E"]
# Glyph -> FontDict assignment; the two FDs use different Private DICT width
# parameters, so a wrong FD assignment also changes the decoded width.
CFF_FD_SELECT = [0, 0, 1, 1, 0, 1]


def _build_multi_fd_cff2():
    """Build an in-memory multi-FD CFF2 font with unique outlines and widths."""
    from fontTools.cffLib import FDSelect
    from fontTools.pens.t2CharStringPen import T2CharStringPen

    fb = FontBuilder(1000, isTTF=False)
    fb.setupGlyphOrder(CFF_GLYPH_ORDER)
    fb.setupCharacterMap({})
    charStrings = {}
    for i, glyphName in enumerate(CFF_GLYPH_ORDER):
        pen = T2CharStringPen(None, None, CFF2=True)
        # A box whose edges embed the glyph index, making every outline unique.
        pen.moveTo((0, 0))
        pen.lineTo((50 + i, 0))
        pen.lineTo((50 + i, 60 + i * 10))
        pen.lineTo((0, 60 + i * 10))
        pen.closePath()
        charStrings[glyphName] = pen.getCharString()
    fb.setupCFF2(
        charStrings,
        fdArrayList=[
            {"defaultWidthX": 500, "nominalWidthX": 0},
            {"defaultWidthX": 777, "nominalWidthX": 100},
        ],
    )
    topDict = fb.font["CFF2"].cff[0]
    topDict.FDSelect = FDSelect()
    topDict.FDSelect.format = 0
    topDict.FDSelect.gidArray = list(CFF_FD_SELECT)
    # An in-memory CFF2 font has no fontNames until it is read from XML; set
    # the same default the XML reader uses so saveXML works.
    fb.font["CFF2"].cff.fontNames = ["CFF2Font"]
    fb.setupHorizontalMetrics(
        {glyphName: (100 + i * 50, 0) for i, glyphName in enumerate(CFF_GLYPH_ORDER)}
    )
    fb.setupHorizontalHeader()
    fb.setupNameTable({"familyName": "MultiFD", "styleName": "Regular"})
    fb.setupOS2()
    fb.setupPost()
    return fb.font


def _multi_fd_cff_font():
    """A binary, CID-keyed, multi-FD CFF font.

    The font is saved and reloaded once so its glyph names are the stable
    CID names (``cidNNNNN``) that every subsequent binary round-trip keeps.
    """
    from fontTools.cffLib.CFF2ToCFF import convertCFF2ToCFF

    font = _build_multi_fd_cff2()
    # The supported CFF2 -> CFF construction route goes through binary.
    buf = BytesIO()
    font.save(buf)
    buf.seek(0)
    font = TTFont(buf, recalcBBoxes=False)
    convertCFF2ToCFF(font)
    font["CFF "].cff.fontNames = ["MultiFD-Regular"]
    return _save_and_reload(font)


def _record_glyph_state(font, tag):
    """Capture per-glyph (outline, width, FD index), keyed by glyph name."""
    from fontTools.pens.recordingPen import RecordingPen

    top_dict = font[tag].cff.topDictIndex[0]
    glyph_set = font.getGlyphSet()
    state = {}
    for name in font.getGlyphOrder():
        pen = RecordingPen()
        glyph = glyph_set[name]
        glyph.draw(pen)
        if hasattr(top_dict, "FDSelect") and len(top_dict.FDSelect):
            # Binary-read font: FDSelect is a populated gid -> FD array.
            fd_index = top_dict.FDSelect[font.getGlyphID(name)]
        elif hasattr(top_dict, "FDArray"):
            # XML-read font: the FD assignment lives on each charstring and
            # the FDSelect array is rebuilt at compile time.
            fd_index = top_dict.CharStrings.charStrings[name].fdSelectIndex
        else:
            fd_index = None
        state[name] = (tuple(pen.value), glyph.width, fd_index)
    return state


def _assert_glyph_state_preserved(font, tag, old_state_by_name):
    """Every glyph name still has the outline/width/FD it had before.

    Reordering never changes the set of glyph names, so this is valid both in
    memory and after a save/reload, including for CID fonts whose names are
    only synthesized on the first binary write.
    """
    current = _record_glyph_state(font, tag)
    assert set(current) == set(old_state_by_name)
    for name, old in old_state_by_name.items():
        assert current[name] == old


def _save_and_reload(font):
    buf = BytesIO()
    font.save(buf)
    buf.seek(0)
    return TTFont(buf)


@pytest.mark.parametrize("lazy", [True, False, None])
@pytest.mark.parametrize("tag", ["CFF ", "CFF2"])
def test_reorder_multi_fd_preserves_outline_width_and_fd(lazy, tag):
    if tag == "CFF ":
        font = _multi_fd_cff_font()
        buf = BytesIO()
        font.save(buf)
        font = TTFont(BytesIO(buf.getvalue()), lazy=lazy)
    else:
        font = _build_multi_fd_cff2()
        buf = BytesIO()
        font.save(buf)
        font = TTFont(BytesIO(buf.getvalue()), lazy=lazy)

    before = _record_glyph_state(font, tag)
    order = font.getGlyphOrder()
    new_order = [order[0]] + list(reversed(order[1:]))

    reorderGlyphs(font, new_order)

    # The in-memory font must already report the right data, not only the file
    # written to disk (lazy INDEX slots used to be read through stale offsets).
    _assert_glyph_state_preserved(font, tag, before)

    reloaded = _save_and_reload(font)
    assert reloaded.getGlyphOrder() == new_order
    _assert_glyph_state_preserved(reloaded, tag, before)
    # Every glyph keeps the FontDict it started with.
    reloaded_top = reloaded[tag].cff.topDictIndex[0]
    for name in new_order:
        gid = reloaded.getGlyphID(name)
        assert reloaded_top.FDSelect[gid] == before[name][2]


def test_reorder_multi_fd_keeps_fdselect_in_sync():
    font = _multi_fd_cff_font()
    top_dict = font["CFF "].cff.topDictIndex[0]
    order = font.getGlyphOrder()
    assert [top_dict.FDSelect[font.getGlyphID(name)] for name in order] == CFF_FD_SELECT

    new_order = [order[0]] + list(reversed(order[1:]))
    old_fd_by_name = {
        name: top_dict.FDSelect[font.getGlyphID(name)] for name in order
    }
    reorderGlyphs(font, new_order)

    expected_gid_array = [old_fd_by_name[name] for name in new_order]
    assert top_dict.FDSelect.gidArray == expected_gid_array
    reloaded = _save_and_reload(font)
    assert reloaded["CFF "].cff.topDictIndex[0].FDSelect.gidArray == expected_gid_array
    # And the reloaded, possibly CID-renamed, font still maps each surviving
    # glyph name to its original FontDict.
    reloaded_top = reloaded["CFF "].cff.topDictIndex[0]
    for new_gid, name in enumerate(new_order):
        assert reloaded_top.FDSelect[new_gid] == old_fd_by_name[name]


def test_reorder_multi_fd_partial_leaves_untouched_glyphs_alone():
    font = _multi_fd_cff_font()
    before = _record_glyph_state(font, "CFF ")
    order = font.getGlyphOrder()
    moved = {order[2], order[4]}
    # Swap only two glyphs that belong to different FontDicts.
    new_order = list(order)
    new_order[2], new_order[4] = new_order[4], new_order[2]

    reorderGlyphs(font, new_order)
    reloaded = _save_and_reload(font)

    _assert_glyph_state_preserved(reloaded, "CFF ", before)
    top_dict = reloaded["CFF "].cff.topDictIndex[0]
    for old_gid, name in enumerate(order):
        if name not in moved:
            assert reloaded.getGlyphID(name) == old_gid
            assert top_dict.FDSelect[old_gid] == before[name][2]


def test_reorder_multi_fd_shared_private_dict():
    # Two FontDicts that point at the same Private dict object: FD membership
    # is tracked independently and must still follow each glyph.
    font = _multi_fd_cff_font()
    top_dict = font["CFF "].cff.topDictIndex[0]
    top_dict.FDArray[1].Private = top_dict.FDArray[0].Private
    before = _record_glyph_state(font, "CFF ")

    order = font.getGlyphOrder()
    reorderGlyphs(font, [order[0]] + list(reversed(order[1:])))
    reloaded = _save_and_reload(font)

    _assert_glyph_state_preserved(reloaded, "CFF ", before)


def test_reorder_multi_fd_cff_xml_roundtrip():
    # CFF dumps the FD assignment to the per-charstring fdSelectIndex and
    # rebuilds the FDSelect array from it on compile, so the full XML path can
    # be exercised (including the name-keyed, non-indexed CharStrings form).
    tag = "CFF "
    font = _multi_fd_cff_font()
    before = _record_glyph_state(font, tag)

    xml_buf = BytesIO()
    font.saveXML(xml_buf)
    xml_buf.seek(0)
    xml_font = TTFont(recalcBBoxes=False, recalcTimestamp=False)
    xml_font.importXML(xml_buf)
    top_dict = xml_font[tag].cff.topDictIndex[0]
    assert top_dict.CharStrings.charStringsAreIndexed == 0
    assert len(top_dict.FDSelect) == 0  # rebuilt lazily from the charstrings
    _assert_glyph_state_preserved(xml_font, tag, before)

    order = xml_font.getGlyphOrder()
    reorderGlyphs(xml_font, [order[0]] + list(reversed(order[1:])))

    # XML -> binary -> reload must not alter the outlines, widths or FDs.
    reloaded = _save_and_reload(xml_font)
    _assert_glyph_state_preserved(reloaded, tag, before)

    # XML -> XML must preserve them as well.
    xml2 = BytesIO()
    xml_font.saveXML(xml2)
    xml2.seek(0)
    xml_font2 = TTFont(recalcBBoxes=False, recalcTimestamp=False)
    xml_font2.importXML(xml2)
    _assert_glyph_state_preserved(xml_font2, tag, before)


def test_reorder_multi_fd_cff2_binary_roundtrip():
    # CFF2 binary round-trip.
    tag = "CFF2"
    font = _build_multi_fd_cff2()
    buf = BytesIO()
    font.save(buf)
    font = TTFont(BytesIO(buf.getvalue()))
    before = _record_glyph_state(font, tag)

    order = font.getGlyphOrder()
    reorderGlyphs(font, [order[0]] + list(reversed(order[1:])))
    reloaded = _save_and_reload(font)
    _assert_glyph_state_preserved(reloaded, tag, before)


def test_reorder_multi_fd_cff2_xml_roundtrip():
    # Round-trip through binary first so the FDSelect is wired onto the
    # CharStrings INDEX (a freshly built in-memory CFF2 font has not done that
    # yet); the XML dump then carries the per-charstring fdSelectIndex.
    tag = "CFF2"
    font = _build_multi_fd_cff2()
    bin_buf = BytesIO()
    font.save(bin_buf)
    font = TTFont(BytesIO(bin_buf.getvalue()))
    before = _record_glyph_state(font, tag)

    xml_buf = BytesIO()
    font.saveXML(xml_buf)
    xml_buf.seek(0)
    xml_font = TTFont(recalcBBoxes=False, recalcTimestamp=False)
    xml_font.importXML(xml_buf)
    top_dict = xml_font[tag].cff.topDictIndex[0]
    assert top_dict.CharStrings.charStringsAreIndexed == 0
    _assert_glyph_state_preserved(xml_font, tag, before)

    order = xml_font.getGlyphOrder()
    reorderGlyphs(xml_font, [order[0]] + list(reversed(order[1:])))
    reloaded = _save_and_reload(xml_font)
    _assert_glyph_state_preserved(reloaded, tag, before)


def test_reorder_multi_fd_bad_order_raises_before_touching_font():
    font = _multi_fd_cff_font()
    order = font.getGlyphOrder()
    original_fd_array = list(font["CFF "].cff.topDictIndex[0].FDSelect.gidArray)

    with pytest.raises(ValueError):
        reorderGlyphs(font, order[:3])
    with pytest.raises(ValueError):
        bad = list(order)
        bad[0] = "nonexistent"
        reorderGlyphs(font, bad)

    # The font is unchanged after the rejected reorders.
    assert font.getGlyphOrder() == order
    assert font["CFF "].cff.topDictIndex[0].FDSelect.gidArray == original_fd_array


def test_reorder_glyphs_bad_length(caplog):
    font_path = DATA_DIR / "Test-Regular.ttf"
    font = TTFont(str(font_path))
    with pytest.raises(ValueError) as ex:
        reorderGlyphs(font, ["A"])
    assert "New glyph order contains 1 glyphs" in str(ex.value)


def test_reorder_glyphs_bad_set(caplog):
    font_path = DATA_DIR / "Test-Regular.ttf"
    font = TTFont(str(font_path))
    ga = list(font.getGlyphOrder()) + ["AA"]
    ga.pop(1)
    with pytest.raises(ValueError) as ex:
        reorderGlyphs(font, ga)
    assert "New glyph order does not contain the same set of glyphs" in str(ex.value)


@pytest.mark.parametrize("lazy", [True, False, None])
@pytest.mark.parametrize("pairpos", [False, True])
def test_reorder_lazy_arrays(lazy, pairpos):
    from fontTools.misc.lazyTools import LazyList

    fb = FontBuilder(1000)
    order = [".notdef"] + [f"g{i}" for i in range(10)]
    fb.setupGlyphOrder(order)
    fb.setupPost()
    if pairpos:
        statements = [f"pos g0 g{i} {i + 1};" for i in range(10)]
    else:
        statements = [f"pos g{i} {i + 1};" for i in range(10)]
    addOpenTypeFeaturesFromString(
        fb.font, "feature kern { " + " ".join(statements) + " } kern;"
    )
    data = BytesIO()
    fb.font.save(data)
    font = TTFont(BytesIO(data.getvalue()), lazy=lazy)
    subtable = font["GPOS"].table.LookupList.Lookup[0].SubTable[0]
    records = subtable.PairSet[0].PairValueRecord if pairpos else subtable.Value
    assert isinstance(records, LazyList) == bool(lazy)
    reorderGlyphs(font, order[:1] + list(reversed(order[1:])))
    output = BytesIO()
    font.save(output)
    font = TTFont(BytesIO(output.getvalue()))
    subtable = font["GPOS"].table.LookupList.Lookup[0].SubTable[0]
    if pairpos:
        assert subtable.Coverage.glyphs == ["g0"]
        pairs = subtable.PairSet[0].PairValueRecord
        assert [record.SecondGlyph for record in pairs] == list(reversed(order[1:]))
        assert {
            (first, record.SecondGlyph): record.Value1.XAdvance
            for first, pair_set in zip(subtable.Coverage.glyphs, subtable.PairSet)
            for record in pair_set.PairValueRecord
        } == {("g0", f"g{i}"): i + 1 for i in range(10)}
    else:
        assert subtable.Coverage.glyphs == list(reversed(order[1:]))
        assert [v.XAdvance for v in subtable.Value] == list(reversed(range(1, 11)))
