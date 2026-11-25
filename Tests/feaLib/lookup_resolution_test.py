# -*- coding: utf-8 -*-
"""Comparison coverage for deferred lookup resolution in feaLib.

The parser used to reject references to lookups that had not been defined
*yet* (including genuinely unknown names) while parsing. These tests pin
the new contract:

* parsing keeps by-name lookup references and their source locations, and
  serializing/reparsing the AST loses no information;
* building a still-undefined reference raises a clear ``FeatureLibError``;
* legal samples produce identical GSUB/GPOS whether built directly from a
  string, built from an explicitly parsed AST, or built from an AST that
  was modified to add/retarget a lookup.
"""

from io import StringIO
import unittest

from fontTools.feaLib import ast
from fontTools.feaLib.builder import Builder, addOpenTypeFeaturesFromString
from fontTools.feaLib.error import FeatureLibError
from fontTools.feaLib.parser import Parser
from fontTools.ttLib import TTFont

GLYPH_ORDER = """.notdef space
    A B C D E F G H I J K L M N O P Q R S T U V W X Y Z
    a b c d e f g h i j k l m n o p q r s t u v w x y z
    f_f f_i f_f_i
""".split()


# A conventional, legal feature file: lookups are defined before use and the
# sample exercises both plain ``lookup Name;`` calls and contextual lookup
# references in GSUB and GPOS.
LEGAL_FEA = """
lookup Ligs {
    sub f f i by f_f_i;
} Ligs;

lookup Single {
    sub a by b;
} Single;

lookup CtxSub {
    sub x' lookup Single y;
} CtxSub;

feature liga {
    lookup Ligs;
    lookup Single;
    sub f f i' lookup Ligs;
} liga;

feature test {
    pos c' lookup Kern d;
} test;

lookup Kern {
    pos a 120;
} Kern;
"""

# Lookup call before its definition (a forward reference).
FORWARD_CALL_FEA = """
feature liga {
    lookup Later;
} liga;
lookup Later {
    sub a by b;
} Later;
"""

# The same lookup, defined first -- this is the historically accepted form.
BACK_CALL_FEA = """
lookup Later {
    sub a by b;
} Later;
feature liga {
    lookup Later;
} liga;
"""

UNKNOWN_CALL_FEA = "feature liga {\n  lookup DoesNotExist;\n} liga;\n"
UNKNOWN_CONTEXT_FEA = "feature liga { sub a' lookup MissingCtx b; } liga;\n"


def make_font():
    font = TTFont()
    font.setGlyphOrder(GLYPH_ORDER)
    return font


def parse(text):
    return Parser(StringIO(text), glyphNames=GLYPH_ORDER).parse()


def build_string(text):
    font = make_font()
    addOpenTypeFeaturesFromString(font, text)
    return font


def build_ast(doc):
    font = make_font()
    Builder(font, doc).build()
    return font


def layout_xml(font):
    buf = StringIO()
    font.saveXML(buf, tables=["GSUB", "GPOS"])
    return buf.getvalue()


def lookup_call_statements(doc):
    return [
        s
        for st in doc.statements
        for s in getattr(st, "statements", [])
        if isinstance(s, ast.LookupReferenceStatement)
    ]


class ParseOnlyLookupReferenceTest(unittest.TestCase):
    def test_unknown_call_parses_and_keeps_name_and_location(self):
        doc = parse(UNKNOWN_CALL_FEA)
        [ref] = lookup_call_statements(doc)
        self.assertEqual(ref.name, "DoesNotExist")
        self.assertIsNone(ref.lookup)
        self.assertIsNotNone(ref.location)
        # The reference sits on the second line of the sample.
        self.assertEqual(ref.location.line, 2)
        self.assertIsNotNone(getattr(ref, "name_location", None))

    def test_unknown_contextual_reference_parses(self):
        doc = parse(UNKNOWN_CONTEXT_FEA)
        [feature] = doc.statements
        [chain] = feature.statements
        [[ref]] = chain.lookups
        self.assertIsInstance(ref, ast.LookupReference)
        self.assertEqual(ref.name, "MissingCtx")
        self.assertIsNone(ref.lookup)
        self.assertIsNotNone(ref.location)

    def test_ast_roundtrip_preserves_unknown_references(self):
        doc = parse(UNKNOWN_CALL_FEA)
        once = doc.asFea()
        twice = parse(once).asFea()
        self.assertEqual(once, twice)
        self.assertIn("lookup DoesNotExist;", once)

        doc = parse(UNKNOWN_CONTEXT_FEA)
        once = doc.asFea()
        twice = parse(once).asFea()
        self.assertEqual(once, twice)
        self.assertIn("lookup MissingCtx", once)

    def test_legal_reference_is_bound_to_lookup_block(self):
        doc = parse(BACK_CALL_FEA)
        block = doc.statements[0]
        [ref] = lookup_call_statements(doc)
        self.assertEqual(ref.name, "Later")
        self.assertIs(ref.lookup, block)

    def test_forward_reference_is_bound_after_parse(self):
        doc = parse(FORWARD_CALL_FEA)
        feature, block = doc.statements
        [ref] = [
            s for s in feature.statements if isinstance(s, ast.LookupReferenceStatement)
        ]
        self.assertIs(ref.lookup, block)


class BuildLookupResolutionTest(unittest.TestCase):
    def test_unknown_call_raises_clear_error_from_string(self):
        with self.assertRaisesRegex(
            FeatureLibError, 'Unknown lookup "DoesNotExist"'
        ) as ctx:
            build_string(UNKNOWN_CALL_FEA)
        # Error carries a source location pointing at the reference name.
        self.assertIsNotNone(ctx.exception.location)
        self.assertIn("2:", str(ctx.exception))

    def test_unknown_call_raises_clear_error_from_ast(self):
        doc = parse(UNKNOWN_CALL_FEA)
        with self.assertRaisesRegex(FeatureLibError, 'Unknown lookup "DoesNotExist"'):
            build_ast(doc)

    def test_unknown_contextual_reference_raises(self):
        with self.assertRaisesRegex(
            FeatureLibError, 'Unknown lookup "MissingCtx"'
        ) as ctx:
            build_string(UNKNOWN_CONTEXT_FEA)
        self.assertIsNotNone(ctx.exception.location)

    def test_legal_sample_string_vs_parsed_ast_equivalent(self):
        from_string = layout_xml(build_string(LEGAL_FEA))
        from_ast = layout_xml(build_ast(parse(LEGAL_FEA)))
        self.assertEqual(from_string, from_ast)
        self.assertIn("<GSUB>", from_string)
        self.assertIn("<GPOS>", from_string)

    def test_forward_call_matches_define_first(self):
        forward = layout_xml(build_string(FORWARD_CALL_FEA))
        backward = layout_xml(build_string(BACK_CALL_FEA))
        self.assertEqual(forward, backward)

    def test_forward_call_from_ast_matches(self):
        forward = layout_xml(build_ast(parse(FORWARD_CALL_FEA)))
        backward = layout_xml(build_string(BACK_CALL_FEA))
        self.assertEqual(forward, backward)


class ModifiedAstBuildTest(unittest.TestCase):
    def test_append_missing_lookup_block(self):
        # Parse a file whose feature calls an unknown lookup, then add the
        # missing LookupBlock to the AST before building.
        doc = parse("feature liga { lookup Added; } liga;\n")
        block = ast.LookupBlock("Added")
        block.statements.append(
            ast.SingleSubstStatement(
                [ast.GlyphName("a")], [ast.GlyphName("b")], [], [], False
            )
        )
        doc.statements.append(block)

        modified = layout_xml(build_ast(doc))
        expected = layout_xml(
            build_string(
                "lookup Added { sub a by b; } Added;\n"
                "feature liga { lookup Added; } liga;\n"
            )
        )
        self.assertEqual(modified, expected)

    def test_rename_reference_to_existing_lookup(self):
        doc = parse(
            "lookup Bar { sub a by b; } Bar;\n"
            "feature liga { lookup Missing; } liga;\n"
        )
        for ref in lookup_call_statements(doc):
            if ref.name == "Missing":
                ref.name = "Bar"

        modified = layout_xml(build_ast(doc))
        expected = layout_xml(
            build_string(
                "lookup Bar { sub a by b; } Bar;\n"
                "feature liga { lookup Bar; } liga;\n"
            )
        )
        self.assertEqual(modified, expected)

    def test_retarget_reference_lookup_property(self):
        # Assigning a LookupBlock to ``ref.lookup`` keeps ``name`` in sync.
        doc = parse(
            "lookup Bar { sub a by b; } Bar;\n"
            "feature liga { lookup Missing; } liga;\n"
        )
        bar = doc.statements[0]
        [ref] = [
            s
            for st in doc.statements
            for s in st.statements
            if isinstance(s, ast.LookupReferenceStatement)
        ]
        ref.lookup = bar
        self.assertEqual(ref.name, "Bar")
        layout_xml(build_ast(doc))  # builds without an unknown-lookup error


if __name__ == "__main__":
    unittest.main()
