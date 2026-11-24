import os
import sys

libdir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))), "Lib"
)
sys.path.insert(0, libdir)

from fontTools.cffLib import TopDict, PrivateDict, CharStrings, CFFFontSet
from fontTools.misc.psCharStrings import calcSubrBias
from fontTools.misc.testTools import parseXML, DataFilesHandler
from fontTools.ttLib import TTFont
import copy
import unittest
from io import BytesIO


class CffLibTest(DataFilesHandler):
    def test_topDict_recalcFontBBox(self):
        topDict = TopDict()
        topDict.CharStrings = CharStrings(None, None, None, PrivateDict(), None, None)
        topDict.CharStrings.fromXML(
            None,
            None,
            parseXML("""
            <CharString name=".notdef">
              endchar
            </CharString>
            <CharString name="foo"><!-- [100, -100, 300, 100] -->
              100 -100 rmoveto 200 hlineto 200 vlineto -200 hlineto endchar
            </CharString>
            <CharString name="bar"><!-- [0, 0, 200, 200] -->
              0 0 rmoveto 200 hlineto 200 vlineto -200 hlineto endchar
            </CharString>
            <CharString name="baz"><!-- [-55.1, -55.1, 55.1, 55.1] -->
              -55.1 -55.1 rmoveto 110.2 hlineto 110.2 vlineto -110.2 hlineto endchar
            </CharString>
        """),
        )

        topDict.recalcFontBBox()
        self.assertEqual(topDict.FontBBox, [-56, -100, 300, 200])

    def test_topDict_recalcFontBBox_empty(self):
        topDict = TopDict()
        topDict.CharStrings = CharStrings(None, None, None, PrivateDict(), None, None)
        topDict.CharStrings.fromXML(
            None,
            None,
            parseXML("""
            <CharString name=".notdef">
              endchar
            </CharString>
            <CharString name="space">
              123 endchar
            </CharString>
        """),
        )

        topDict.recalcFontBBox()
        self.assertEqual(topDict.FontBBox, [0, 0, 0, 0])

    def test_topDict_set_Encoding(self):
        ttx_path = self.getpath("TestOTF.ttx")
        font = TTFont(recalcBBoxes=False, recalcTimestamp=False)
        font.importXML(ttx_path)

        topDict = font["CFF "].cff[0]
        encoding = [".notdef"] * 256
        encoding[0x20] = "space"
        topDict.Encoding = encoding

        self.temp_dir()
        save_path = os.path.join(self.tempdir, "TestOTF.otf")
        font.save(save_path)

        font2 = TTFont(save_path)
        topDict2 = font2["CFF "].cff.topDictIndex[0]
        self.assertEqual(topDict2.Encoding[32], "space")

    def test_topDict_delattr(self):
        font = TTFont(
            self.getpath("LinLibertine_RBI.otf"),
            recalcBBoxes=False,
            recalcTimestamp=False,
        )
        topDict = font["CFF "].cff.topDictIndex[0]

        # not loaded from rawDict yet
        del topDict.Notice
        self.assertFalse(hasattr(topDict, "Notice"))

        # already loaded from rawDict
        self.assertEqual(topDict.FullName, "Linux Libertine O Bold Italic")
        del topDict.FullName
        self.assertFalse(hasattr(topDict, "FullName"))

        with self.assertRaises(AttributeError):
            del topDict.Notice

        private = topDict.Private
        del topDict.Private
        self.assertFalse(hasattr(topDict, "Private"))
        topDict.Private = private

        data = BytesIO()
        font.save(data)
        data.seek(0)
        topDict2 = TTFont(data)["CFF "].cff.topDictIndex[0]
        self.assertFalse(hasattr(topDict2, "Notice"))
        self.assertFalse(hasattr(topDict2, "FullName"))
        self.assertTrue(hasattr(topDict2, "FamilyName"))
        self.assertIsInstance(topDict2.Private, PrivateDict)

    def test_CFF_deepcopy(self):
        """Test that deepcopying a TTFont with a CFF table does not recurse
        infinitely."""
        ttx_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "varLib",
            "data",
            "master_ttx_interpolatable_otf",
            "TestFamily2-Master0.ttx",
        )
        font = TTFont(recalcBBoxes=False, recalcTimestamp=False)
        font.importXML(ttx_path)
        copy.deepcopy(font)

    def test_CFF2_VarStore_recompiled_after_mutation(self):
        """A VarStore changed after a save must be written out as changed."""
        ttx_path = self.getpath("TestSparseCFF2VF.ttx")
        font = TTFont(recalcBBoxes=False, recalcTimestamp=False)
        font.importXML(ttx_path)
        font.save(BytesIO())

        varStore = font["CFF2"].cff.topDictIndex[0].VarStore.otVarStore
        varStore.VarRegionList.Region[0].VarRegionAxis[0].PeakCoord = 0.5

        buf = BytesIO()
        font.save(buf)
        buf.seek(0)
        font2 = TTFont(buf)

        varStore2 = font2["CFF2"].cff.topDictIndex[0].VarStore.otVarStore
        self.assertEqual(
            varStore2.VarRegionList.Region[0].VarRegionAxis[0].PeakCoord, 0.5
        )

    def test_FDSelect_format_4(self):
        ttx_path = self.getpath("TestFDSelect4.ttx")
        font = TTFont(recalcBBoxes=False, recalcTimestamp=False)
        font.importXML(ttx_path)

        self.temp_dir()
        save_path = os.path.join(self.tempdir, "TestOTF.otf")
        font.save(save_path)

        font2 = TTFont(save_path)
        topDict2 = font2["CFF2"].cff.topDictIndex[0]
        self.assertEqual(topDict2.FDSelect.format, 4)
        self.assertEqual(topDict2.FDSelect.gidArray, [0, 0, 1])

    def test_unique_glyph_names(self):
        font_path = self.getpath("LinLibertine_RBI.otf")
        font = TTFont(font_path, recalcBBoxes=False, recalcTimestamp=False)

        glyphOrder = font.getGlyphOrder()
        self.assertEqual(len(glyphOrder), len(set(glyphOrder)))

        self.temp_dir()
        save_path = os.path.join(self.tempdir, "TestOTF.otf")
        font.save(save_path)

        font2 = TTFont(save_path)
        glyphOrder = font2.getGlyphOrder()
        self.assertEqual(len(glyphOrder), len(set(glyphOrder)))

    def test_reading_supplement_encoding(self):
        cff_path = self.getpath("TestSupplementEncoding.cff")
        topDict = None
        with open(cff_path, "rb") as fontfile:
            cff = CFFFontSet()
            cff.decompile(fontfile, None)
            topDict = cff[0]
            self.assertEqual(topDict.Encoding[9], "space")
            self.assertEqual(topDict.Encoding[32], "space")

    def test_non_ascii_font_name_round_trip(self):
        font = TTFont(self.getpath("LinLibertine_RBI.otf"))
        font["CFF "].cff.fontNames = ["Caf\u00e9Sans"]

        data = BytesIO()
        font.save(data)
        data.seek(0)

        self.assertEqual(TTFont(data)["CFF "].cff.fontNames, ["Caf\u00e9Sans"])


class CFFToCFF2Test(DataFilesHandler):
    def test_roundtrip_with_local_subrs(self):
        from fontTools.cffLib.CFFToCFF2 import convertCFFToCFF2
        from fontTools.cffLib.CFF2ToCFF import convertCFF2ToCFF
        from fontTools.pens.recordingPen import RecordingPen

        def drawGlyphs(font):
            glyphSet = font.getGlyphSet()
            result = []
            for glyphName in font.getGlyphOrder():
                pen = RecordingPen()
                glyphSet[glyphName].draw(pen)
                result.append((glyphSet[glyphName].width, pen.value))
            return result

        font = TTFont(self.getpath("CFFToCFF2-1.otf"))
        expected = drawGlyphs(font)
        convertCFFToCFF2(font)
        buf = BytesIO()
        font.save(buf)
        buf.seek(0)

        # Load the CFF2 font without touching the charstrings, so that the
        # local Subrs are still undecompiled when converting back to CFF.
        font = TTFont(buf, recalcBBoxes=False)
        convertCFF2ToCFF(font)
        buf = BytesIO()
        font.save(buf)
        buf.seek(0)

        font = TTFont(buf)
        self.assertEqual(drawGlyphs(font), expected)

    def test_conversion(self):
        font_path = self.getpath("CFFToCFF2-1.otf")
        font = TTFont(font_path)
        from fontTools.cffLib.CFFToCFF2 import convertCFFToCFF2

        convertCFFToCFF2(font)
        f = BytesIO()
        font.save(f)


def _makeCFF2Font(glyphOrder, fdSelect=None):
    from fontTools.fontBuilder import FontBuilder
    from fontTools.cffLib import FDSelect
    from fontTools.pens.t2CharStringPen import T2CharStringPen

    fb = FontBuilder(1000, isTTF=False)
    fb.setupGlyphOrder(glyphOrder)
    fb.setupCharacterMap({})
    charStrings = {}
    for i, glyphName in enumerate(glyphOrder):
        pen = T2CharStringPen(None, None, CFF2=True)
        pen.moveTo((0, 0))
        pen.lineTo((100 + i * 10, 0))
        pen.lineTo((0, 100))
        pen.closePath()
        charStrings[glyphName] = pen.getCharString()
    fdArrayList = None
    if fdSelect is not None:
        fdArrayList = [{} for _ in range(max(fdSelect) + 1)]
    fb.setupCFF2(charStrings, fdArrayList=fdArrayList)
    if fdSelect is not None:
        topDict = fb.font["CFF2"].cff[0]
        topDict.FDSelect = FDSelect()
        topDict.FDSelect.format = 0
        topDict.FDSelect.gidArray = fdSelect
    fb.setupHorizontalMetrics(
        {glyphName: (500 + i, 0) for i, glyphName in enumerate(glyphOrder)}
    )
    fb.setupHorizontalHeader()
    fb.setupNameTable({"familyName": "TestCFF2", "styleName": "Regular"})
    fb.setupOS2()
    fb.setupPost()
    buf = BytesIO()
    fb.font.save(buf)
    buf.seek(0)
    return TTFont(buf, recalcBBoxes=False)


def _drawGlyphs(font):
    from fontTools.pens.recordingPen import RecordingPen

    glyphSet = font.getGlyphSet()
    result = []
    for glyphName in font.getGlyphOrder():
        pen = RecordingPen()
        glyphSet[glyphName].draw(pen)
        result.append((glyphSet[glyphName].width, pen.value))
    return result


def _convertAndReload(font):
    from fontTools.cffLib.CFF2ToCFF import convertCFF2ToCFF

    convertCFF2ToCFF(font)
    buf = BytesIO()
    font.save(buf)
    buf.seek(0)
    return TTFont(buf)


def _drawCFFCharStrings(font, tag):
    """Draw every glyph straight from the CFF CharStrings, recording the
    resolved program and width; works without hmtx/glyphSet tables."""
    from fontTools.pens.recordingPen import RecordingPen

    cff = font[tag].cff
    charStrings = cff[0].CharStrings
    result = []
    for glyphName in font.getGlyphOrder():
        charString = charStrings[glyphName]
        pen = RecordingPen()
        charString.draw(pen)
        result.append((charString.width, pen.value))
    return result


def _makeSubrFont(
    numLocalSubrs=10,
    usedLocal=None,
    numGlobalSubrs=5,
    usedGlobal=None,
    fdSelect=None,
):
    """Build a CFF2 font whose glyphs call local and global subroutines.

    Subroutine programs are tiny relative linetos; some subroutines call
    other subroutines so nested calls are exercised too. ``usedLocal`` and
    ``usedGlobal`` are lists of (possibly sparse) old subroutine indices.
    """
    from fontTools.fontBuilder import FontBuilder
    from fontTools.cffLib import FDSelect, SubrsIndex
    from fontTools.misc.psCharStrings import T2CharString, calcSubrBias
    from fontTools.pens.t2CharStringPen import T2CharStringPen

    if usedLocal is None:
        usedLocal = [0, numLocalSubrs - 1]
    if usedGlobal is None:
        usedGlobal = list(range(numGlobalSubrs))

    glyphOrder = [".notdef", "A", "B"]
    fb = FontBuilder(1000, isTTF=False)
    fb.setupGlyphOrder(glyphOrder)
    fb.setupCharacterMap({})
    charStrings = {}
    for glyphName in glyphOrder:
        pen = T2CharStringPen(None, None, CFF2=True)
        pen.moveTo((0, 0))
        pen.lineTo((10, 0))
        pen.lineTo((0, 10))
        pen.closePath()
        charStrings[glyphName] = pen.getCharString()
    fdArrayList = [{} for _ in range(max(fdSelect) + 1)] if fdSelect else None
    fb.setupCFF2(charStrings, fdArrayList=fdArrayList)
    topDict = fb.font["CFF2"].cff[0]
    if fdSelect is not None:
        topDict.FDSelect = FDSelect()
        topDict.FDSelect.format = 0
        topDict.FDSelect.gidArray = fdSelect
    globalSubrs = fb.font["CFF2"].cff.GlobalSubrs
    privates = [fd.Private for fd in topDict.FDArray]

    localBias = calcSubrBias(range(numLocalSubrs))
    for fdIndex, private in enumerate(privates):
        subrs = SubrsIndex()
        for i in range(numLocalSubrs):
            if i == 1 and numLocalSubrs > 2:
                # Nested: subr 1 calls local subr 2.
                program = [2 - localBias, "callsubr", 1, 0, "rlineto", "return"]
            else:
                program = [i % 7 + 1, 0, "rlineto", "return"]
            subrs.append(
                T2CharString(program=program, private=private, globalSubrs=globalSubrs)
            )
        private.Subrs = subrs

    globalBias = calcSubrBias(range(numGlobalSubrs))
    for i in range(numGlobalSubrs):
        if i == 0 and numGlobalSubrs > 1:
            # Nested: global subr 0 calls global subr 1.
            program = [1 - globalBias, "callgsubr", 1, 0, "rlineto", "return"]
        else:
            program = [i % 5 + 1, 0, "rlineto", "return"]
        globalSubrs.append(
            T2CharString(program=program, private=None, globalSubrs=globalSubrs)
        )

    for glyphIndex, glyphName in enumerate(glyphOrder):
        charString = charStrings[glyphName]
        fdIndex = topDict.FDSelect.gidArray[glyphIndex] if fdSelect else 0
        private = topDict.FDArray[fdIndex].Private
        program = [0, 0, "rmoveto"]
        for oldIndex in usedLocal:
            program.extend([oldIndex - localBias, "callsubr"])
        for oldIndex in usedGlobal:
            program.extend([oldIndex - globalBias, "callgsubr"])
        program.append("endchar")
        charString.program = program
        charString.private = private
        charString.globalSubrs = globalSubrs

    buf = BytesIO()
    fb.font.save(buf)
    buf.seek(0)
    return TTFont(buf, recalcBBoxes=False)


def _reload(font):
    buf = BytesIO()
    font.save(buf)
    buf.seek(0)
    return TTFont(buf, recalcBBoxes=False)


class RemoveUnusedSubroutinesTest(unittest.TestCase):
    def _checkRoundTrip(self, font, numLocalExpected=None, numGlobalExpected=None):
        expected = _drawCFFCharStrings(font, "CFF2")
        cff = font["CFF2"].cff
        cff.remove_unused_subroutines()

        # The kept subroutines must be renumbered densely from zero and in
        # their original (ascending old index) order.
        for fd in cff[0].FDArray:
            subrs = getattr(fd.Private, "Subrs", None)
            if subrs is not None:
                self.assertEqual(len(subrs), len(set(range(len(subrs)))))
        if numLocalExpected is not None:
            for fd in cff[0].FDArray:
                self.assertEqual(len(fd.Private.Subrs), numLocalExpected)
        if numGlobalExpected is not None:
            self.assertEqual(len(cff.GlobalSubrs), numGlobalExpected)

        reloaded = _reload(font)
        self.assertEqual(_drawCFFCharStrings(reloaded, "CFF2"), expected)
        # The surviving local subroutines should be byte-for-byte the ones
        # that were used, in the same relative order.
        return reloaded

    def test_local_and_global_subrs_deduplicated_and_ordered(self):
        # Sparse, non-contiguous uses, including repeated calls.
        font = _makeSubrFont(
            numLocalSubrs=20,
            usedLocal=[17, 3, 3, 11],
            numGlobalSubrs=7,
            usedGlobal=[6, 2, 6],
        )
        expected = _drawCFFCharStrings(font, "CFF2")
        font["CFF2"].cff.remove_unused_subroutines()
        self.assertEqual(len(font["CFF2"].cff[0].FDArray[0].Private.Subrs), 3)
        self.assertEqual(len(font["CFF2"].cff.GlobalSubrs), 2)
        reloaded = _reload(font)
        self.assertEqual(_drawCFFCharStrings(reloaded, "CFF2"), expected)

    def test_sparse_indices_keep_original_order(self):
        # Old indices will be renumbered to 0..n-1 sorted by old index, so
        # subr 17 must remain the last kept subr, not the first one called.
        font = _makeSubrFont(numLocalSubrs=20, usedLocal=[17, 3, 11], numGlobalSubrs=1)
        cff = font["CFF2"].cff
        kept = []
        for i in (3, 11, 17):
            subr = cff[0].FDArray[0].Private.Subrs[i]
            subr.decompile()
            kept.append(subr.program)
        cff.remove_unused_subroutines()
        subrs = cff[0].FDArray[0].Private.Subrs
        for subr in subrs.items:
            subr.decompile()
        self.assertEqual([subr.program for subr in subrs.items], kept)

    def test_bias_change_after_removal(self):
        # Start with enough local subrs for a bias of 1131, keep only a few,
        # so the new bias becomes 107: calls must still resolve.
        numLocalSubrs = 1300
        usedLocal = [0, 1, 2, 700, 1299]
        font = _makeSubrFont(
            numLocalSubrs=numLocalSubrs,
            usedLocal=usedLocal,
            numGlobalSubrs=1300,
            usedGlobal=[1299, 0, 1, 500],
        )
        cff = font["CFF2"].cff
        oldBias = calcSubrBias(range(numLocalSubrs))
        self.assertEqual(oldBias, 1131)
        newBias = calcSubrBias(range(len(usedLocal)))
        self.assertEqual(newBias, 107)
        # The first glyph program stores the operand for old subr 0.
        charString = cff[0].CharStrings[".notdef"]
        charString.decompile()
        self.assertIn(0 - oldBias, charString.program)
        self._checkRoundTrip(font, numLocalExpected=5, numGlobalExpected=4)

    def test_fdarray_local_subrs_per_fontdict(self):
        font = _makeSubrFont(
            numLocalSubrs=12,
            usedLocal=[10, 4],
            numGlobalSubrs=3,
            usedGlobal=[2, 1],
            fdSelect=[0, 1, 1],
        )
        self._checkRoundTrip(font, numLocalExpected=2, numGlobalExpected=2)

    def test_nested_subroutine_calls_renumbered(self):
        # Glyph calls local subr 1, which in turn calls local subr 2; global
        # subr 0 calls global subr 1. All four survive the pruning, and the
        # nested calls must be renumbered to refer to the new positions.
        font = _makeSubrFont(
            numLocalSubrs=8,
            usedLocal=[1, 5],
            numGlobalSubrs=4,
            usedGlobal=[0, 3],
        )
        expected = _drawCFFCharStrings(font, "CFF2")
        font["CFF2"].cff.remove_unused_subroutines()
        cff = font["CFF2"].cff
        self.assertEqual(len(cff[0].FDArray[0].Private.Subrs), 3)
        self.assertEqual(len(cff.GlobalSubrs), 3)
        localBias = 107
        globalBias = 107
        # Old local subrs 1, 2, 5 become 0, 1, 2; subr 0 must still call 1.
        # (CFF2 drops the trailing "return" of subroutines on compile.)
        self.assertEqual(
            cff[0].FDArray[0].Private.Subrs[0].program,
            [1 - localBias, "callsubr", 1, 0, "rlineto"],
        )
        self.assertEqual(
            cff[0].FDArray[0].Private.Subrs[2].program,
            [5 % 7 + 1, 0, "rlineto"],
        )
        # Old global subrs 0, 1, 3 become 0, 1, 2; subr 0 must still call 1.
        self.assertEqual(
            cff.GlobalSubrs[0].program,
            [1 - globalBias, "callgsubr", 1, 0, "rlineto"],
        )
        reloaded = _reload(font)
        self.assertEqual(_drawCFFCharStrings(reloaded, "CFF2"), expected)

    def test_used_set_not_left_on_subrs(self):
        font = _makeSubrFont(numLocalSubrs=5, usedLocal=[1, 3], numGlobalSubrs=3)
        font["CFF2"].cff.remove_unused_subroutines()
        subrs = font["CFF2"].cff[0].FDArray[0].Private.Subrs
        self.assertFalse(hasattr(subrs, "_used"))
        self.assertFalse(hasattr(subrs, "_old_bias"))
        self.assertFalse(hasattr(subrs, "_new_bias"))


class CFF2ToCFFTest(unittest.TestCase):
    def test_single_fontdict_converts_to_name_keyed(self):
        glyphOrder = [".notdef", "A", "B"]
        font = _makeCFF2Font(glyphOrder)
        expected = _drawGlyphs(font)

        font = _convertAndReload(font)

        topDict = font["CFF "].cff[0]
        self.assertFalse(hasattr(topDict, "ROS"))
        self.assertFalse(hasattr(topDict, "FDArray"))
        self.assertFalse(hasattr(topDict, "FDSelect"))
        self.assertTrue(hasattr(topDict, "Private"))
        self.assertEqual(font.getGlyphOrder(), glyphOrder)
        self.assertEqual(_drawGlyphs(font), expected)

    def test_multiple_fontdicts_converts_to_cid_keyed(self):
        font = _makeCFF2Font([".notdef", "A", "B"], fdSelect=[0, 1, 1])
        expected = _drawGlyphs(font)

        font = _convertAndReload(font)

        topDict = font["CFF "].cff[0]
        self.assertEqual(topDict.ROS, ("Adobe", "Identity", 0))
        self.assertEqual(len(topDict.FDArray), 2)
        self.assertEqual(font.getGlyphOrder(), [".notdef", "cid00001", "cid00002"])
        self.assertEqual(_drawGlyphs(font), expected)


if __name__ == "__main__":
    sys.exit(unittest.main())
