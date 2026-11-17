from __future__ import annotations

import pytest
from helpers import FIXTURES

from viloch.definition import AuxProgram, Definition, split_clauses

DEFS = FIXTURES / "definitions"
LIBRARY = FIXTURES / "library"


def test_parse_splits_main_rule_and_aux():
    d = Definition.from_file(DEFS / "alternatives.lp")
    assert d.target == "concept"
    assert d.rule.count("concept(M)") == 2
    (aux,) = d.aux
    assert aux.name == "aux_charged"
    assert aux.description == "the atom carries a formal charge"
    assert aux.source.count(":-") == 2


def test_main_rule_is_the_unused_predicate():
    d = Definition.from_file(DEFS / "carboxylic_acid.lp")
    assert d.target == "chebi_33575"
    assert [p.name for p in d.aux] == ["aux_carboxy_group"]


def test_explicit_target_wins():
    d = Definition.parse("a(M) :- b(M).\nb(M) :- c(M).", target="b")
    assert d.rule == "b(M) :- c(M)."
    assert [p.name for p in d.aux] == ["a"]


def test_text_round_trip():
    d = Definition.from_file(DEFS / "alternatives.lp")
    assert Definition.parse(d.to_text()) == d


def test_header_without_aux_prefix():
    text = "concept(M) :- aux_x(M).\n% PREDICATE_NAME: x\n% DESCRIPTION: an x\naux_x(M) :- o(M)."
    assert Definition.parse(text).aux == (
        AuxProgram("aux_x", "aux_x(M) :- o(M).", "an x"),
    )


def test_resolve_from_library_is_transitive():
    d = Definition.from_file(DEFS / "library_aux.lp").resolve(str(LIBRARY))
    assert [p.name for p in d.aux] == ["aux_hydroxy", "aux_on_carbon"]
    assert all("%" not in p.source for p in d.aux)
    assert d.aux[0].description.startswith("contains a hydroxy group")
    assert d.used_aux() == []


def test_resolve_without_library_names_the_missing_predicates():
    with pytest.raises(ValueError, match="aux_hydroxy"):
        Definition.from_file(DEFS / "library_aux.lp").resolve(None)


def test_resolve_is_a_no_op_when_self_contained():
    d = Definition.from_file(DEFS / "alternatives.lp")
    assert d.resolve(None) is d


@pytest.mark.parametrize(
    "text, clauses",
    [
        ("a :- b. c :- d.", ["a :- b.", "c :- d."]),
        ("a(X) :- X = 1..3.", ["a(X) :- X = 1..3."]),
        (
            "a :- #count{ X : p(X) } > 1. % note\nb.",
            ["a :- #count{ X : p(X) } > 1.", "b."],
        ),
        ('a :- p("x. y").', ['a :- p("x. y").']),
        ("a :- b", ["a :- b."]),
    ],
)
def test_split_clauses(text, clauses):
    assert split_clauses(text) == clauses


def test_lenient_resolve_keeps_what_it_finds(tmp_path):
    text = "concept(M) :- aux_hydroxy(M), aux_nope(M)."
    d = Definition.parse(text).resolve(str(LIBRARY), strict=False)
    assert [p.name for p in d.aux] == ["aux_hydroxy", "aux_on_carbon"]
    assert d.used_aux() == ["aux_nope"]
    assert (
        Definition.parse(text).resolve(str(tmp_path / "none"), strict=False).aux == ()
    )
    with pytest.raises(ValueError, match="aux_nope"):
        Definition.parse(text).resolve(str(LIBRARY))
