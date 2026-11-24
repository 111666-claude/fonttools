"""Multi-rule contract tests for designspaceLib.

The single-rule tests live in ``designspace_test.py``. This module covers the
cases that only show up when several rules interact in one document:

* the order in which rules are evaluated (and serialized),
* OR between conditionsets and AND within a conditionset,
* axis defaults that fill in missing coordinates,
* substitutions that chain on the same glyph across rules,
* reading/writing a document without changing the resulting substitutions,
* empty hits, invalid conditions and duplicate rules.

The fixture ``data/multi_rules.designspace`` is a small but realistic
designspace: two mapped axes, nine rules that overlap in several places and a
default source location that is not a corner of the designspace.

Expected values below are written out by hand rather than computed with the
code under test, so a regression in ``evaluateRule``/``processRules`` or in
rule serialization is reported instead of silently accepted.

Failure messages include the coordinates, the expected/actual glyphs, the
expected/actual matching rules and a trace of every rule at that location; see
``_format_failure``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import pytest

import fontTools.designspaceLib as designspaceLib
from fontTools.designspaceLib import (
    DesignSpaceDocument,
    DesignSpaceDocumentError,
    RuleDescriptor,
    evaluateRule,
    processRules,
)
from fontTools.misc import etree as ET

DATA_DIR = Path(__file__).parent / "data"

FIXTURE = "multi_rules.designspace"

# An unmodified document from the test corpus, also used by varLib/split tests.
# Two overlapping rules on mapped axes; the default location is a corner
# (weight=300, width=50) rather than the middle of the space.
REAL_SAMPLE = "split_output/MutatorSansVariable_Weight_Width.designspace"

# Glyphs used by the matrix cases. They cover every substitution target in the
# fixture plus one glyph no rule mentions.
GLYPHS = ("slash", "dollar", "ampersand", "three", "zero", "two", "A")

# The rule names in document order. "ampersand.alt" appears twice on purpose:
# the document contains an exact duplicate rule.
RULE_NAMES = (
    "slash.wide",
    "slash.final",
    "dollar.to.alt",
    "dollar.to.alt2",
    "ampersand.alt",
    "ampersand.alt",
    "default.weight",
    "always",
    "never",
)


@dataclass(frozen=True)
class RuleCase:
    """One coordinate at which the multi-rule behavior is pinned down."""

    id: str
    expected_glyphs: tuple[str, ...]
    expected_matched: tuple[str, ...]
    glyphs: tuple[str, ...] = GLYPHS
    # Exactly one of the two locations is given. Design locations are used for
    # exact boundary checks; user locations exercise axis mapping and defaults.
    design_location: Mapping[str, float] | None = None
    user_location: Mapping[str, float] | None = None

    def location(self, doc: DesignSpaceDocument) -> dict[str, float]:
        if self.design_location is not None:
            return dict(self.design_location)
        assert self.user_location is not None
        return doc.map_forward(dict(self.user_location))


# ---------------------------------------------------------------------------
# Contract cases
# ---------------------------------------------------------------------------

# Design coordinates. The axes map as follows:
#   Weight: user 300/400/700/900 -> design 0/100/600/1000
#   Width:  user  50/100/200    -> design 0/500/1000
DESIGN_CASES: tuple[RuleCase, ...] = (
    RuleCase(
        id="default.design",
        design_location={"Weight": 100, "Width": 500},
        expected_matched=(
            "dollar.to.alt",
            "ampersand.alt",
            "ampersand.alt",
            "default.weight",
            "always",
        ),
        expected_glyphs=(
            "slash",
            "dollar.alt",
            "ampersand.alt",
            "three.alt",
            "zero.osf",
            "two",
            "A",
        ),
    ),
    RuleCase(
        id="bold.narrow",
        design_location={"Weight": 1000, "Width": 0},
        expected_matched=(
            "slash.wide",
            "slash.final",
            "dollar.to.alt",
            "dollar.to.alt2",
            "ampersand.alt",
            "ampersand.alt",
            "always",
        ),
        expected_glyphs=(
            "slash.final",
            "dollar.alt2",
            "ampersand.alt",
            "three",
            "zero.osf",
            "two",
            "A",
        ),
    ),
    RuleCase(
        id="light.wide",
        design_location={"Weight": 0, "Width": 1000},
        expected_matched=("slash.wide", "default.weight", "always"),
        expected_glyphs=(
            "slash.wide",
            "dollar",
            "ampersand",
            "three.alt",
            "zero.osf",
            "two",
            "A",
        ),
    ),
    RuleCase(
        id="bold.wide",
        design_location={"Weight": 1000, "Width": 1000},
        expected_matched=(
            "slash.wide",
            "slash.final",
            "dollar.to.alt2",
            "ampersand.alt",
            "ampersand.alt",
            "always",
        ),
        expected_glyphs=(
            "slash.final",
            "dollar",
            "ampersand.alt",
            "three",
            "zero.osf",
            "two",
            "A",
        ),
    ),
    RuleCase(
        id="or.second.conditionset",
        design_location={"Weight": 300, "Width": 750},
        expected_matched=("slash.wide", "always"),
        expected_glyphs=(
            "slash.wide",
            "dollar",
            "ampersand",
            "three",
            "zero.osf",
            "two",
            "A",
        ),
    ),
    RuleCase(
        id="and.both.conditions",
        design_location={"Weight": 600, "Width": 300},
        expected_matched=(
            "slash.wide",
            "dollar.to.alt",
            "dollar.to.alt2",
            "ampersand.alt",
            "ampersand.alt",
            "always",
        ),
        expected_glyphs=(
            "slash.wide",
            "dollar.alt2",
            "ampersand.alt",
            "three",
            "zero.osf",
            "two",
            "A",
        ),
    ),
    RuleCase(
        id="or.neither.conditionset",
        design_location={"Weight": 900, "Width": 500},
        expected_matched=(
            "slash.final",
            "dollar.to.alt",
            "dollar.to.alt2",
            "ampersand.alt",
            "ampersand.alt",
            "always",
        ),
        expected_glyphs=(
            "slash",
            "dollar.alt2",
            "ampersand.alt",
            "three",
            "zero.osf",
            "two",
            "A",
        ),
    ),
    RuleCase(
        id="chain.first.link.only",
        design_location={"Weight": 300, "Width": 300},
        expected_matched=(
            "dollar.to.alt",
            "ampersand.alt",
            "ampersand.alt",
            "always",
        ),
        expected_glyphs=(
            "slash",
            "dollar.alt",
            "ampersand.alt",
            "three",
            "zero.osf",
            "two",
            "A",
        ),
    ),
    RuleCase(
        id="chain.second.link.alone.cannot.fire",
        design_location={"Weight": 900, "Width": 600},
        expected_matched=(
            "slash.final",
            "dollar.to.alt2",
            "ampersand.alt",
            "ampersand.alt",
            "always",
        ),
        expected_glyphs=(
            "slash",
            "dollar",
            "ampersand.alt",
            "three",
            "zero.osf",
            "two",
            "A",
        ),
    ),
    RuleCase(
        id="chain.both.links",
        design_location={"Weight": 1000, "Width": 300},
        expected_matched=(
            "slash.wide",
            "slash.final",
            "dollar.to.alt",
            "dollar.to.alt2",
            "ampersand.alt",
            "ampersand.alt",
            "always",
        ),
        expected_glyphs=(
            "slash.final",
            "dollar.alt2",
            "ampersand.alt",
            "three",
            "zero.osf",
            "two",
            "A",
        ),
    ),
    RuleCase(
        id="boundary.weight.min.hit",
        design_location={"Weight": 500, "Width": 0},
        expected_matched=(
            "slash.wide",
            "dollar.to.alt",
            "dollar.to.alt2",
            "ampersand.alt",
            "ampersand.alt",
            "always",
        ),
        expected_glyphs=(
            "slash.wide",
            "dollar.alt2",
            "ampersand.alt",
            "three",
            "zero.osf",
            "two",
            "A",
        ),
    ),
    RuleCase(
        id="boundary.weight.min.miss",
        design_location={"Weight": 499.999, "Width": 0},
        expected_matched=(
            "dollar.to.alt",
            "ampersand.alt",
            "ampersand.alt",
            "always",
        ),
        expected_glyphs=(
            "slash",
            "dollar.alt",
            "ampersand.alt",
            "three",
            "zero.osf",
            "two",
            "A",
        ),
    ),
    RuleCase(
        id="boundary.width.max.hit",
        design_location={"Weight": 600, "Width": 400},
        expected_matched=(
            "slash.wide",
            "dollar.to.alt",
            "dollar.to.alt2",
            "ampersand.alt",
            "ampersand.alt",
            "always",
        ),
        expected_glyphs=(
            "slash.wide",
            "dollar.alt2",
            "ampersand.alt",
            "three",
            "zero.osf",
            "two",
            "A",
        ),
    ),
    RuleCase(
        id="boundary.width.max.miss",
        design_location={"Weight": 600, "Width": 400.001},
        expected_matched=(
            "dollar.to.alt",
            "dollar.to.alt2",
            "ampersand.alt",
            "ampersand.alt",
            "always",
        ),
        expected_glyphs=(
            "slash",
            "dollar.alt2",
            "ampersand.alt",
            "three",
            "zero.osf",
            "two",
            "A",
        ),
    ),
    RuleCase(
        id="boundary.or.set2.hit",
        design_location={"Weight": 100, "Width": 750},
        expected_matched=("slash.wide", "default.weight", "always"),
        expected_glyphs=(
            "slash.wide",
            "dollar",
            "ampersand",
            "three.alt",
            "zero.osf",
            "two",
            "A",
        ),
    ),
    RuleCase(
        id="boundary.or.set2.miss",
        design_location={"Weight": 100, "Width": 749.999},
        expected_matched=("default.weight", "always"),
        expected_glyphs=(
            "slash",
            "dollar",
            "ampersand",
            "three.alt",
            "zero.osf",
            "two",
            "A",
        ),
    ),
    RuleCase(
        id="boundary.final.min.hit",
        design_location={"Weight": 700, "Width": 0},
        expected_matched=(
            "slash.wide",
            "slash.final",
            "dollar.to.alt",
            "dollar.to.alt2",
            "ampersand.alt",
            "ampersand.alt",
            "always",
        ),
        expected_glyphs=(
            "slash.final",
            "dollar.alt2",
            "ampersand.alt",
            "three",
            "zero.osf",
            "two",
            "A",
        ),
    ),
    RuleCase(
        id="boundary.final.min.miss",
        design_location={"Weight": 699.999, "Width": 0},
        expected_matched=(
            "slash.wide",
            "dollar.to.alt",
            "dollar.to.alt2",
            "ampersand.alt",
            "ampersand.alt",
            "always",
        ),
        expected_glyphs=(
            "slash.wide",
            "dollar.alt2",
            "ampersand.alt",
            "three",
            "zero.osf",
            "two",
            "A",
        ),
    ),
    RuleCase(
        id="boundary.dollar.width.hit",
        design_location={"Weight": 300, "Width": 500},
        expected_matched=(
            "dollar.to.alt",
            "ampersand.alt",
            "ampersand.alt",
            "always",
        ),
        expected_glyphs=(
            "slash",
            "dollar.alt",
            "ampersand.alt",
            "three",
            "zero.osf",
            "two",
            "A",
        ),
    ),
    RuleCase(
        id="boundary.dollar.width.miss",
        design_location={"Weight": 100, "Width": 500.001},
        expected_matched=("default.weight", "always"),
        expected_glyphs=(
            "slash",
            "dollar",
            "ampersand",
            "three.alt",
            "zero.osf",
            "two",
            "A",
        ),
    ),
    RuleCase(
        id="boundary.default.weight.hit",
        design_location={"Weight": 200, "Width": 1000},
        expected_matched=("slash.wide", "default.weight", "always"),
        expected_glyphs=(
            "slash.wide",
            "dollar",
            "ampersand",
            "three.alt",
            "zero.osf",
            "two",
            "A",
        ),
    ),
    RuleCase(
        id="boundary.default.weight.miss",
        design_location={"Weight": 200.001, "Width": 1000},
        expected_matched=("slash.wide", "always"),
        expected_glyphs=(
            "slash.wide",
            "dollar",
            "ampersand",
            "three",
            "zero.osf",
            "two",
            "A",
        ),
    ),
    RuleCase(
        id="only.always.on.matches.no.targets",
        design_location={"Weight": 300, "Width": 600},
        glyphs=("A", "B"),
        expected_matched=("always",),
        expected_glyphs=("A", "B"),
    ),
    RuleCase(
        id="hit.but.no.target.glyphs",
        design_location={"Weight": 1000, "Width": 0},
        glyphs=("A", "B"),
        expected_matched=(
            "slash.wide",
            "slash.final",
            "dollar.to.alt",
            "dollar.to.alt2",
            "ampersand.alt",
            "ampersand.alt",
            "always",
        ),
        expected_glyphs=("A", "B"),
    ),
)

# User coordinates. These prove that mapping and axis defaults are applied
# before the rules are evaluated.
USER_CASES: tuple[RuleCase, ...] = (
    RuleCase(
        id="user.implicit.defaults",
        user_location={},
        expected_matched=(
            "dollar.to.alt",
            "ampersand.alt",
            "ampersand.alt",
            "default.weight",
            "always",
        ),
        expected_glyphs=(
            "slash",
            "dollar.alt",
            "ampersand.alt",
            "three.alt",
            "zero.osf",
            "two",
            "A",
        ),
    ),
    RuleCase(
        id="user.partial.defaults",
        user_location={"Weight": 400},
        expected_matched=(
            "dollar.to.alt",
            "ampersand.alt",
            "ampersand.alt",
            "default.weight",
            "always",
        ),
        expected_glyphs=(
            "slash",
            "dollar.alt",
            "ampersand.alt",
            "three.alt",
            "zero.osf",
            "two",
            "A",
        ),
    ),
    RuleCase(
        id="user.explicit.defaults",
        user_location={"Weight": 400, "Width": 100},
        expected_matched=(
            "dollar.to.alt",
            "ampersand.alt",
            "ampersand.alt",
            "default.weight",
            "always",
        ),
        expected_glyphs=(
            "slash",
            "dollar.alt",
            "ampersand.alt",
            "three.alt",
            "zero.osf",
            "two",
            "A",
        ),
    ),
    RuleCase(
        id="user.light.narrow",
        user_location={"Weight": 300, "Width": 50},
        expected_matched=(
            "dollar.to.alt",
            "ampersand.alt",
            "ampersand.alt",
            "default.weight",
            "always",
        ),
        expected_glyphs=(
            "slash",
            "dollar.alt",
            "ampersand.alt",
            "three.alt",
            "zero.osf",
            "two",
            "A",
        ),
    ),
    RuleCase(
        id="user.bold.wide",
        user_location={"Weight": 900, "Width": 200},
        expected_matched=(
            "slash.wide",
            "slash.final",
            "dollar.to.alt2",
            "ampersand.alt",
            "ampersand.alt",
            "always",
        ),
        expected_glyphs=(
            "slash.final",
            "dollar",
            "ampersand.alt",
            "three",
            "zero.osf",
            "two",
            "A",
        ),
    ),
    RuleCase(
        id="user.semibold.mid",
        user_location={"Weight": 700, "Width": 150},
        expected_matched=(
            "slash.wide",
            "dollar.to.alt2",
            "ampersand.alt",
            "ampersand.alt",
            "always",
        ),
        expected_glyphs=(
            "slash.wide",
            "dollar",
            "ampersand.alt",
            "three",
            "zero.osf",
            "two",
            "A",
        ),
    ),
    RuleCase(
        id="user.missing.width",
        user_location={"Weight": 900},
        expected_matched=(
            "slash.final",
            "dollar.to.alt",
            "dollar.to.alt2",
            "ampersand.alt",
            "ampersand.alt",
            "always",
        ),
        expected_glyphs=(
            "slash",
            "dollar.alt2",
            "ampersand.alt",
            "three",
            "zero.osf",
            "two",
            "A",
        ),
    ),
)

ALL_CASES = DESIGN_CASES + USER_CASES


# ---------------------------------------------------------------------------
# Readable failure reporting
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContractFailure:
    case_id: str
    expected_glyphs: tuple[str, ...]
    actual_glyphs: tuple[str, ...]
    expected_matched: tuple[str, ...]
    actual_matched: tuple[str, ...]
    report: str


def _format_number(value: float) -> str:
    if float(value).is_integer():
        return f"{int(value)}"
    return f"{value:g}"


def _format_condition(condition: Mapping[str, float | None]) -> str:
    minimum = condition.get("minimum")
    maximum = condition.get("maximum")
    lower = "-inf" if minimum is None else _format_number(minimum)
    upper = "+inf" if maximum is None else _format_number(maximum)
    return f"{condition['name']} [{lower}, {upper}]"


def _format_conditionsets(rule: RuleDescriptor) -> str:
    if not rule.conditionSets:
        return "<no conditionset: never matches>"
    rendered_sets = []
    for conditions in rule.conditionSets:
        if not conditions:
            rendered_sets.append("<empty conditionset: always true>")
        else:
            rendered_sets.append(
                " AND ".join(_format_condition(condition) for condition in conditions)
            )
    return " OR ".join(f"({rendered})" for rendered in rendered_sets)


def _format_rule_trace(doc: DesignSpaceDocument, location: Mapping[str, float]) -> str:
    lines = []
    for index, rule in enumerate(doc.rules):
        status = "HIT " if designspaceLib.evaluateRule(rule, location) else "miss"
        substitutions = ", ".join(f"{a}->{b}" for a, b in rule.subs)
        lines.append(
            f"    [{index}] {status} {rule.name or '<unnamed>'}: "
            f"{_format_conditionsets(rule)} => {substitutions or '<no subs>'}"
        )
    return "\n".join(lines)


def _format_mapping(mapping: Mapping[str, float]) -> str:
    return (
        "{" + ", ".join(f"{k!r}: {_format_number(v)}" for k, v in mapping.items()) + "}"
    )


def _first_difference(expected: Sequence[str], actual: Sequence[str]) -> str | None:
    for index, (expected_name, actual_name) in enumerate(zip(expected, actual)):
        if expected_name != actual_name:
            return f"glyph {index}: expected {expected_name!r}, got {actual_name!r}"
    if len(expected) != len(actual):
        return f"glyph count: expected {len(expected)}, got {len(actual)}"
    return None


def _apply_rules_in_document_order(
    doc: DesignSpaceDocument,
    location: Mapping[str, float],
    glyphs: Sequence[str],
) -> list[str]:
    """Apply each matching rule's subs in document order, without processRules.

    This is a deliberately independent implementation of the documented
    contract ("the rules are evaluated in this order") used only for failure
    diagnostics: if ``processRules`` disagrees with it, the report can say so
    instead of merely showing different glyphs.
    """
    current = list(glyphs)
    for rule in doc.rules:
        if not designspaceLib.evaluateRule(rule, location):
            continue
        # First matching sub wins, mirroring processRules' intra-rule behavior.
        mapping: dict[str, str] = {}
        for source, target in rule.subs:
            mapping.setdefault(source, target)
        current = [mapping.get(name, name) for name in current]
    return current


def _format_failure(
    case: RuleCase,
    doc: DesignSpaceDocument,
    location: Mapping[str, float],
    actual_matched: Sequence[str],
    actual_glyphs: Sequence[str],
) -> str:
    user_location = doc.map_backward(location)
    document_order_glyphs = _apply_rules_in_document_order(doc, location, case.glyphs)
    lines = [
        f"Rule contract failure: case {case.id!r}",
        f"  design location: {_format_mapping(location)}",
        f"  user location:   {_format_mapping(user_location)}",
        f"  input glyphs:    {list(case.glyphs)}",
        f"  expected glyphs: {list(case.expected_glyphs)}",
        f"  actual glyphs:   {list(actual_glyphs)}",
    ]
    difference = _first_difference(case.expected_glyphs, actual_glyphs)
    if difference is not None:
        lines.append(f"  first difference: {difference}")
    else:
        lines.append("  glyphs match; rule membership/order expectation differs")

    lines.append("  expected matching rules: " f"{list(case.expected_matched)}")
    lines.append("  actual matching rules:   " f"{list(actual_matched)}")
    if list(actual_matched) == list(case.expected_matched):
        lines.append(
            "  matching rule membership is unchanged; the glyph difference must "
            "come from evaluation/substitution order"
        )
    elif sorted(actual_matched) == sorted(case.expected_matched):
        lines.append("  same rules matched, but in a different order")
    else:
        missing = [name for name in case.expected_matched if name not in actual_matched]
        extra = [name for name in actual_matched if name not in case.expected_matched]
        if missing:
            lines.append(f"  rules that should have matched but did not: {missing}")
        if extra:
            lines.append(f"  rules that matched but should not have: {extra}")

    if document_order_glyphs != list(actual_glyphs):
        lines.append(
            "  processRules disagrees with document-order application: "
            f"{document_order_glyphs} vs {list(actual_glyphs)}"
        )
    lines.extend(
        [
            "  rules in document order at this location:",
            _format_rule_trace(doc, location),
        ]
    )
    return "\n".join(lines)


def collect_contract_failures(
    doc: DesignSpaceDocument, cases: Sequence[RuleCase] = ALL_CASES
) -> list[ContractFailure]:
    failures = []
    for case in cases:
        location = case.location(doc)
        actual_matched = tuple(
            rule.name
            for rule in doc.rules
            if designspaceLib.evaluateRule(rule, location)
        )
        actual_glyphs = tuple(
            designspaceLib.processRules(doc.rules, dict(location), list(case.glyphs))
        )
        if (
            actual_glyphs == case.expected_glyphs
            and actual_matched == case.expected_matched
        ):
            continue
        failures.append(
            ContractFailure(
                case_id=case.id,
                expected_glyphs=case.expected_glyphs,
                actual_glyphs=actual_glyphs,
                expected_matched=case.expected_matched,
                actual_matched=actual_matched,
                report=_format_failure(
                    case, doc, location, actual_matched, actual_glyphs
                ),
            )
        )
    return failures


def format_contract_failures(
    failures: Sequence[ContractFailure], context: str = ""
) -> str:
    header = f"{len(failures)} multi-rule contract case(s) failed"
    if context:
        header += f" ({context})"
    return header + ":\n\n" + "\n\n".join(failure.report for failure in failures)


def assert_contract_holds(
    doc: DesignSpaceDocument,
    cases: Sequence[RuleCase] = ALL_CASES,
    context: str = "",
) -> None:
    failures = collect_contract_failures(doc, cases)
    if failures:
        pytest.fail(format_contract_failures(failures, context), pytrace=False)


def load_doc() -> DesignSpaceDocument:
    return DesignSpaceDocument.fromfile(DATA_DIR / FIXTURE)


def _rule_signatures(doc: DesignSpaceDocument):
    return [(rule.name, rule.conditionSets, rule.subs) for rule in doc.rules]


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", ALL_CASES, ids=lambda case: case.id)
def test_multi_rule_contract(case):
    doc = load_doc()
    assert_contract_holds(doc, [case], context=f"case {case.id!r}")


def test_document_rule_order_is_the_fixture_order():
    doc = load_doc()
    assert tuple(rule.name for rule in doc.rules) == RULE_NAMES
    assert doc.rulesProcessingLast is True


def test_rule_order_is_significant():
    doc = load_doc()
    by_name = {rule.name: rule for rule in doc.rules}

    # Where both links of a chain match, the final glyph depends on applying
    # slash.wide before slash.final.
    location = {"Weight": 1000, "Width": 300}
    slash_chain = [by_name["slash.wide"], by_name["slash.final"]]
    assert processRules(slash_chain, location, ["slash"]) == ["slash.final"]
    assert processRules(list(reversed(slash_chain)), location, ["slash"]) == [
        "slash.wide"
    ]

    # Same for the dollar chain: the second rule consumes the output of the
    # first, so reversing the order leaves the intermediate glyph visible.
    dollar_chain = [by_name["dollar.to.alt"], by_name["dollar.to.alt2"]]
    assert processRules(dollar_chain, location, ["dollar"]) == ["dollar.alt2"]
    assert processRules(list(reversed(dollar_chain)), location, ["dollar"]) == [
        "dollar.alt"
    ]


def test_conditionsets_are_ored_and_conditions_are_anded():
    doc = load_doc()
    rule = {rule.name: rule for rule in doc.rules}["slash.wide"]

    # First conditionset: Weight >= 500 AND Width <= 400.
    assert evaluateRule(rule, {"Weight": 600, "Width": 300}) is True
    # Second conditionset alone: Width >= 750 (Weight is irrelevant).
    assert evaluateRule(rule, {"Weight": 0, "Width": 800}) is True
    # Each conditionset fails one of its own conditions: OR stays false.
    assert evaluateRule(rule, {"Weight": 0, "Width": 300}) is False
    assert evaluateRule(rule, {"Weight": 600, "Width": 500}) is False
    # The boundary values are inclusive; several rules in the fixture use
    # exact minimum/maximum values.
    assert evaluateRule(rule, {"Weight": 500, "Width": 400}) is True
    assert evaluateRule(rule, {"Weight": 499.999, "Width": 400}) is False
    assert evaluateRule(rule, {"Weight": 500, "Width": 400.001}) is False


def test_empty_conditionset_is_always_on_but_missing_conditionset_is_never_on():
    always = RuleDescriptor(
        name="always", conditionSets=[[]], subs=[("zero", "zero.osf")]
    )
    never = RuleDescriptor(name="never", subs=[("two", "two.alt")])

    assert evaluateRule(always, {"Weight": 0}) is True
    assert evaluateRule(never, {"Weight": 0}) is False
    assert processRules([never], {"Weight": 0}, ["two", "A"]) == ["two", "A"]


def test_no_matching_rule_leaves_glyphs_unchanged():
    """Empty hit: not a single rule matches, so nothing is substituted."""
    doc = load_doc()
    location = {"Weight": 300, "Width": 600}
    rules = [rule for rule in doc.rules if rule.name != "always"]
    assert not [rule for rule in rules if evaluateRule(rule, location)]
    assert processRules(rules, location, ["zero", "A"]) == ["zero", "A"]

    # With the always-on rule present, the same location still leaves the
    # glyphs unchanged because "zero" is not in the given glyph list.
    assert processRules(doc.rules, location, ["A", "B"]) == ["A", "B"]

    # A document without rules is a no-op too.
    empty_doc = DesignSpaceDocument()
    assert processRules(empty_doc.rules, location, ["a", "b"]) == ["a", "b"]


def test_axis_defaults_fill_missing_coordinates():
    doc = load_doc()
    assert [(axis.name, axis.default) for axis in doc.axes] == [
        ("Weight", 400),
        ("Width", 100),
    ]
    default_location = doc.newDefaultLocation()
    assert default_location == {"Weight": 100.0, "Width": 500.0}
    assert doc.map_forward({}) == default_location
    assert doc.map_forward({"Weight": 400}) == default_location
    assert doc.map_forward({"Weight": 900}) == {"Weight": 1000.0, "Width": 500.0}

    # Rules operate on design coordinates, so the mapped default location is
    # what a caller passes to evaluateRule/processRules.
    assert processRules(doc.rules, default_location, list(GLYPHS)) == [
        "slash",
        "dollar.alt",
        "ampersand.alt",
        "three.alt",
        "zero.osf",
        "two",
        "A",
    ]

    # A location that is missing an axis named by a condition is a caller
    # error; map_forward/newDefaultLocation is the supported way to complete it.
    with pytest.raises(KeyError, match="Weight"):
        evaluateRule(doc.rules[0], {"Width": 300})


def test_consecutive_substitutions_on_the_same_glyph():
    doc = load_doc()
    by_name = {rule.name: rule for rule in doc.rules}
    location = {"Weight": 1000, "Width": 300}

    # Each link alone does at most one substitution.
    assert processRules([by_name["slash.wide"]], location, ["slash"]) == ["slash.wide"]
    assert processRules([by_name["slash.final"]], location, ["slash"]) == ["slash"]
    assert processRules([by_name["dollar.to.alt"]], location, ["dollar"]) == [
        "dollar.alt"
    ]
    assert processRules([by_name["dollar.to.alt2"]], location, ["dollar"]) == ["dollar"]

    # Both links in document order chain.
    assert processRules(
        [by_name["slash.wide"], by_name["slash.final"]], location, ["slash"]
    ) == ["slash.final"]
    assert processRules(
        [by_name["dollar.to.alt"], by_name["dollar.to.alt2"]], location, ["dollar"]
    ) == ["dollar.alt2"]

    # Substitutions are not transitive within one rule: a rule only rewrites
    # the glyphs it was given, so a->b does not become c via b->c in the same
    # rule. Chaining happens between rules (see above).
    single_rule = RuleDescriptor(
        name="a-to-b-to-c",
        conditionSets=[[]],
        subs=[("a", "b"), ("b", "c")],
    )
    assert processRules([single_rule], {"Weight": 0}, ["a", "b"]) == ["b", "c"]


def test_duplicate_rules_are_preserved_in_order_and_are_idempotent():
    doc = load_doc()
    indices = [
        index for index, rule in enumerate(doc.rules) if rule.name == "ampersand.alt"
    ]
    assert indices == [4, 5]
    first, second = doc.rules[4], doc.rules[5]
    assert first.conditionSets == second.conditionSets
    assert first.subs == second.subs

    location = {"Weight": 900, "Width": 300}
    with_both = processRules([first, second], location, ["ampersand", "A"])
    with_one = processRules([first], location, ["ampersand", "A"])
    assert with_both == with_one == ["ampersand.alt", "A"]

    # Duplicates are kept when writing and reading, in their original order.
    reread = DesignSpaceDocument.fromstring(doc.tostring())
    names = [rule.name for rule in reread.rules]
    assert names == list(RULE_NAMES)
    assert names.count("ampersand.alt") == 2


def test_rule_serialization_preserves_order_conditions_and_substitutions():
    doc = load_doc()
    xml_root = ET.fromstring(doc.tostring())

    serialized_names = [
        rule_element.attrib.get("name")
        for rule_element in xml_root.findall(".rules/rule")
    ]
    assert serialized_names == list(RULE_NAMES)
    assert xml_root.find(".rules").attrib.get("processing") == "last"

    # Round-trips through a file and through a string preserve descriptor
    # contents exactly, including condition order and substitution order.
    reread = DesignSpaceDocument.fromstring(doc.tostring())
    assert _rule_signatures(reread) == _rule_signatures(doc)
    assert reread.rulesProcessingLast is True


def test_roundtrip_preserves_behavior_at_every_contract_coordinate(tmp_path):
    original = load_doc()
    roundtrip_path = tmp_path / "multi_rules_roundtrip.designspace"
    original.write(roundtrip_path)
    reread = DesignSpaceDocument.fromfile(roundtrip_path)

    assert _rule_signatures(reread) == _rule_signatures(original)
    assert reread.rulesProcessingLast is True

    # The re-read document must still satisfy the hand-written contract.
    assert_contract_holds(reread, ALL_CASES, context="after file round-trip")

    # And its substitutions must match the original at every coordinate.
    for case in ALL_CASES:
        location = case.location(original)
        before = processRules(original.rules, dict(location), list(case.glyphs))
        after = processRules(reread.rules, dict(location), list(case.glyphs))
        assert before == after, _format_failure(
            case,
            reread,
            location,
            tuple(r.name for r in reread.rules if evaluateRule(r, location)),
            after,
        )


REAL_SAMPLE_CASES = (
    # (user location, matching rule names, output glyphs)
    (
        {"weight": 300, "width": 50},
        ("fold_I_serifs", "fold_S_terminals"),
        ("I.narrow", "S.closed", "A"),
    ),
    (
        {"weight": 900, "width": 200},
        (),
        ("I", "S", "A"),
    ),
    (
        {"weight": 300, "width": 200},
        ("fold_S_terminals",),
        ("I", "S.closed", "A"),
    ),
    (
        {"weight": 900, "width": 50},
        ("fold_I_serifs",),
        ("I.narrow", "S", "A"),
    ),
    (
        # width=100 maps to design 500: just past the 328 cut-off for I.
        {"weight": 500, "width": 100},
        ("fold_S_terminals",),
        ("I", "S.closed", "A"),
    ),
    (
        # weight=700 maps to design 1000: just past the 500 cut-off for S.
        {"weight": 700, "width": 100},
        (),
        ("I", "S", "A"),
    ),
)


def test_real_designspace_sample_matches_before_and_after_roundtrip(tmp_path):
    original = DesignSpaceDocument.fromfile(DATA_DIR / REAL_SAMPLE)
    roundtrip_path = tmp_path / "real_sample_roundtrip.designspace"
    original.write(roundtrip_path)
    reread = DesignSpaceDocument.fromfile(roundtrip_path)

    assert _rule_signatures(reread) == _rule_signatures(original)

    for user_location, expected_matched, expected_glyphs in REAL_SAMPLE_CASES:
        design_location = original.map_forward(dict(user_location))
        assert design_location == reread.map_forward(dict(user_location))

        assert (
            tuple(
                rule.name
                for rule in original.rules
                if evaluateRule(rule, design_location)
            )
            == expected_matched
        )
        assert processRules(
            original.rules, dict(design_location), ["I", "S", "A"]
        ) == list(expected_glyphs)
        # Parsing the round-tripped file must not change any substitution.
        assert processRules(
            reread.rules, dict(design_location), ["I", "S", "A"]
        ) == list(expected_glyphs)


def test_failure_diagnostics_agree_with_processRules():
    """The independent document-order walk used in failure reports must match.

    If this ever diverges, the "processRules disagrees with document-order
    application" line in a failure report would be misleading.
    """
    doc = load_doc()
    for case in ALL_CASES:
        location = case.location(doc)
        assert _apply_rules_in_document_order(
            doc, location, case.glyphs
        ) == processRules(doc.rules, dict(location), list(case.glyphs))


def test_condition_without_minimum_or_maximum_is_rejected_when_reading():
    xml = """\
        <designspace format="5.0">
          <axes>
            <axis name="Weight" tag="wght" minimum="0" default="0" maximum="1000"/>
          </axes>
          <rules>
            <rule name="broken">
              <conditionset>
                <condition name="Weight"/>
              </conditionset>
              <sub name="a" with="a.alt"/>
            </rule>
          </rules>
        </designspace>
        """
    with pytest.raises(
        DesignSpaceDocumentError,
        match="condition missing required minimum or maximum in rule 'broken'",
    ):
        DesignSpaceDocument.fromstring(xml)


def test_unsatisfiable_condition_never_matches():
    rule = RuleDescriptor(
        name="inverted",
        conditionSets=[[{"name": "Weight", "minimum": 600, "maximum": 400}]],
        subs=[("a", "b")],
    )
    assert evaluateRule(rule, {"Weight": 500}) is False
    assert processRules([rule], {"Weight": 500}, ["a"]) == ["a"]


def test_condition_for_unknown_axis_is_rejected_at_evaluation():
    xml = """\
        <designspace format="5.0">
          <axes>
            <axis name="Weight" tag="wght" minimum="0" default="0" maximum="1000"/>
          </axes>
          <rules>
            <rule name="unknown.axis">
              <conditionset>
                <condition name="Ghost" minimum="0" maximum="500"/>
              </conditionset>
              <sub name="a" with="a.alt"/>
            </rule>
          </rules>
        </designspace>
        """
    doc = DesignSpaceDocument.fromstring(xml)
    assert doc.rules[0].conditionSets == [
        [{"name": "Ghost", "minimum": 0.0, "maximum": 500.0}]
    ]

    with pytest.raises(KeyError, match="Ghost"):
        evaluateRule(doc.rules[0], doc.newDefaultLocation())
    with pytest.raises(KeyError, match="Ghost"):
        processRules(doc.rules, doc.newDefaultLocation(), ["a"])


# ---------------------------------------------------------------------------
# Controlled mutations: prove the contract above has teeth.
# ---------------------------------------------------------------------------


def test_contract_detects_reversed_rule_order():
    doc = load_doc()
    broken = doc.deepcopyExceptFonts()
    broken.rules.reverse()

    failures = collect_contract_failures(broken)
    assert failures, "reversing the rules was not detected by the contract"
    report = format_contract_failures(failures, "reversed rule order")
    assert "chain.both.links" in {failure.case_id for failure in failures}, report
    assert "Rule contract failure" in report
    assert "expected glyphs" in report
    assert "actual glyphs" in report
    assert "rules in document order at this location:" in report
    # The trace must reveal the reordered evaluation, not just differing glyphs.
    assert "[0] miss never" in report
    assert "[8] miss slash.wide" in report
    assert "[1] HIT  always" in report


def test_contract_detects_broken_condition_boundaries(monkeypatch):
    """Turn inclusive rule bounds into exclusive ones and require detection."""

    def exclusive_evaluateConditions(conditions, location):
        for condition in conditions:
            value = location[condition["name"]]
            if condition.get("minimum") is None:
                if value >= condition["maximum"]:
                    return False
            elif condition.get("maximum") is None:
                if condition["minimum"] >= value:
                    return False
            elif not condition["minimum"] < value < condition["maximum"]:
                return False
        return True

    monkeypatch.setattr(
        designspaceLib, "evaluateConditions", exclusive_evaluateConditions
    )

    doc = load_doc()
    failures = collect_contract_failures(doc)
    assert failures, "exclusive condition bounds were not detected by the contract"
    failing_cases = {failure.case_id for failure in failures}
    assert "boundary.weight.min.hit" in failing_cases
    assert "boundary.default.weight.hit" in failing_cases

    report = format_contract_failures(failures, "exclusive condition bounds")
    assert "boundary.weight.min.hit" in report
    assert "expected glyphs" in report
    assert "actual glyphs" in report


def test_contract_detects_conditionsets_being_anded(monkeypatch):
    """Treat conditionsets as AND instead of OR and require detection."""

    def anded_evaluateRule(rule, location):
        return all(
            designspaceLib.evaluateConditions(conditions, location)
            for conditions in rule.conditionSets
        )

    monkeypatch.setattr(designspaceLib, "evaluateRule", anded_evaluateRule)

    doc = load_doc()
    failures = collect_contract_failures(doc)
    assert failures, "ANDing conditionsets was not detected by the contract"
    failing_cases = {failure.case_id for failure in failures}
    # "slash.wide" matches at (0, 1000) only through its second conditionset;
    # under AND semantics it stops matching there.
    assert "light.wide" in failing_cases
    assert "or.second.conditionset" in failing_cases

    report = format_contract_failures(failures, "conditionsets ANDed")
    assert "rules in document order at this location:" in report
    assert "miss slash.wide" in report
