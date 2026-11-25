from fontTools.misc import sstruct
from fontTools.misc.textTools import safeEval
from . import DefaultTable

maxpFormat_0_5 = """
		>	# big endian
		tableVersion:           i
		numGlyphs:              H
"""

maxpFormat_1_0_add = """
		>	# big endian
		maxPoints:              H
		maxContours:            H
		maxCompositePoints:     H
		maxCompositeContours:   H
		maxZones:               H
		maxTwilightPoints:      H
		maxStorage:             H
		maxFunctionDefs:        H
		maxInstructionDefs:     H
		maxStackElements:       H
		maxSizeOfInstructions:  H
		maxComponentElements:   H
		maxComponentDepth:      H
"""


class table__m_a_x_p(DefaultTable.DefaultTable):
    """Maximum Profile table

    The ``maxp`` table contains the memory requirements for the data in
    the font.

    See also https://learn.microsoft.com/en-us/typography/opentype/spec/maxp
    """

    dependencies = ["glyf"]
    glyphTableTag = "glyf"
    metricsTableTag = "hmtx"
    numGlyphsSize = 2

    def decompile(self, data, ttFont):
        headerSize = 4 + self.numGlyphsSize
        self.tableVersion = int.from_bytes(data[:4], "big")
        self.numGlyphs = int.from_bytes(data[4:headerSize], "big")
        data = data[headerSize:]
        self.numGlyphs = int(self.numGlyphs)
        if self.tableVersion != 0x00005000:
            dummy, data = sstruct.unpack2(maxpFormat_1_0_add, data, self)
        assert len(data) == 0

    def compile(self, ttFont):
        if self.glyphTableTag in ttFont:
            if ttFont.isLoaded(self.glyphTableTag) and ttFont.recalcBBoxes:
                self.recalc(ttFont)
        else:
            pass  # CFF
        self.numGlyphs = len(ttFont.getGlyphOrder())
        if self.tableVersion != 0x00005000:
            self.tableVersion = 0x00010000
        data = self.tableVersion.to_bytes(4, "big")
        data += self.numGlyphs.to_bytes(self.numGlyphsSize, "big")
        if self.tableVersion == 0x00010000:
            data = data + sstruct.pack(maxpFormat_1_0_add, self)
        return data

    def recalc(self, ttFont):
        """Recalculate the font bounding box, and most other maxp values except
        for the TT instructions values. Also recalculate the value of bit 1
        of the flags field and the font bounding box of the 'head' table.
        """
        glyfTable = ttFont[self.glyphTableTag]
        # 'head' is required for a valid sfnt but a minimal/partial font may
        # omit it; the empty bitmap-only shell in particular has no bounds to
        # write back, so tolerate its absence rather than raising KeyError.
        headTable = ttFont["head"] if "head" in ttFont else None
        # numGlyphs is a font-wide count from the global glyph order. In a
        # bitmap-only OTB shell glyf.glyphs is intentionally empty even though
        # the order (and maxp.numGlyphs) still lists all bitmap glyphs.
        self.numGlyphs = len(ttFont.getGlyphOrder())
        INFINITY = 100000
        xMin = +INFINITY
        yMin = +INFINITY
        xMax = -INFINITY
        yMax = -INFINITY
        maxPoints = 0
        maxContours = 0
        maxCompositePoints = 0
        maxCompositeContours = 0
        maxComponentElements = 0
        maxComponentDepth = 0
        allXMinIsLsb = 1
        maxpValuesCache = {}
        # An empty glyf shell has no outline records to recalculate from;
        # leave the extents at their zero defaults below instead of indexing
        # the (empty) glyph mapping for every name in the global order.
        if getattr(glyfTable, "glyphs", None):
            # hmtx is only needed to compare side bearings while walking
            # actual outline glyphs; a shell need not contain it.
            hmtxTable = ttFont[self.metricsTableTag]
            for glyphName in ttFont.getGlyphOrder():
                g = glyfTable[glyphName]
                if g.numberOfContours:
                    if hmtxTable[glyphName][1] != g.xMin:
                        allXMinIsLsb = 0
                    xMin = min(xMin, g.xMin)
                    yMin = min(yMin, g.yMin)
                    xMax = max(xMax, g.xMax)
                    yMax = max(yMax, g.yMax)
                    if g.numberOfContours > 0:
                        nPoints, nContours = g.getMaxpValues()
                        maxPoints = max(maxPoints, nPoints)
                        maxContours = max(maxContours, nContours)
                    elif g.isComposite():
                        nPoints, nContours, componentDepth = g.getCompositeMaxpValues(
                            glyfTable, maxpValuesCache=maxpValuesCache
                        )
                        maxCompositePoints = max(maxCompositePoints, nPoints)
                        maxCompositeContours = max(maxCompositeContours, nContours)
                        maxComponentElements = max(
                            maxComponentElements, len(g.components)
                        )
                        maxComponentDepth = max(maxComponentDepth, componentDepth)
        if headTable is not None:
            if xMin == +INFINITY:
                headTable.xMin = 0
                headTable.yMin = 0
                headTable.xMax = 0
                headTable.yMax = 0
            else:
                headTable.xMin = xMin
                headTable.yMin = yMin
                headTable.xMax = xMax
                headTable.yMax = yMax
        self.maxPoints = maxPoints
        self.maxContours = maxContours
        self.maxCompositePoints = maxCompositePoints
        self.maxCompositeContours = maxCompositeContours
        self.maxComponentElements = maxComponentElements
        self.maxComponentDepth = maxComponentDepth
        if headTable is not None:
            if allXMinIsLsb:
                headTable.flags = headTable.flags | 0x2
            else:
                headTable.flags = headTable.flags & ~0x2

    def testrepr(self):
        items = sorted(self.__dict__.items())
        print(". . . . . . . . .")
        for combo in items:
            print("  %s: %s" % combo)
        print(". . . . . . . . .")

    def toXML(self, writer, ttFont):
        if self.tableVersion != 0x00005000:
            writer.comment("Most of this table will be recalculated by the compiler")
            writer.newline()
        names = {"tableVersion": None, "numGlyphs": None}
        if self.tableVersion != 0x00005000:
            formatstring, names_1_0, fixes = sstruct.getformat(maxpFormat_1_0_add)
            names = {**names, **names_1_0}
        for name in names:
            value = getattr(self, name)
            if name == "tableVersion":
                value = hex(value)
            writer.simpletag(name, value=value)
            writer.newline()

    def fromXML(self, name, attrs, content, ttFont):
        setattr(self, name, safeEval(attrs["value"]))
