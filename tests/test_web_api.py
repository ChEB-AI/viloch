from __future__ import annotations

import pytest
from helpers import FIXTURES
from starlette.testclient import TestClient

from viloch.web.app import create_app

DEFS = FIXTURES / "definitions"


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app(library_dir=str(FIXTURES / "library")))


def definition(name: str) -> str:
    return (DEFS / f"{name}.lp").read_text(encoding="utf-8")


def test_index_and_assets(client):
    assert "block-canvas" in client.get("/").text
    for asset in ("blocks.js", "blocks.css", "standalone.js", "standalone.css"):
        assert client.get(f"/static/{asset}").status_code == 200


def test_catalog(client):
    data = client.get("/api/catalog").json()
    assert data["target"] == "concept"
    assert any(b["id"] == "el_c" for b in data["catalog"])


def test_parse_compile_round_trip(client):
    parsed = client.post(
        "/api/parse", json={"definition": definition("alternatives")}
    ).json()
    assert parsed["target"] == "concept"
    assert [p["name"] for p in parsed["aux"]] == ["aux_charged"]
    assert [b["input"]["pred"] for b in parsed["blocks"]] == ["aux_charged"]
    assert len(parsed["model"]["clauses"]) == 2

    compiled = client.post(
        "/api/compile",
        json={
            "model": parsed["model"],
            "aux": parsed["aux"],
            "target": parsed["target"],
        },
    ).json()
    assert compiled["rule"].splitlines() == [
        "concept(V0) :- has_atom(V0,V1), s(V1).",
        "concept(V0) :- has_atom(V0,V1), n(V1), aux_charged(V1).",
    ]
    assert "% PREDICATE_NAME: aux_charged" in compiled["definition"]


def test_compile_drops_unused_aux(client):
    parsed = client.post(
        "/api/parse", json={"definition": definition("alternatives")}
    ).json()
    model = {"clauses": parsed["model"]["clauses"][:1]}  # the sulfur clause only
    compiled = client.post(
        "/api/compile", json={"model": model, "aux": parsed["aux"]}
    ).json()
    assert "aux_charged" not in compiled["definition"]


def test_parse_keeps_inferred_target(client):
    parsed = client.post(
        "/api/parse", json={"definition": definition("carboxylic_acid")}
    ).json()
    assert parsed["target"] == "chebi_33575"
    assert "rawClause" not in parsed["model"]["clauses"][0]


def test_parse_unfolded(client):
    parsed = client.post(
        "/api/parse", json={"definition": definition("library_aux"), "unfold": True}
    ).json()
    (clause,) = parsed["model"]["clauses"]
    chips = [c["pred"] for a in clause["atoms"] for c in a["chips"]]
    assert "o" in chips and "has_1_hs" in chips


def test_unfold_one_predicate(client):
    parsed = client.post(
        "/api/parse", json={"definition": definition("alternatives")}
    ).json()
    clause = parsed["model"]["clauses"][1]
    data = client.post(
        "/api/unfold",
        json={"clause": clause, "pred": "aux_charged", "aux": parsed["aux"]},
    ).json()
    assert "error" not in data
    assert len(data["model"]["clauses"]) == 2  # one per clause of the definition


def test_unfold_recursive_reports_why(client):
    defn = definition("recursive")
    parsed = client.post("/api/parse", json={"definition": defn}).json()
    data = client.post(
        "/api/unfold",
        json={
            "clause": parsed["model"]["clauses"][0],
            "pred": "aux_reaches_n",
            "aux": parsed["aux"],
        },
    ).json()
    assert "recursive" in data["error"]


def test_search_finds_library_and_efg(client):
    data = client.get("/api/search", params={"q": "hydroxy"}).json()
    ids = [b["input"]["pred"] for b in data["results"]]
    assert "aux_hydroxy" in ids and any(i.startswith("efg_") for i in ids)


@pytest.mark.parametrize(
    "path, body, status",
    [
        ("/api/parse", {"definition": 5}, 400),
        ("/api/parse", {"definition": "concept(X) :- X = 1..100000000."}, 400),
        ("/api/parse", {"definition": "a" * 30_000}, 400),
        ("/api/compile", {"model": "nope"}, 400),
        ("/api/compile", {"model": {"clauses": [{"atoms": [{}]}]}}, 400),
        ("/api/unfold", {"clause": {}, "pred": "Bad Name"}, 400),
        (
            "/api/explain/molecule",
            {"definition": "concept(M) :- o(M).", "molecule": ""},
            400,
        ),
        (
            "/api/explain/molecule",
            {"definition": "concept(M) :- o(M).", "molecule": "C("},
            422,
        ),
        (
            "/api/explain/rule",
            {
                "definition": definition("library_aux").replace(
                    "aux_hydroxy", "aux_nope"
                )
            },
            422,
        ),
    ],
)
def test_bad_input(client, path, body, status):
    res = client.post(path, json=body)
    assert res.status_code == status
    assert res.json()["error"]


@pytest.mark.slow
def test_explain_endpoints(client):
    rule = client.post(
        "/api/explain/rule", json={"definition": definition("carboxylic_acid")}
    )
    assert rule.status_code == 200
    assert rule.json()["image"].startswith("data:image/png;base64,")
    mol = client.post(
        "/api/explain/molecule",
        json={
            "definition": definition("carboxylic_acid"),
            "molecule": "CC(=O)O",
            "name": "acetic acid",
        },
    ).json()
    assert mol["fires"] is True and mol["text"]
