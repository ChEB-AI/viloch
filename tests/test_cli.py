from __future__ import annotations

import json

import pytest
from helpers import DEFS, LIBRARY

from viloch.cli import main


def test_convert_round_trip(capsys, tmp_path):
    assert main(["convert", str(DEFS / "alternatives.lp"), "--to", "model"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["target"] == "concept"
    assert len(data["model"]["clauses"]) == 2
    assert [p["name"] for p in data["aux"]] == ["aux_charged"]

    model_file = tmp_path / "model.json"
    model_file.write_text(json.dumps(data))
    assert main(["convert", str(model_file), "--to", "asp"]) == 0
    text = capsys.readouterr().out
    assert "concept(V0) :- has_atom(V0,V1), s(V1)." in text
    assert "% PREDICATE_NAME: aux_charged" in text


@pytest.mark.slow
def test_explain_rule_writes_png(capsys, tmp_path):
    out = tmp_path / "rule.png"
    code = main(
        ["explain-rule", str(DEFS / "carboxylic_acid.lp"), "-o", str(out), "--json"]
    )
    assert code == 0
    record = json.loads(capsys.readouterr().out)
    assert record["image"] == str(out) and out.stat().st_size > 1000
    assert record["text"]


@pytest.mark.slow
def test_explain_molecule_single(capsys):
    code = main(
        [
            "explain-molecule",
            str(DEFS / "carboxylic_acid.lp"),
            "--smiles",
            "CC(=O)O",
            "--name",
            "acetic acid",
            "--class-name",
            "carboxylic acid",
        ]
    )
    assert code == 0
    assert capsys.readouterr().out.startswith("acetic acid: accepted.")


@pytest.mark.slow
def test_explain_molecule_batch(capsys, tmp_path):
    batch = tmp_path / "mols.tsv"
    batch.write_text("name\tsmiles\nethanol\tCCO\nbenzene\tc1ccccc1\nbroken\tC(\n")
    code = main(
        [
            "explain-molecule",
            str(DEFS / "library_aux.lp"),
            "--library",
            LIBRARY,
            "--batch",
            str(batch),
            "--out-dir",
            str(tmp_path / "out"),
            "--json",
        ]
    )
    assert code == 1  # one molecule could not be parsed
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert {r["molecule"]: r["fires"] for r in records} == {
        "ethanol": True,
        "benzene": False,
    }
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == [
        "benzene.png",
        "ethanol.png",
    ]


def test_missing_library_is_an_error(capsys):
    assert main(["explain-rule", str(DEFS / "library_aux.lp")]) == 2
    assert "aux_hydroxy" in capsys.readouterr().err
