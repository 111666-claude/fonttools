import io
import itertools
import struct
from fontTools import ttLib
from fontTools.ttLib.tables._g_l_y_f import Glyph
from fontTools.fontBuilder import FontBuilder
from fontTools.merge import Merger, main as merge_main
import difflib
import os
import re
import shutil
import sys
import tempfile
import unittest
import pathlib
import pytest


class MergeIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = None
        self.num_tempfiles = 0

    def tearDown(self):
        if self.tempdir:
            shutil.rmtree(self.tempdir)

    @staticmethod
    def getpath(testfile):
        path, _ = os.path.split(__file__)
        return os.path.join(path, "data", testfile)

    def temp_path(self, suffix):
        if not self.tempdir:
            self.tempdir = tempfile.mkdtemp()
        self.num_tempfiles += 1
        return os.path.join(self.tempdir, "tmp%d%s" % (self.num_tempfiles, suffix))

    IGNORED_LINES_RE = re.compile(
        "^(<ttFont |    <(checkSumAdjustment|created|modified) ).*"
    )

    def read_ttx(self, path):
        lines = []
        with open(path, "r", encoding="utf-8") as ttx:
            for line in ttx.readlines():
                # Elide lines with data that often change.
                if self.IGNORED_LINES_RE.match(line):
                    lines.append("\n")
                else:
                    lines.append(line.rstrip() + "\n")
        return lines

    def expect_ttx(self, font, expected_ttx, tables=None):
        path = self.temp_path(suffix=".ttx")
        font.saveXML(path, tables=tables)
        actual = self.read_ttx(path)
        expected = self.read_ttx(expected_ttx)
        if actual != expected:
            for line in difflib.unified_diff(
                expected, actual, fromfile=expected_ttx, tofile=path
            ):
                sys.stdout.write(line)
            self.fail("TTX output is different from expected")

    def compile_font(self, path, suffix):
        savepath = self.temp_path(suffix=suffix)
        font = ttLib.TTFont(recalcBBoxes=False, recalcTimestamp=False)
        font.importXML(path)
        font.save(savepath, reorderTables=None)
        return font, savepath

    # -----
    # Tests
    # -----

    def test_merge_cff(self):
        _, fontpath1 = self.compile_font(self.getpath("CFFFont1.ttx"), ".otf")
        _, fontpath2 = self.compile_font(self.getpath("CFFFont2.ttx"), ".otf")
        mergedpath = self.temp_path(".otf")
        merge_main([fontpath1, fontpath2, "--output-file=%s" % mergedpath])
        mergedfont = ttLib.TTFont(mergedpath)
        self.expect_ttx(mergedfont, self.getpath("CFFFont_expected.ttx"))


class gaspMergeUnitTest(unittest.TestCase):
    def setUp(self):
        self.merger = Merger()

        self.table1 = ttLib.newTable("gasp")
        self.table1.version = 1
        self.table1.gaspRange = {
            0x8: 0xA,
            0x10: 0x5,
        }

        self.table2 = ttLib.newTable("gasp")
        self.table2.version = 1
        self.table2.gaspRange = {
            0x6: 0xB,
            0xFF: 0x4,
        }

        self.result = ttLib.newTable("gasp")

    def test_gasp_merge_basic(self):
        result = self.result.merge(self.merger, [self.table1, self.table2])
        self.assertEqual(result, self.table1)

        result = self.result.merge(self.merger, [self.table2, self.table1])
        self.assertEqual(result, self.table2)

    def test_gasp_merge_notImplemented(self):
        result = self.result.merge(self.merger, [NotImplemented, self.table1])
        self.assertEqual(result, NotImplemented)

        result = self.result.merge(self.merger, [self.table1, NotImplemented])
        self.assertEqual(result, self.table1)


class CmapMergeUnitTest(unittest.TestCase):
    def setUp(self):
        self.merger = Merger()
        self.table1 = ttLib.newTable("cmap")
        self.table2 = ttLib.newTable("cmap")
        self.mergedTable = ttLib.newTable("cmap")
        pass

    def tearDown(self):
        pass

    def makeSubtable(self, format, platformID, platEncID, cmap):
        module = ttLib.getTableModule("cmap")
        subtable = module.cmap_classes[format](format)
        subtable.platformID, subtable.platEncID, subtable.language, subtable.cmap = (
            platformID,
            platEncID,
            0,
            cmap,
        )
        return subtable

    def makeUvsSubtable(self, format, platformID, platEncID, uvsDict):
        subtable = self.makeSubtable(format, platformID, platEncID, {})
        subtable.uvsDict = uvsDict
        return subtable

    # 4-3-1 table merged with 12-3-10 table with no dupes with codepoints outside BMP
    def test_cmap_merge_no_dupes(self):
        table1 = self.table1
        table2 = self.table2
        mergedTable = self.mergedTable

        cmap1 = {0x2603: "SNOWMAN"}
        table1.tables = [self.makeSubtable(4, 3, 1, cmap1)]

        cmap2 = {0x26C4: "SNOWMAN WITHOUT SNOW"}
        cmap2Extended = {0x1F93C: "WRESTLERS"}
        cmap2Extended.update(cmap2)
        table2.tables = [
            self.makeSubtable(4, 3, 1, cmap2),
            self.makeSubtable(12, 3, 10, cmap2Extended),
        ]

        self.merger.alternateGlyphsPerFont = [{}, {}]
        mergedTable.merge(self.merger, [table1, table2])

        expectedCmap = cmap2.copy()
        expectedCmap.update(cmap1)
        expectedCmapExtended = cmap2Extended.copy()
        expectedCmapExtended.update(cmap1)
        self.assertEqual(mergedTable.numSubTables, 2)
        self.assertEqual(
            [
                (table.format, table.platformID, table.platEncID, table.language)
                for table in mergedTable.tables
            ],
            [(4, 3, 1, 0), (12, 3, 10, 0)],
        )
        self.assertEqual(mergedTable.tables[0].cmap, expectedCmap)
        self.assertEqual(mergedTable.tables[1].cmap, expectedCmapExtended)

    # Tests Issue #322
    def test_cmap_merge_three_dupes(self):
        table1 = self.table1
        table2 = self.table2
        mergedTable = self.mergedTable

        cmap1 = {0x20: "space#0", 0xA0: "space#0"}
        table1.tables = [self.makeSubtable(4, 3, 1, cmap1)]
        cmap2 = {0x20: "space#1", 0xA0: "uni00A0#1"}
        table2.tables = [self.makeSubtable(4, 3, 1, cmap2)]

        self.merger.duplicateGlyphsPerFont = [{}, {}]
        mergedTable.merge(self.merger, [table1, table2])

        expectedCmap = cmap1.copy()
        self.assertEqual(mergedTable.numSubTables, 1)
        table = mergedTable.tables[0]
        self.assertEqual(
            (table.format, table.platformID, table.platEncID, table.language),
            (4, 3, 1, 0),
        )
        self.assertEqual(table.cmap, expectedCmap)
        self.assertEqual(
            self.merger.duplicateGlyphsPerFont, [{}, {"space#0": "space#1"}]
        )

    def test_cmap_merge_format_14(self):
        table1 = self.table1
        table2 = self.table2
        mergedTable = self.mergedTable

        cmap1 = {0x3404: "uni3404"}
        uvsDict1 = {0xFE00: [(0x0030, "uni0030.FE00")], 0xE0101: [(0x3404, "uni3404")]}
        table1.tables = [
            self.makeUvsSubtable(14, 0, 5, uvsDict1),
            self.makeSubtable(4, 3, 1, cmap1),
        ]
        uvsDict2 = {0xFE00: [(0x20122, "u2F803")], 0xE0102: [(0x34FF, "uni34FF.var2")]}
        table2.tables = [self.makeUvsSubtable(14, 0, 5, uvsDict2)]

        self.merger.duplicateGlyphsPerFont = [{}, {}]
        mergedTable.merge(self.merger, [table1, table2])

        self.assertEqual(mergedTable.numSubTables, 2)
        uvsTable, cmapTable = mergedTable.tables

        self.assertEqual(
            (
                uvsTable.format,
                uvsTable.platformID,
                uvsTable.platEncID,
                uvsTable.language,
            ),
            (14, 0, 5, 0),
        )
        self.assertEqual(
            (
                cmapTable.format,
                cmapTable.platformID,
                cmapTable.platEncID,
                cmapTable.language,
            ),
            (4, 3, 1, 0),
        )

        expectedUvsDict = {
            0xFE00: [(0x0030, "uni0030.FE00"), (0x20122, "u2F803")],
            0xE0101: [(0x3404, None)],
            0xE0102: [(0x34FF, "uni34FF.var2")],
        }
        self.assertEqual(uvsTable.uvsDict, expectedUvsDict)

    def test_cmap_merge_format_14_dupes(self):
        table1 = self.table1
        table2 = self.table2
        mergedTable = self.mergedTable

        cmap1 = {0x2F803: "u2F803#0"}
        uvsDict1 = {0xFE00: [(0x20122, "u2F803#0")], 0xE0101: [(0x3404, "uni3404")]}
        table1.tables = [
            self.makeUvsSubtable(14, 0, 5, uvsDict1),
            self.makeSubtable(12, 3, 10, cmap1),
        ]
        cmap2 = {0x2F803: "u2F803#1"}
        uvsDict2 = {
            0xFE00: [(0x20122, "u2F803#1")],
            0xE0102: [(0x34FF, "uni34FF.var2")],
        }
        table2.tables = [
            self.makeUvsSubtable(14, 0, 5, uvsDict2),
            self.makeSubtable(12, 3, 10, cmap2),
        ]

        self.merger.duplicateGlyphsPerFont = [{}, {}]
        mergedTable.merge(self.merger, [table1, table2])

        self.assertEqual(mergedTable.numSubTables, 3)
        uvsTable, cmap_4_3_1_Table, cmap_12_3_10_Table = mergedTable.tables

        self.assertEqual(
            (
                uvsTable.format,
                uvsTable.platformID,
                uvsTable.platEncID,
                uvsTable.language,
            ),
            (14, 0, 5, 0),
        )
        self.assertEqual(
            (
                cmap_4_3_1_Table.format,
                cmap_4_3_1_Table.platformID,
                cmap_4_3_1_Table.platEncID,
                cmap_4_3_1_Table.language,
            ),
            (4, 3, 1, 0),
        )
        self.assertEqual(
            (
                cmap_12_3_10_Table.format,
                cmap_12_3_10_Table.platformID,
                cmap_12_3_10_Table.platEncID,
                cmap_12_3_10_Table.language,
            ),
            (12, 3, 10, 0),
        )

        expectedUvsDict = {
            0xFE00: [(0x20122, "u2F803#0")],
            0xE0101: [(0x3404, "uni3404")],
            0xE0102: [(0x34FF, "uni34FF.var2")],
        }
        self.assertEqual(uvsTable.uvsDict, expectedUvsDict)
        self.assertEqual(
            self.merger.duplicateGlyphsPerFont, [{}, {"u2F803#0": "u2F803#1"}]
        )


def _compile(ttFont):
    buf = io.BytesIO()
    ttFont.save(buf)
    buf.seek(0)
    return buf


def _make_fontfile_with_OS2(*, version, **kwargs):
    upem = 1000
    glyphOrder = [".notdef", "a"]
    cmap = {0x61: "a"}
    glyphs = {gn: Glyph() for gn in glyphOrder}
    hmtx = {gn: (500, 0) for gn in glyphOrder}
    names = {"familyName": "TestOS2", "styleName": "Regular"}

    fb = FontBuilder(unitsPerEm=upem)
    fb.setupGlyphOrder(glyphOrder)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(hmtx)
    fb.setupHorizontalHeader()
    fb.setupNameTable(names)
    fb.setupOS2(version=version, **kwargs)

    return _compile(fb.font)


def _make_fontfile_with_glyphs(first_gid, glyph_count):
    upem = 1000
    glyphOrder = [".notdef"] + [
        f"glyph{gid:05d}" for gid in range(first_gid, first_gid + glyph_count - 1)
    ]
    cmap = {
        first_gid + codepoint: glyphName
        for codepoint, glyphName in enumerate(glyphOrder[1:])
    }
    glyphs = {gn: Glyph() for gn in glyphOrder}
    hmtx = {gn: (500, 0) for gn in glyphOrder}
    names = {"familyName": "TestMerge", "styleName": "Regular"}

    fb = FontBuilder(unitsPerEm=upem)
    fb.setupGlyphOrder(glyphOrder)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(hmtx)
    fb.setupHorizontalHeader()
    fb.setupNameTable(names)
    fb.setupOS2()

    return _compile(fb.font)


def _merge_and_recompile(fontfiles, options=None):
    merger = Merger(options)
    merged = merger.merge(fontfiles)
    buf = _compile(merged)
    return ttLib.TTFont(buf)


def _make_cmap_overflow_font(
    first_gid, start, count, *, with_uvs=False, non_bmp=False, extra=False
):
    """Build a font mapping ``count`` consecutive BMP codepoints from ``start``
    alternately to two glyphs, so that a merged format 4 subtable needs one
    glyphIndexArray entry per codepoint.

    Two fonts built with different ``first_gid`` values contribute disjoint
    glyphs; merging them produces a BMP map that straddles format 4's 16-bit
    size limit. With ``with_uvs`` a default and a non-default variation
    sequence are added for the first two codepoints.

    Returns ``(fontfile, cmap, expected_uvs)``.
    """
    font = ttLib.TTFont(_make_fontfile_with_glyphs(first_gid, 3))
    font.ensureDecompiled()
    glyphs = font.getGlyphOrder()[1:]
    cmap = {start + i: glyphs[i % 2] for i in range(count)}
    if non_bmp:
        cmap[0x10000] = glyphs[0]
    if extra:
        cmap[start + count + 5] = glyphs[0]
    uvs = None
    expected_uvs = []
    if with_uvs:
        uvs = [(start, 0xFE0F, None), (start + 1, 0xFE0F, glyphs[0])]
        expected_uvs = [(start, None), (start + 1, glyphs[0])]
    fb = FontBuilder(font=font)
    fb.setupCharacterMap(cmap, uvs=uvs)
    fb.setupOS2()
    fb.setupPost()
    return _compile(font), cmap, expected_uvs


def _assert_cmap_and_uvs_roundtrip(merged, expected_cmap, expected_uvs, order=None):
    assert merged.getBestCmap() == expected_cmap
    uvs = merged["cmap"].getcmap(0, 5)
    if expected_uvs is None:
        assert uvs is None
    else:
        actual = {
            selector: dict(mappings) for selector, mappings in uvs.uvsDict.items()
        }
        assert actual == {0xFE0F: dict(expected_uvs)}
    if order is not None:
        assert [t.format for t in merged["cmap"].tables] == order


@pytest.mark.parametrize("reverse_order", [False, True])
@pytest.mark.parametrize(
    "non_bmp, extra_range",
    [(False, False), (True, False), (False, True)],
)
def test_merge_cmap_exceeding_format4_capacity(non_bmp, extra_range, reverse_order):
    # Two fonts of 20,000 BMP mappings each: the merged format 4 subtable
    # cannot be written, so the merger must fall back to format 12 while
    # keeping every mapping and the UVS subtable.
    fontfiles = []
    expected_cmap = {}
    expected_uvs = []
    for first_gid, start in [(0x20, 0x800), (0x40, 0x800 + 20000)]:
        font, cmap, uvs = _make_cmap_overflow_font(
            first_gid,
            start,
            20000,
            with_uvs=True,
            non_bmp=non_bmp and first_gid == 0x40,
            extra=extra_range and first_gid == 0x40,
        )
        fontfiles.append(font)
        expected_cmap.update(cmap)
        expected_uvs.extend(uvs)
    if reverse_order:
        fontfiles.reverse()

    merged = _merge_and_recompile(fontfiles)
    _assert_cmap_and_uvs_roundtrip(merged, expected_cmap, expected_uvs, order=[14, 12])
    assert merged["cmap"].getcmap(3, 1) is None


@pytest.mark.parametrize(
    "extra_entry, expected_formats",
    [
        # 32,750 BMP mappings compile to a format 4 subtable of 65,532 bytes.
        (False, [4]),
        # One more mapping pushes the subtable past 16 bits.
        (True, [12]),
    ],
)
def test_merge_cmap_format4_capacity_boundary(extra_entry, expected_formats):
    from fontTools.ttLib.tables._c_m_a_p import CmapSubtable

    count = 16375
    fontfiles = []
    expected_cmap = {}
    expected_uvs = []
    for first_gid, start in [(0x20, 0x800), (0x40, 0x800 + count)]:
        font, cmap, uvs = _make_cmap_overflow_font(
            first_gid,
            start,
            count,
            with_uvs=True,
            extra=extra_entry and first_gid == 0x40,
        )
        fontfiles.append(font)
        expected_cmap.update(cmap)
        expected_uvs.extend(uvs)

    merged = _merge_and_recompile(fontfiles)
    _assert_cmap_and_uvs_roundtrip(merged, expected_cmap, expected_uvs)
    assert [t.format for t in merged["cmap"].tables] == [14] + expected_formats

    # Confirm the boundary really is format 4's 16-bit length limit.
    would_be = CmapSubtable.newSubtable(4)
    would_be.platformID, would_be.platEncID, would_be.language = 3, 1, 0
    would_be.cmap = expected_cmap
    try:
        length = len(would_be.compile(merged))
    except (struct.error, OverflowError):
        length = None
    if expected_formats == [4]:
        assert length == 65532
    else:
        assert length is None


def test_merge_small_cmap_keeps_format4():
    fonts = []
    expected = {}
    for gid, base in [(0x20, 0x800), (0x40, 0x1000)]:
        font, cmap, uvs = _make_cmap_overflow_font(gid, base, 100)
        fonts.append(font)
        expected.update(cmap)
    merged = _merge_and_recompile(fonts)
    _assert_cmap_and_uvs_roundtrip(merged, expected, None, order=[4])


def test_merge_head_different_units_per_em():
    heads = []
    for units_per_em in (1000, 2048):
        head = ttLib.newTable("head")
        head.unitsPerEm = units_per_em
        heads.append(head)

    with pytest.raises(
        ValueError,
        match=r"Cannot merge fonts with different unitsPerEm values: \[1000, 2048\]",
    ):
        ttLib.newTable("head").merge(Merger(), heads)


@pytest.mark.parametrize("v1, v2", list(itertools.permutations(range(5 + 1), 2)))
def test_merge_OS2_mixed_versions(v1, v2):
    # https://github.com/fonttools/fonttools/issues/1865
    fontfiles = [
        _make_fontfile_with_OS2(version=v1),
        _make_fontfile_with_OS2(version=v2),
    ]
    merged = _merge_and_recompile(fontfiles)
    assert merged["OS/2"].version == max(v1, v2)


if __name__ == "__main__":
    import sys

    sys.exit(unittest.main())
