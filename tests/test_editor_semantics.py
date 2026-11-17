"""The editor never changes what a rule means: a rule and its round trip through the
editor model accept exactly the same molecules."""

from __future__ import annotations

import csv
import functools

import clingo
import pytest
from helpers import EDITOR_FIXTURES, FIXTURES, editor_cases

from viloch.editor.asp import from_asp, to_asp

# Definitions of the aux predicates some fixtures use.
SUPPORT = """
aux_atom_element(A, E) :- has_atom(M, A), c(A), has_atom(M, E), c(E), bSINGLE(A, E).
aux_has_carboxy(M) :- has_atom(M, C), c(C), has_atom(M, O), o(O), bDOUBLE(C, O).
"""


@functools.cache
def molecules() -> list[tuple[str, str]]:
    with open(FIXTURES / "molecules.tsv", encoding="utf-8") as fh:
        return [(r["name"], r["smiles"]) for r in csv.DictReader(fh, delimiter="\t")]


@functools.cache
def facts(smiles: str) -> str:
    from viloch.explain.explain import read_molecule
    from viloch.explain.molecule import bk_facts

    return "\n".join(bk_facts(read_molecule(smiles)))


def accepts(rule: str, smiles: str) -> bool:
    ctl = clingo.Control(["--warn=none"])
    ctl.add("base", [], facts(smiles) + SUPPORT + rule + "\n#show concept/1.")
    ctl.ground([("base", [])])
    found = []
    ctl.solve(on_model=lambda m: found.extend(str(s) for s in m.symbols(shown=True)))
    return "concept(m)" in found


# Known editor limitation (inherited from icarus): a clause that is only the guard
# has_atom(M,_) ("every molecule") parses to an empty clause, which compiles to nothing.
KNOWN_LOSSY = {"only_guard"}


@pytest.mark.parametrize(
    "name",
    [
        pytest.param(
            n, marks=pytest.mark.xfail(reason="guard-only clause", strict=True)
        )
        if n in KNOWN_LOSSY
        else n
        for n in editor_cases()
    ],
)
def test_round_trip_keeps_meaning(name):
    rule = (EDITOR_FIXTURES / f"{name}.lp").read_text(encoding="utf-8")
    round_trip = to_asp(from_asp(rule))
    before = {n for n, s in molecules() if accepts(rule, s)}
    after = {n for n, s in molecules() if accepts(round_trip, s)}
    assert before == after
