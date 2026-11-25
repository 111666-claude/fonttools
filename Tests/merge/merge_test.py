import io
import itertools
from fontTools import ttLib
from fontTools.ttLib.tables._g_l_y_f import Glyph
from fontTools.fontBuilder import FontBuilder
from fontTools.merge import Merger, main as merge_main
from fontTools.otlLib.builder import buildMathTable
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


def _merge_and_recompile(fontfiles, options=None):
    merger = Merger(options)
    merged = merger.merge(fontfiles)
    buf = _compile(merged)
    return ttLib.TTFont(buf)


def _make_tt_font(family, codepoints, *, widths=None):
    glyphOrder = [".notdef"] + [chr(cp) for cp in codepoints]
    cmap = {cp: chr(cp) for cp in codepoints}
    glyphs = {gn: Glyph() for gn in glyphOrder}
    widths = widths or {}
    hmtx = {gn: (widths.get(gn, 500), 0) for gn in glyphOrder}

    fb = FontBuilder(unitsPerEm=1000, isTTF=True)
    fb.setupGlyphOrder(glyphOrder)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(hmtx)
    fb.setupHorizontalHeader()
    fb.setupNameTable({"familyName": family, "styleName": "Regular"})
    fb.setupOS2()
    fb.setupPost()
    return fb.font


def _make_cff_font(family, codepoints):
    from fontTools.fontBuilder import FontBuilder as FB
    from fontTools.pens.t2CharStringPen import T2CharStringPen

    glyphOrder = [".notdef"] + [chr(cp) for cp in codepoints]
    cmap = {cp: chr(cp) for cp in codepoints}
    fb = FB(unitsPerEm=1000, isTTF=False)
    fb.setupGlyphOrder(glyphOrder)
    fb.setupCharacterMap(cmap)

    def empty_charstring(width=500):
        pen = T2CharStringPen(width, None)
        return pen.getCharString()

    fb.setupCFF(
        psName=family + "-Regular",
        fontInfo={"FullName": family, "FamilyName": family, "Weight": "Regular"},
        charStringsDict={gn: empty_charstring() for gn in glyphOrder},
        privateDict={},
    )
    fb.setupHorizontalMetrics({gn: (500, 0) for gn in glyphOrder})
    fb.setupHorizontalHeader()
    fb.setupNameTable({"familyName": family, "styleName": "Regular"})
    fb.setupOS2()
    fb.setupPost()
    return fb.font


def _font_signature(font):
    """Serializable description used to compare two merged fonts."""
    buf = _compile(font)
    reopened = ttLib.TTFont(io.BytesIO(buf.getvalue()))
    return {
        "sfntVersion": reopened.sfntVersion,
        "glyphOrder": tuple(reopened.getGlyphOrder()),
        "cmap": tuple(sorted(reopened.getBestCmap().items())),
        "name4": reopened["name"].getDebugName(4),
        "tables": tuple(reopened.keys()),
        "hmtx": tuple(sorted(reopened["hmtx"].metrics.items())),
    }


class MergeFontObjectsTest(unittest.TestCase):
    """Merger.merge() must accept TTFont objects alongside paths/streams."""

    def setUp(self):
        self.fontA = _make_tt_font("FamA", [0x61, 0x62], widths={"a": 300})
        self.fontB = _make_tt_font("FamB", [0x63, 0x64], widths={"c": 700})
        self.fontCff = _make_cff_font("FamCff", [0x65])

    def _path_pair(self):
        # Write the in-memory fonts to disk without mutating the objects, then
        # reopen fresh objects from those bytes for the path-based merge.
        dirpath = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, dirpath)
        paths = []
        for font in (self.fontA, self.fontB):
            path = os.path.join(dirpath, "font%d.ttf" % len(paths))
            font.save(path)
            paths.append(path)
        return paths

    def test_merge_ttfont_objects(self):
        merged = Merger().merge([self.fontA, self.fontB])

        self.assertEqual(
            merged.getGlyphOrder(),
            [".notdef", "a", "b", ".notdef.1", "c", "d"],
        )
        self.assertEqual(sorted(merged.getBestCmap().keys()), [0x61, 0x62, 0x63, 0x64])
        # Metrics from both fonts are retained.
        self.assertEqual(merged["hmtx"]["a"][0], 300)
        self.assertEqual(merged["hmtx"]["c"][0], 700)

    def test_path_and_object_merge_equivalent(self):
        pathA, pathB = self._path_pair()

        merged_from_paths = Merger().merge([pathA, pathB])
        merged_from_objects = Merger().merge([self.fontA, self.fontB])
        merged_mixed = Merger().merge([pathA, ttLib.TTFont(_compile(self.fontB))])

        signature = _font_signature(merged_from_paths)
        self.assertEqual(signature, _font_signature(merged_from_objects))
        self.assertEqual(signature, _font_signature(merged_mixed))

        # The merged fonts survive a binary round trip and reopen identically.
        for merged in (merged_from_paths, merged_from_objects, merged_mixed):
            buf = _compile(merged)
            reopened = ttLib.TTFont(io.BytesIO(buf.getvalue()))
            self.assertEqual(tuple(reopened.getGlyphOrder()), signature["glyphOrder"])
            self.assertEqual(
                tuple(sorted(reopened.getBestCmap().items())), signature["cmap"]
            )

    def test_unsaved_in_memory_changes_are_merged(self):
        self.fontA["name"].setName("InMemoryFamily", 1, 3, 1, 0x409)
        self.fontA["name"].setName("InMemoryFull", 4, 3, 1, 0x409)
        snapshot = self.fontA["name"].getDebugName(4)

        merged = Merger().merge([self.fontA, self.fontB])

        self.assertEqual(merged["name"].getDebugName(1), "InMemoryFamily")
        self.assertEqual(merged["name"].getDebugName(4), "InMemoryFull")
        # The caller's object still holds its unsaved state, untouched.
        self.assertEqual(self.fontA["name"].getDebugName(4), snapshot)

    def test_caller_objects_are_not_modified(self):
        orderA = list(self.fontA.getGlyphOrder())
        orderB = list(self.fontB.getGlyphOrder())
        tablesA = set(self.fontA.keys())
        headModifiedA = self.fontA["head"].modified

        Merger().merge([self.fontA, self.fontB])

        self.assertEqual(list(self.fontA.getGlyphOrder()), orderA)
        self.assertEqual(list(self.fontB.getGlyphOrder()), orderB)
        self.assertEqual(set(self.fontA.keys()), tablesA)
        # save() inside the merger must not recalc timestamps on the caller.
        self.assertEqual(self.fontA["head"].modified, headModifiedA)
        # The caller's font must remain fully usable and independently savable.
        buf = _compile(self.fontA)
        self.assertEqual(ttLib.TTFont(buf).getGlyphOrder(), orderA)

    def test_lazy_objects_keep_lazy_reader_and_stream(self):
        pathA, pathB = self._path_pair()
        lazyA = ttLib.TTFont(pathA, lazy=True)
        lazyB = ttLib.TTFont(pathB, lazy=True)
        self.addCleanup(lazyA.close)
        self.addCleanup(lazyB.close)

        merged = Merger().merge([lazyA, lazyB])
        _compile(merged)  # merged result is valid and saveable

        self.assertTrue(lazyA.lazy)
        self.assertIsNotNone(lazyA.reader)
        self.assertTrue(lazyB.lazy)
        self.assertIsNotNone(lazyB.reader)
        # Original glyph orders were never renamed in place.
        self.assertEqual(lazyA.getGlyphOrder(), [".notdef", "a", "b"])

    def test_merged_result_survives_caller_stream_closing(self):
        pathA, pathB = self._path_pair()
        fontA = ttLib.TTFont(pathA, lazy=True)
        fontB = ttLib.TTFont(pathB, lazy=True)

        merged = Merger().merge([fontA, fontB])
        fontA.close()
        fontB.close()

        # The merger holds no reference to the caller's input streams.
        buf = _compile(merged)
        reopened = ttLib.TTFont(io.BytesIO(buf.getvalue()))
        self.assertEqual(
            reopened.getGlyphOrder(),
            [".notdef", "a", "b", ".notdef.1", "c", "d"],
        )

    def test_shared_table_cache(self):
        pathA, pathB = self._path_pair()
        tableCache = {}
        fontA = ttLib.TTFont(pathA, lazy=True, _tableCache=tableCache)
        fontB = ttLib.TTFont(pathB, lazy=True, _tableCache=tableCache)

        merged = Merger().merge([fontA, fontB])
        _compile(merged)

        # The caller's shared cache is untouched.
        self.assertIs(fontA._tableCache, tableCache)
        self.assertIs(fontB._tableCache, tableCache)

    def test_same_object_passed_more_than_once(self):
        merged = Merger().merge([self.fontA, self.fontA])

        order = merged.getGlyphOrder()
        self.assertEqual(order, [".notdef", "a", "b", ".notdef.1", "a.1", "b.1"])
        # The binary output must contain every renamed glyph.
        buf = _compile(merged)
        reopened = ttLib.TTFont(io.BytesIO(buf.getvalue()))
        self.assertEqual(tuple(reopened.getGlyphOrder()), tuple(order))
        # Caller untouched.
        self.assertEqual(self.fontA.getGlyphOrder(), [".notdef", "a", "b"])

    def test_cff_objects(self):
        cff = self.fontCff
        order_before = cff.getGlyphOrder()

        merged = Merger().merge([cff, cff])

        self.assertEqual(merged.sfntVersion, "OTTO")
        self.assertIn("CFF ", merged)
        self.assertEqual(merged.getGlyphOrder(), [".notdef", "e", ".notdef.1", "e.1"])
        buf = _compile(merged)
        reopened = ttLib.TTFont(io.BytesIO(buf.getvalue()))
        self.assertEqual(reopened.sfntVersion, "OTTO")
        self.assertEqual(reopened.getGlyphOrder(), merged.getGlyphOrder())
        self.assertEqual(cff.getGlyphOrder(), order_before)

    def test_invalid_argument_is_locatable(self):
        with self.assertRaises(TypeError) as cm:
            Merger().merge([self.fontA, 12345])
        message = str(cm.exception)
        self.assertIn("fontfiles[1]", message)
        self.assertIn("int", message)

    def test_invalid_first_argument_is_locatable(self):
        with self.assertRaises(TypeError) as cm:
            Merger().merge([object()])
        self.assertIn("fontfiles[0]", str(cm.exception))

    def test_no_temporary_font_files(self):
        import builtins

        real_open = builtins.open
        real_mkstemp = tempfile.mkstemp
        real_mkdtemp = tempfile.mkdtemp

        def fail_open(file, mode="r", *args, **kwargs):
            if any(flag in mode for flag in ("w", "a", "x", "+")):
                raise AssertionError(
                    "merge() of TTFont objects must not write to the file system: %r"
                    % file
                )
            return real_open(file, mode, *args, **kwargs)

        def fail_mkstemp(*args, **kwargs):
            raise AssertionError("merge() must not create temporary files")

        def fail_mkdtemp(*args, **kwargs):
            raise AssertionError("merge() must not create temporary directories")

        builtins.open = fail_open
        tempfile.mkstemp = fail_mkstemp
        tempfile.mkdtemp = fail_mkdtemp
        try:
            merged = Merger().merge([self.fontA, self.fontB])
        finally:
            builtins.open = real_open
            tempfile.mkstemp = real_mkstemp
            tempfile.mkdtemp = real_mkdtemp

        self.assertEqual(
            merged.getGlyphOrder(),
            [".notdef", "a", "b", ".notdef.1", "c", "d"],
        )

    def test_pathlike_inputs_still_work(self):
        pathA, pathB = self._path_pair()
        merged = Merger().merge([pathlib.Path(pathA), pathlib.Path(pathB)])
        self.assertEqual(
            merged.getGlyphOrder(),
            [".notdef", "a", "b", ".notdef.1", "c", "d"],
        )


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


def _make_fontfile_with_MATH(glyphs, **kwargs):
    glyphOrder = [".notdef"] + glyphs
    fb = FontBuilder(unitsPerEm=1000)
    fb.setupGlyphOrder(glyphOrder)
    fb.setupCharacterMap({})
    fb.setupGlyf({gn: Glyph() for gn in glyphOrder})
    fb.setupHorizontalMetrics({gn: (500, 0) for gn in glyphOrder})
    fb.setupHorizontalHeader()
    fb.setupNameTable({"familyName": "TestMATH", "styleName": "Regular"})
    fb.setupOS2()
    fb.setupPost()
    if kwargs:
        buildMathTable(fb.font, **kwargs)
    return _compile(fb.font)


def test_merge_MATH():
    # https://github.com/fonttools/fonttools/issues/3823
    fontfiles = [
        _make_fontfile_with_MATH(
            ["a", "parenleft", "parenleft.size1"],
            constants={"AxisHeight": 250},
            italicsCorrections={"a": 10},
            mathKerns={"a": {"TopRight": ([100], [10, 20])}},
            minConnectorOverlap=20,
            vertGlyphVariants={
                "parenleft": [("parenleft", 700), ("parenleft.size1", 1000)]
            },
        ),
        _make_fontfile_with_MATH(
            ["b", "integral", "minus"],
            constants={"AxisHeight": 300},
            italicsCorrections={"b": 20},
            topAccentAttachments={"b": 250},
            extendedShapes={"integral"},
            minConnectorOverlap=30,
            horizGlyphVariants={"minus": [("minus", 500)]},
        ),
        _make_fontfile_with_MATH(["c"]),
    ]
    merged = _merge_and_recompile(fontfiles)

    table = merged["MATH"].table
    assert table.MathConstants.AxisHeight.Value == 250

    glyphInfo = table.MathGlyphInfo
    italics = glyphInfo.MathItalicsCorrectionInfo
    assert italics.Coverage.glyphs == ["a", "b"]
    assert [v.Value for v in italics.ItalicsCorrection] == [10, 20]
    topAccent = glyphInfo.MathTopAccentAttachment
    assert topAccent.TopAccentCoverage.glyphs == ["b"]
    assert [v.Value for v in topAccent.TopAccentAttachment] == [250]
    assert glyphInfo.ExtendedShapeCoverage.glyphs == ["integral"]
    assert glyphInfo.MathKernInfo.MathKernCoverage.glyphs == ["a"]
    assert len(glyphInfo.MathKernInfo.MathKernInfoRecords) == 1

    variants = table.MathVariants
    assert variants.MinConnectorOverlap == 20
    assert variants.VertGlyphCoverage.glyphs == ["parenleft"]
    assert [
        r.VariantGlyph for r in variants.VertGlyphConstruction[0].MathGlyphVariantRecord
    ] == ["parenleft", "parenleft.size1"]
    assert variants.HorizGlyphCoverage.glyphs == ["minus"]
    assert [
        r.VariantGlyph
        for r in variants.HorizGlyphConstruction[0].MathGlyphVariantRecord
    ] == ["minus"]


if __name__ == "__main__":
    import sys

    sys.exit(unittest.main())
