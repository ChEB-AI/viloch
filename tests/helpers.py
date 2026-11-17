"""Shared test helpers."""

from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
EDITOR_FIXTURES = FIXTURES / "editor"


def editor_cases() -> list[str]:
    return sorted(
        p.stem
        for p in EDITOR_FIXTURES.glob("*.lp")
        if not p.name.endswith(".compiled.lp")
    )


def normalize_ids(model: dict) -> dict:
    """Renumber ids ``a1, a2, …`` by position (mirrors tests/js/normalize.cjs)."""
    mapping: dict[str, str] = {}

    def nid(old: str) -> str:
        if old not in mapping:
            mapping[old] = f"a{len(mapping) + 1}"
        return mapping[old]

    out = []
    for cl in model.get("clauses", []):
        if cl.get("rawClause") is not None:
            out.append(cl)
            continue
        for a in cl["atoms"]:
            if not a.get("group"):
                nid(a["id"])
        for g in cl["groups"]:
            nid(g["id"])
            for a in cl["atoms"]:
                if a.get("group") == g["id"]:
                    nid(a["id"])
        out.append(
            {
                **cl,
                "atoms": [
                    {
                        **a,
                        "id": nid(a["id"]),
                        **({"group": nid(a["group"])} if a.get("group") else {}),
                    }
                    for a in cl["atoms"]
                ],
                "bonds": [
                    {**b, "a": nid(b["a"]), "b": nid(b["b"])} for b in cl["bonds"]
                ],
                "groups": [{**g, "id": nid(g["id"])} for g in cl["groups"]],
            }
        )
    return {**model, "clauses": out}


def without_why(model: dict) -> dict:
    """``model`` with the reasons of raw clauses dropped (their wording may differ)."""
    return {
        **model,
        "clauses": [
            {"rawClause": c["rawClause"]} if c.get("rawClause") is not None else c
            for c in model.get("clauses", [])
        ],
    }
