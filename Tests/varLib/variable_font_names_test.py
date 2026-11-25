"""Tests for the explicit family name of ``<variable-font>`` descriptors.

A single designspace can define several variable fonts; each of them can now
carry its own family name (with optional localisations) which is written to
the built font's ``name`` table instead of the family name inherited from
the default source.
"""

from fontTools.designspaceLib import (
    AxisDescriptor,
    DesignSpaceDocument,
    InstanceDescriptor,
    RangeAxisSubsetDescriptor,
    SourceDescriptor,
    ValueAxisSubsetDescriptor,
    VariableFontDescriptor,
)
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.varLib import build_many
from fontTools.varLib.instancer.names import NameID


def make_master(styleName="Regular"):
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder([".notdef", "a"])
    builder.setupCharacterMap({0x61: "a"})
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((300, 0))
    pen.lineTo((300, 700))
    pen.lineTo((0, 700))
    pen.closePath()
    glyph = pen.glyph()
    builder.setupGlyf({".notdef": glyph, "a": glyph})
    builder.setupHorizontalMetrics({".notdef": (300, 0), "a": (300, 0)})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "MasterFamily", "styleName": styleName})
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200)
    builder.setupPost()
    return builder.font


def make_designspace():
    doc = DesignSpaceDocument()
    doc.formatVersion = "5.0"
    doc.addAxis(
        AxisDescriptor(name="Weight", tag="wght", minimum=100, maximum=900, default=400)
    )
    doc.addAxis(
        AxisDescriptor(name="Width", tag="wdth", minimum=50, maximum=150, default=100)
    )
    # Masters on the 2-axis rectangle plus the default location; all VFs
    # share these same sources.
    for wght, wdth in [
        (100, 50),
        (900, 50),
        (100, 150),
        (900, 150),
        (400, 100),
    ]:
        source = SourceDescriptor()
        source.name = f"master_{wght}_{wdth}"
        source.font = make_master()
        source.familyName = "MasterFamily"
        source.styleName = "Regular"
        source.location = {"Weight": wght, "Width": wdth}
        doc.addSource(source)

    doc.addVariableFont(
        VariableFontDescriptor(
            name="FirstFamily_VF",
            familyName="First Family",
            axisSubsets=[
                RangeAxisSubsetDescriptor(name="Weight"),
                RangeAxisSubsetDescriptor(name="Width"),
            ],
        )
    )
    doc.addVariableFont(
        VariableFontDescriptor(
            name="SecondFamily_VF",
            familyName="Second Family",
            localisedFamilyName={
                "en": "Second Family",
                "fr": "Deuxième Famille",
            },
            axisSubsets=[
                RangeAxisSubsetDescriptor(name="Weight"),
                ValueAxisSubsetDescriptor(name="Width", userValue=100),
            ],
        )
    )
    return doc


def names(font, nameID):
    return {
        (record.platformID, record.platEncID, record.langID): record.toUnicode()
        for record in font["name"].names
        if record.nameID == nameID
    }


def test_build_many_applies_distinct_vf_family_names():
    fonts = build_many(make_designspace())

    assert set(fonts) == {"FirstFamily_VF", "SecondFamily_VF"}

    first = fonts["FirstFamily_VF"]
    # The default source's family name is replaced on both family name IDs.
    assert names(first, NameID.FAMILY_NAME) == {
        (1, 0, 0): "First Family",
        (3, 1, 0x409): "First Family",
    }
    assert names(first, NameID.TYPOGRAPHIC_FAMILY_NAME) == {
        (1, 0, 0): "First Family",
        (3, 1, 0x409): "First Family",
    }
    # Full name drops the elidable "Regular"; style name stays untouched.
    assert names(first, NameID.FULL_FONT_NAME) == {
        (1, 0, 0): "First Family",
        (3, 1, 0x409): "First Family",
    }
    assert names(first, NameID.SUBFAMILY_NAME) == {
        (1, 0, 0): "Regular",
        (3, 1, 0x409): "Regular",
    }
    # The two VFs do not cross-contaminate: the second one keeps its own name.
    second = fonts["SecondFamily_VF"]
    assert names(second, NameID.FAMILY_NAME)[(3, 1, 0x409)] == "Second Family"
    assert names(first, NameID.FAMILY_NAME)[(3, 1, 0x409)] == "First Family"


def test_build_many_writes_localised_vf_family_name():
    second = build_many(make_designspace())["SecondFamily_VF"]

    # The French translation is added as a new Windows name record (LCID 0x40c)
    # on the family and full-name IDs, without touching English.
    assert names(second, NameID.FAMILY_NAME)[(3, 1, 0x40C)] == "Deuxième Famille"
    assert names(second, NameID.TYPOGRAPHIC_FAMILY_NAME)[(3, 1, 0x40C)] == (
        "Deuxième Famille"
    )
    assert names(second, NameID.FULL_FONT_NAME)[(3, 1, 0x40C)] == ("Deuxième Famille")
    assert names(second, NameID.FAMILY_NAME)[(3, 1, 0x409)] == "Second Family"

    first = build_many(make_designspace())["FirstFamily_VF"]
    # A language only declared on the other VF descriptor must not appear.
    assert all(record.langID != 0x40C for record in first["name"].names)


def test_build_many_vf_default_instance_matches_family_name():
    fonts = build_many(make_designspace())
    for vf_name, font in fonts.items():
        fvar = font["fvar"]
        default_location = {axis.axisTag: axis.defaultValue for axis in fvar.axes}
        # The default location of the built font is the base master itself;
        # its family name is what the descriptor renamed.
        assert default_location["wght"] == 400
        if vf_name == "SecondFamily_VF":
            # The Width axis was frozen, so it is not an fvar axis anymore.
            assert "wdth" not in default_location
        else:
            assert default_location["wdth"] == 100


def test_build_many_without_vf_family_name_keeps_inherited_name():
    doc = make_designspace()
    doc.variableFonts[0].familyName = None
    doc.variableFonts[0].localisedFamilyName = {}

    first = build_many(doc)["FirstFamily_VF"]
    assert names(first, NameID.FAMILY_NAME) == {
        (1, 0, 0): "MasterFamily",
        (3, 1, 0x409): "MasterFamily",
    }


def test_build_many_rebuilds_postscript_and_full_name_when_present():
    doc = make_designspace()
    # Give the masters a rich name table including ID 6 and non-Regular style.
    for source in doc.sources:
        nameTable = source.font["name"]
        nameTable.setName(
            "MasterFamily-BoldItalic", NameID.POSTSCRIPT_NAME, 3, 1, 0x409
        )
        nameTable.setName("MasterFamily-BoldItalic", NameID.POSTSCRIPT_NAME, 1, 0, 0)
        nameTable.setName(
            "Master Family Bold Italic", NameID.FULL_FONT_NAME, 3, 1, 0x409
        )
        nameTable.setName("Master Family Bold Italic", NameID.FULL_FONT_NAME, 1, 0, 0)
        nameTable.setName("Bold Italic", NameID.SUBFAMILY_NAME, 3, 1, 0x409)
        nameTable.setName("Bold Italic", NameID.SUBFAMILY_NAME, 1, 0, 0)

    first = build_many(doc)["FirstFamily_VF"]
    assert names(first, NameID.POSTSCRIPT_NAME)[(3, 1, 0x409)] == (
        "FirstFamily-BoldItalic"
    )
    assert names(first, NameID.FULL_FONT_NAME)[(3, 1, 0x409)] == (
        "First Family Bold Italic"
    )
    # Style names are never overwritten by the family rename.
    assert names(first, NameID.SUBFAMILY_NAME)[(3, 1, 0x409)] == "Bold Italic"


def test_build_many_localised_only_family_name_leaves_english_inherited():
    # A descriptor with only localised <familyname> children (no English
    # attribute) renames just those languages; English keeps the master name.
    doc = make_designspace()
    vf = doc.variableFonts[0]
    vf.familyName = None
    vf.localisedFamilyName = {"fr": "Première Famille"}

    built = build_many(doc)["FirstFamily_VF"]
    assert names(built, NameID.FAMILY_NAME)[(3, 1, 0x40C)] == "Première Famille"
    assert names(built, NameID.FAMILY_NAME)[(3, 1, 0x409)] == "MasterFamily"
    assert names(built, NameID.FAMILY_NAME)[(1, 0, 0)] == "MasterFamily"


def test_build_many_matches_sublanguage_tags_and_avoids_duplicate_records():
    # A descriptor language tag more specific than the font's record tag
    # (de-DE vs. de) still matches through the language subtag, and the
    # rewrite must not emit duplicate name records.
    doc = make_designspace()
    for source in doc.sources:
        name_table = source.font["name"]
        name_table.setName("Meisterfamilie", NameID.FAMILY_NAME, 3, 1, 0x407)
        name_table.setName(
            "Meisterfamilie", NameID.TYPOGRAPHIC_FAMILY_NAME, 3, 1, 0x407
        )
    vf = doc.variableFonts[0]
    vf.familyName = "New Family"
    vf.localisedFamilyName = {"en": "New Family", "de-DE": "Neue Familie"}

    built = build_many(doc)["FirstFamily_VF"]
    assert names(built, NameID.FAMILY_NAME)[(3, 1, 0x407)] == "Neue Familie"
    assert names(built, NameID.FAMILY_NAME)[(3, 1, 0x409)] == "New Family"
    # Exactly one record per (platform, lang) pair for each family name ID.
    for name_id in (NameID.FAMILY_NAME, NameID.TYPOGRAPHIC_FAMILY_NAME):
        keys = [
            (r.platformID, r.platEncID, r.langID)
            for r in built["name"].names
            if r.nameID == name_id
        ]
        assert len(keys) == len(set(keys))


def test_build_many_keeps_instance_and_style_names_untouched():
    doc = make_designspace()
    instance = InstanceDescriptor()
    instance.name = "Light Instance"
    instance.styleName = "Light"
    instance.localisedStyleName = {"en": "Light", "fr": "Léger"}
    instance.location = {"Weight": 100, "Width": 100}
    doc.addInstance(instance)

    first, second = (
        build_many(doc)[name] for name in ("FirstFamily_VF", "SecondFamily_VF")
    )

    for font in (first, second):
        # The default subfamily (ID 2) inherited from the master is untouched.
        assert names(font, NameID.SUBFAMILY_NAME)[(3, 1, 0x409)] == "Regular"
        # The named fvar instance keeps its own style name and localisation,
        # stored on a dedicated name ID rather than the family records.
        (fvar_instance,) = font["fvar"].instances
        instance_name_id = fvar_instance.subfamilyNameID
        assert instance_name_id >= 256
        assert font["name"].getName(instance_name_id, 3, 1, 0x409).toUnicode() == (
            "Light"
        )
        assert font["name"].getName(instance_name_id, 3, 1, 0x40C).toUnicode() == (
            "Léger"
        )


def test_variable_font_family_name_xml_roundtrip():
    doc = make_designspace()
    xml = doc.tostring().decode("utf-8")
    assert 'familyname="First Family"' in xml
    assert 'familyname="Second Family"' in xml
    assert '<familyname xml:lang="fr">Deuxième Famille</familyname>' in xml

    doc2 = DesignSpaceDocument.fromstring(xml.encode("utf-8"))
    vf1, vf2 = doc2.variableFonts
    assert vf1.familyName == "First Family"
    assert vf1.localisedFamilyName == {"en": "First Family"}
    assert vf2.familyName == "Second Family"
    assert vf2.localisedFamilyName == {
        "en": "Second Family",
        "fr": "Deuxième Famille",
    }
    # The second write must be byte-identical to the first.
    assert doc2.tostring().decode("utf-8") == xml


def test_variable_font_without_family_name_roundtrip_has_no_attribute():
    doc = make_designspace()
    doc.variableFonts[0].familyName = None
    doc.variableFonts[0].localisedFamilyName = {}
    xml = doc.tostring().decode("utf-8")
    assert (
        "familyname="
        not in xml.split('name="SecondFamily_VF"')[0].split('name="FirstFamily_VF"')[1]
    )

    doc2 = DesignSpaceDocument.fromstring(xml.encode("utf-8"))
    assert doc2.variableFonts[0].familyName is None
    assert doc2.variableFonts[0].localisedFamilyName == {}
