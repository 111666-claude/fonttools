import logging

from fontTools.misc import psCharStrings
from fontTools import ttLib
from fontTools.pens.basePen import NullPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.misc.roundTools import otRound
from fontTools.misc.loggingTools import deprecateFunction
from fontTools.subset.util import _add_method, _uniq_sort

log = logging.getLogger("fontTools.subset")


def _decodeSeacCode(code):
    """Return the integer StandardEncoding code, or None if it is invalid."""
    if isinstance(code, int):
        return code
    if isinstance(code, float) and code.is_integer():
        return int(code)
    return None


def _decodeSeacArgs(args):
    """Decode the four operands of the deprecated 'endchar' seac form.

    Returns a tuple ``(adx, ady, baseGlyph, accentGlyph)``, or None if the
    character codes are not integers in the range of the StandardEncoding.
    """
    adx, ady, bchar, achar = args[-4:]
    bchar = _decodeSeacCode(bchar)
    achar = _decodeSeacCode(achar)
    if (
        bchar is None
        or achar is None
        or not (0 <= bchar < 256)
        or not (0 <= achar < 256)
    ):
        return None
    from fontTools.encodings.StandardEncoding import StandardEncoding

    baseGlyph = StandardEncoding[bchar]
    accentGlyph = StandardEncoding[achar]
    return adx, ady, baseGlyph, accentGlyph


def _isMappedSeacCode(seac):
    """Whether the character codes of a decoded seac form designate glyphs."""
    # The StandardEncoding table has '.notdef' for codes it does not map.
    return seac[2] != ".notdef" and seac[3] != ".notdef"


class _SeacArgsT2Decompiler(psCharStrings.T2WidthExtractor):
    """Records the width and the operands of the deprecated seac 'endchar'."""

    def reset(self):
        psCharStrings.T2WidthExtractor.reset(self)
        self.seacArgs = None

    def op_endchar(self, index):
        args = self.popallWidth()
        if len(args) >= 4:
            # endchar can do seac accent building; The T2 spec says it's
            # deprecated, but some fonts still use it.
            self.seacArgs = tuple(args[-4:])


class _ClosureGlyphsT2Decompiler(psCharStrings.SimpleT2Decompiler):
    def __init__(self, components, localSubrs, globalSubrs, flattenSeac=False):
        psCharStrings.SimpleT2Decompiler.__init__(self, localSubrs, globalSubrs)
        self.components = components
        self.flattenSeac = flattenSeac

    def op_endchar(self, index):
        args = self.popall()
        if len(args) >= 4:
            if self.flattenSeac:
                # The flattener leaves seac forms with unusable character
                # codes untouched (and warns about them), so do not crash on
                # them here; still close over the ones it can resolve.
                seac = _decodeSeacArgs(args[-4:])
                if seac is None:
                    return
                baseGlyph, accentGlyph = seac[2], seac[3]
            else:
                from fontTools.encodings.StandardEncoding import StandardEncoding

                # endchar can do seac accent bulding; The T2 spec says it's
                # deprecated, but recent software that shall remain nameless
                # does output it.
                adx, ady, bchar, achar = args[-4:]
                baseGlyph = StandardEncoding[bchar]
                accentGlyph = StandardEncoding[achar]
            self.components.add(baseGlyph)
            self.components.add(accentGlyph)


class _SeacFlattenPen(T2CharStringPen):
    """A T2CharStringPen that decomposes components, refusing cycles.

    The component glyphs are drawn exactly as ``T2CharString.draw`` would,
    so that nested seac forms (including ones whose character codes map to
    '.notdef') produce the same outline as before flattening.
    """

    def __init__(self, width, glyphSet, activeGlyphs):
        super().__init__(width, glyphSet, roundTolerance=0)
        self._activeGlyphs = activeGlyphs

    def addComponent(self, glyphName, transformation):
        if glyphName in self._activeGlyphs:
            raise ValueError("component cycle through glyph %r" % glyphName)
        self._activeGlyphs.add(glyphName)
        try:
            super().addComponent(glyphName, transformation)
        finally:
            self._activeGlyphs.discard(glyphName)


def _flattenSeacGlyph(glyphSet, glyphName):
    """Inline the base and accent components of a CFF1 seac glyph.

    The glyph's own outline (if any) and its width are preserved, and the
    base and accent outlines are appended at their respective offsets. The
    component glyphs are only read, never modified, so they can be shared
    between several composites.

    Returns True if the glyph was rewritten, False if it does not use the
    seac form or if it cannot be flattened (in which case it is left
    untouched).
    """
    charString = glyphSet[glyphName]
    if charString.needsDecompilation():
        charString.decompile()

    private = charString.private
    if private is None:
        log.warning("Cannot flatten seac form of glyph %r: no Private DICT", glyphName)
        return False
    localSubrs = getattr(private, "Subrs", [])
    decompiler = _SeacArgsT2Decompiler(
        localSubrs,
        charString.globalSubrs,
        private.nominalWidthX,
        private.defaultWidthX,
        private,
    )
    decompiler.execute(charString)
    if decompiler.seacArgs is None:
        return False

    seac = _decodeSeacArgs(decompiler.seacArgs)
    if seac is None or not _isMappedSeacCode(seac):
        log.warning(
            "Cannot flatten seac form of glyph %r: character code(s) do not "
            "designate glyphs in the StandardEncoding",
            glyphName,
        )
        return False
    _, _, baseGlyph, accentGlyph = seac
    missing = [g for g in (baseGlyph, accentGlyph) if g not in glyphSet]
    if missing:
        log.warning(
            "Cannot flatten seac form of glyph %r: missing component glyph(s) %s",
            glyphName,
            ", ".join(repr(g) for g in missing),
        )
        return False

    if decompiler.width == private.defaultWidthX:
        penWidth = None
    else:
        penWidth = decompiler.width - private.nominalWidthX

    # Draw the glyph and its seac components (including any regular outlines
    # preceding the endchar, and subroutines used to build them) into a new,
    # plain charstring. This inlines the components' outlines and therefore
    # drops their hinting; the seac form itself has no place for it.
    pen = _SeacFlattenPen(None, glyphSet, {glyphName})
    try:
        charString.draw(pen)
    except (KeyError, IndexError, TypeError, ValueError) as e:
        # A component may itself contain an invalid seac form or reference a
        # missing glyph; leave this glyph untouched rather than aborting the
        # subsetting.
        log.warning("Cannot flatten seac form of glyph %r: %s", glyphName, e)
        return False

    newCharString = pen.getCharString(
        private=private, globalSubrs=charString.globalSubrs
    )
    if penWidth is not None:
        # Insert the width exactly as encoded in the original charstring;
        # T2CharStringPen would have rounded it.
        newCharString.program.insert(0, penWidth)
    if hasattr(charString, "fdSelectIndex"):
        newCharString.fdSelectIndex = charString.fdSelectIndex
    glyphSet[glyphName] = newCharString
    log.debug("Flattened seac glyph %r", glyphName)
    return True


@_add_method(ttLib.getTableClass("CFF "))
def closure_glyphs(self, s):
    cff = self.cff
    assert len(cff) == 1
    font = cff[cff.keys()[0]]
    glyphSet = font.CharStrings

    # The seac form is a CFF1 construct; CFF2 charstrings have no 'endchar'
    # operator at all.
    flattenSeac = getattr(s.options, "flatten_seac", False) and cff.major == 1

    decompose = s.glyphs
    while decompose:
        components = set()
        for g in decompose:
            if g not in glyphSet:
                continue
            if flattenSeac:
                # Do this before closing over the glyph, so that the base and
                # accent glyphs are only retained if they are needed otherwise.
                _flattenSeacGlyph(glyphSet, g)
            gl = glyphSet[g]

            subrs = getattr(gl.private, "Subrs", [])
            decompiler = _ClosureGlyphsT2Decompiler(
                components, subrs, gl.globalSubrs, flattenSeac=flattenSeac
            )
            decompiler.execute(gl)
        components -= s.glyphs
        s.glyphs.update(components)
        decompose = components


def _empty_charstring(font, glyphName, isCFF2, ignoreWidth=False):
    c, fdSelectIndex = font.CharStrings.getItemAndSelector(glyphName)
    if isCFF2 or ignoreWidth:
        # CFF2 charstrings have no widths nor 'endchar' operators
        c.setProgram([] if isCFF2 else ["endchar"])
    else:
        if hasattr(font, "FDArray") and font.FDArray is not None:
            private = font.FDArray[fdSelectIndex].Private
        else:
            private = font.Private
        dfltWdX = private.defaultWidthX
        nmnlWdX = private.nominalWidthX
        pen = NullPen()
        c.draw(pen)  # this will set the charstring's width
        if c.width != dfltWdX:
            c.program = [c.width - nmnlWdX, "endchar"]
        else:
            c.program = ["endchar"]


@_add_method(ttLib.getTableClass("CFF "))
def prune_pre_subset(self, font, options):
    cff = self.cff
    # CFF table must have one font only
    cff.fontNames = cff.fontNames[:1]

    if options.notdef_glyph and not options.notdef_outline:
        isCFF2 = cff.major > 1
        for fontname in cff.keys():
            font = cff[fontname]
            _empty_charstring(font, ".notdef", isCFF2=isCFF2)

    # Clear useless Encoding
    for fontname in cff.keys():
        font = cff[fontname]
        # https://github.com/fonttools/fonttools/issues/620
        font.Encoding = "StandardEncoding"

    return True  # bool(cff.fontNames)


@_add_method(ttLib.getTableClass("CFF "))
def subset_glyphs(self, s):
    cff = self.cff
    for fontname in cff.keys():
        font = cff[fontname]
        cs = font.CharStrings

        glyphs = s.glyphs.union(s.glyphs_emptied)

        # Load all glyphs
        for g in font.charset:
            if g not in glyphs:
                continue
            c, _ = cs.getItemAndSelector(g)

        if cs.charStringsAreIndexed:
            indices = [i for i, g in enumerate(font.charset) if g in glyphs]
            csi = cs.charStringsIndex
            csi.items = [csi.items[i] for i in indices]
            del csi.file, csi.offsets
            newCharStrings = {}
            for indicesIdx, charsetIdx in enumerate(indices):
                g = font.charset[charsetIdx]
                if g in cs.charStrings:
                    newCharStrings[g] = indicesIdx
            cs.charStrings = newCharStrings
        else:
            cs.charStrings = {g: v for g, v in cs.charStrings.items() if g in glyphs}
        if hasattr(font, "FDSelect"):
            sel = font.FDSelect
            sel.format = None
            # FDSelect may also map VARC-only glyphs beyond the CFF2 charset.
            sel.gidArray = [
                sel.gidArray[i]
                for i, g in enumerate(s.orig_glyph_order)
                if g in glyphs and i < len(sel.gidArray)
            ]
        font.charset = [g for g in font.charset if g in glyphs]
        font.numGlyphs = len(font.charset)

        if s.options.retain_gids:
            isCFF2 = cff.major > 1
            for g in s.glyphs_emptied:
                if g not in cs:
                    continue
                _empty_charstring(font, g, isCFF2=isCFF2, ignoreWidth=True)

    return True  # any(cff[fontname].numGlyphs for fontname in cff.keys())


@_add_method(ttLib.getTableClass("CFF "))
def prune_post_subset(self, ttfFont, options):
    cff = self.cff
    for fontname in cff.keys():
        font = cff[fontname]
        cs = font.CharStrings

        # Drop unused FontDictionaries
        if hasattr(font, "FDSelect"):
            sel = font.FDSelect
            indices = _uniq_sort(sel.gidArray)
            sel.gidArray = [indices.index(ss) for ss in sel.gidArray]
            arr = font.FDArray
            arr.items = [arr[i] for i in indices]
            del arr.file, arr.offsets

    # Desubroutinize if asked for
    if options.desubroutinize:
        cff.desubroutinize()

    # Drop hints if not needed
    if not options.hinting:
        self.remove_hints()
    elif not options.desubroutinize:
        self.remove_unused_subroutines()
    return True


@deprecateFunction(
    "use 'CFFFontSet.desubroutinize()' instead", category=DeprecationWarning
)
@_add_method(ttLib.getTableClass("CFF "))
def desubroutinize(self):
    self.cff.desubroutinize()


@deprecateFunction(
    "use 'CFFFontSet.remove_hints()' instead", category=DeprecationWarning
)
@_add_method(ttLib.getTableClass("CFF "))
def remove_hints(self):
    self.cff.remove_hints()


@deprecateFunction(
    "use 'CFFFontSet.remove_unused_subroutines' instead", category=DeprecationWarning
)
@_add_method(ttLib.getTableClass("CFF "))
def remove_unused_subroutines(self):
    self.cff.remove_unused_subroutines()
