"""ASP <-> editor model, against goldens captured from icarus' original blocks.js."""

from __future__ import annotations

import json

import pytest
from helpers import EDITOR_FIXTURES, editor_cases, normalize_ids, without_why

from viloch.editor.asp import from_asp, to_asp

CASES = editor_cases()


def _read(name: str, suffix: str) -> str:
    return (EDITOR_FIXTURES / f"{name}{suffix}").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", CASES)
def test_parse_matches_golden(name):
    model = from_asp(_read(name, ".lp"))
    golden = json.loads(_read(name, ".model.json"))
    assert without_why(normalize_ids(model)) == without_why(golden)


@pytest.mark.parametrize("name", CASES)
def test_compile_matches_golden(name):
    golden = json.loads(_read(name, ".model.json"))
    assert to_asp(golden) == _read(name, ".compiled.lp").rstrip("\n")


@pytest.mark.parametrize("name", CASES)
def test_compile_is_a_fixpoint(name):
    """Text -> model -> text is stable after one round."""
    once = to_asp(from_asp(_read(name, ".lp")))
    assert to_asp(from_asp(once)) == once


@pytest.mark.parametrize("name", CASES)
def test_raw_clauses_say_why(name):
    for clause in from_asp(_read(name, ".lp"))["clauses"]:
        if clause.get("rawClause") is not None:
            assert clause["why"]


def test_target_is_a_parameter():
    model = from_asp("chebi_1(M) :- has_atom(M,A), o(A).", target="chebi_1")
    assert "rawClause" not in model["clauses"][0]
    assert to_asp(model, target="chebi_1") == "chebi_1(V0) :- has_atom(V0,V1), o(V1)."


def test_syntax_error_stays_raw():
    model = from_asp("concept(M) :- has_atom(M,A), o(A")
    (clause,) = model["clauses"]
    assert clause["rawClause"].startswith("concept(M)")
    assert "parsed" in clause["why"]


def test_facts_are_skipped():
    assert from_asp("concept(m1).") == {"clauses": []}


@pytest.mark.parametrize("name", CASES)
def test_models_match_the_schema(name):
    from viloch.editor.model import validate

    validate(from_asp(_read(name, ".lp")))
    validate(json.loads(_read(name, ".model.json")))
