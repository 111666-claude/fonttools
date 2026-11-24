"""Regression tests for CFF2 variation data across an XML (TTX) round trip.

Importing a variable CFF2 font from XML used to leave
``CharStrings.varStore`` unset because ``<VarStore>`` is serialized after
``<CharStrings>``. As a result ``getGlyphSet(location=...)`` silently drew
the default outlines at every axis position. These tests compare outlines
and metrics at fixed locations across the original font, the live
XML-rebuilt font, and a binary saved and reopened from it, and check that
malformed input identifies the offending glyph.
"""

import os
from io import BytesIO

import pytest

from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib import TTFont

I_OTF = os.path.join(os.path.dirname(__file__), "..", "ttLib", "data", "I.otf")


def _locations(font):
    axes = [
        (a.axisTag, a.minValue, a.defaultValue, a.maxValue) for a in font["fvar"].axes
    ]
    tags = [a[0] for a in axes]
    locs = [{}]
    for tag, lo, _default, hi in axes:
        locs.append({tag: lo})
        locs.append({tag: hi})
        locs.append({tag: (lo + hi) / 2})
    if len(tags) >= 2:
        locs.append({tags[0]: axes[0][1], tags[1]: axes[1][3]})
        locs.append({tags[0]: axes[0][3], tags[1]: axes[1][1]})
    return locs


def _snapshot(font, locations):
    result = {}
    for loc in locations:
        glyphSet = font.getGlyphSet(location=loc)
        for glyphName in font.getGlyphOrder():
            pen = RecordingPen()
            glyph = glyphSet[glyphName]
            glyph.draw(pen)
            result[(tuple(sorted(loc.items())), glyphName)] = (
                glyph.width,
                glyph.lsb,
                tuple(pen.value),
            )
    return result


def _xml_roundtrip(font):
    xml = BytesIO()
    font.saveXML(xml)
    xml.seek(0)
    rebuilt = TTFont()
    rebuilt.importXML(xml)
    return rebuilt


def _binary_roundtrip(font):
    data = BytesIO()
    font.save(data)
    data.seek(0)
    return TTFont(data)


def test_cff2_xml_import_wires_varstore():
    font = TTFont(I_OTF)
    rebuilt = _xml_roundtrip(font)
    topDict = rebuilt["CFF2"].cff.topDictIndex[0]
    assert topDict.CharStrings.varStore is topDict.VarStore
    for fontDict in topDict.FDArray:
        if hasattr(fontDict, "Private"):
            assert fontDict.Private.vstore is topDict.VarStore


@pytest.mark.parametrize("location", [{}, {"wght": 200}, {"wght": 1000}])
def test_cff2_glyphset_from_xml_matches_original(location):
    font = TTFont(I_OTF)
    expected = RecordingPen()
    font.getGlyphSet(location=location)["I"].draw(expected)

    rebuilt = _xml_roundtrip(TTFont(I_OTF))
    actual = RecordingPen()
    rebuilt.getGlyphSet(location=location)["I"].draw(actual)
    assert actual.value == expected.value


def test_cff2_xml_three_way_outlines_and_metrics():
    original = TTFont(I_OTF)
    locations = _locations(original)

    from_xml = _xml_roundtrip(TTFont(I_OTF))
    from_binary = _binary_roundtrip(from_xml)

    expected = _snapshot(original, locations)
    assert _snapshot(from_xml, locations) == expected
    assert _snapshot(from_binary, locations) == expected


def test_cff2_lazy_source_xml_roundtrip():
    lazy_font = TTFont(I_OTF, lazy=True, recalcBBoxes=False)
    rebuilt = _xml_roundtrip(lazy_font)
    reopened = _binary_roundtrip(rebuilt)

    location = {"wght": 900, "CNTR": 100}
    expected = RecordingPen()
    TTFont(I_OTF).getGlyphSet(location=location)["I"].draw(expected)

    for font in (rebuilt, reopened):
        pen = RecordingPen()
        font.getGlyphSet(location=location)["I"].draw(pen)
        assert pen.value == expected.value


def test_cff2_missing_optional_hvar_still_matches():
    original = TTFont(I_OTF, recalcBBoxes=False)
    if "HVAR" in original:
        del original["HVAR"]
    locations = [{}, {"wght": 200}, {"wght": 900}]

    from_xml = _xml_roundtrip(original)
    from_binary = _binary_roundtrip(from_xml)

    expected = _snapshot(original, locations)
    assert _snapshot(from_xml, locations) == expected
    assert _snapshot(from_binary, locations) == expected


def test_bad_fdselect_index_names_glyph():
    from fontTools.cffLib import CharStrings, PrivateDict
    from fontTools.misc.testTools import parseXML

    fdArray = [type("FD", (), {"Private": PrivateDict()})()]
    charStrings = CharStrings(None, None, [], None, None, fdArray, isCFF2=True)
    xml = '<CharString name="missingFD" fdSelectIndex="9">' "1 2 rmoveto</CharString>"
    with pytest.raises(Exception, match="missingFD"):
        charStrings.fromXML("CharStrings", {}, parseXML(xml))
