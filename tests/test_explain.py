"""Explanations of the fixture definitions: verdicts, and text a chemist can read."""

from __future__ import annotations

import csv
import re

import pytest
from helpers import FIXTURES

from viloch import Definition, explain_molecule, explain_rule
from viloch.explain.text import MAX_WORDS

DEFS = FIXTURES / "definitions"
LIBRARY = str(FIXTURES / "library")

with open(FIXTURES / "molecules.tsv", encoding="utf-8") as fh:
    SMILES = {r["name"]: r["smiles"] for r in csv.DictReader(fh, delimiter="\t")}
with open(DEFS / "expected.tsv", encoding="utf-8") as fh:
    EXPECTED = [
        (r["definition"], r["molecule"], r["fires"] == "true")
        for r in csv.DictReader(fh, delimiter="\t")
    ]
DEFINITIONS = sorted({d for d, _, _ in EXPECTED})

# Logic-programming syntax that must never reach the reader.
_SYNTAX = re.compile(
    r":-|\baux_|#count|_Anon|\b[A-Z][A-Za-z]*_\d+\b|\bV\d+\b|\b[a-z_]\w*\([A-Z_]"
)


# An atom letter as the subject ("a is C, not O") reads like the article "a".
_BARE_LETTER = re.compile(
    r"(?:^|: |, |and )(?:the )?[a-h](?:–[a-h])? (?:is|has|carries)"
)


def readable(text: str) -> bool:
    return (
        bool(text.strip())
        and not _SYNTAX.search(text.replace("CHEBI:", ""))
        and not _BARE_LETTER.search(text)
    )


def load(name: str) -> Definition:
    return Definition.from_file(DEFS / f"{name}.lp")


pytestmark = pytest.mark.slow


@pytest.mark.parametrize("name", DEFINITIONS)
def test_global_explanation(name):
    expl = explain_rule(load(name), library_dir=LIBRARY)
    assert readable(expl.text), expl.text
    assert expl.image.width > 100 and expl.image.height > 50
    assert expl.fires is None


@pytest.mark.parametrize("name, molecule, fires", EXPECTED)
def test_local_explanation(name, molecule, fires):
    expl = explain_molecule(
        SMILES[molecule], load(name), library_dir=LIBRARY, name=molecule
    )
    assert expl.fires is fires
    assert readable(expl.text), expl.text
    assert len(expl.text.split()) <= 2 * MAX_WORDS
    assert expl.image.width > 100


NO = "This molecule does not satisfy the rule: "


@pytest.mark.parametrize(
    "name, molecule, text",
    [
        # an atom of the wrong element, named as "atom a"
        (
            "library_aux",
            "benzene",
            "in the closest match, atom a is carbon, but oxygen is needed.",
        ),
        # a negated molecule property: pyridine is aromatic
        ("aliphatic_nitrogen", "pyridine", "it has aromatic atoms."),
        # an element missing from the whole molecule; reasons it implies are left out
        ("carboxylic_acid", "hexane", "it has no oxygen atom."),
        (
            "carboxylic_acid",
            "ethanol",
            "the bond between atoms a and b is single, but must be double.",
        ),
        # an editor "not" box: the pattern, not a placeholder description
        (
            "oxygen_without_nitrogen",
            "glycine",
            "it contains a nitrogen atom, which must be absent.",
        ),
        # an aux predicate's description
        (
            "recursive",
            "ethanol",
            "atom a does not meet the condition “the atom is linked by bonds to a nitrogen”.",
        ),
        (
            "two_or_more_oxygens",
            "benzene",
            "it has no oxygen atoms, but must have at least 2.",
        ),
    ],
)
def test_near_miss_wording(name, molecule, text):
    expl = explain_molecule(SMILES[molecule], load(name), library_dir=LIBRARY)
    assert expl.text.startswith(NO + text), expl.text


def test_class_name_without_graph():
    expl = explain_molecule(
        SMILES["acetic acid"], load("carboxylic_acid"), class_name="carboxylic acid"
    )
    assert expl.fires is True


def test_rule_text_is_accepted():
    expl = explain_rule("concept(M) :- has_atom(M,A), o(A).")
    assert "oxygen" in expl.text
