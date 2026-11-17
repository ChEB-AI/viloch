"""The rule IR: negated aggregates are read as their positive counterpart."""

from __future__ import annotations

import pytest

from viloch.logic.rule_ir import Agg, parse_program

COUNT = "#count{ X : has_atom(M,X), o(X) }"
_MIRROR = {"=": "=", "!=": "!=", "<": ">", "<=": ">=", ">": "<", ">=": "<="}


def bounds(clause) -> list[tuple[str, str]]:
    """The bounds of the clause's aggregates as ``#count op n``."""
    out = []
    for b in clause.body:
        if isinstance(b, Agg):
            if b.lguard:
                out.append((_MIRROR[b.lguard[0]], b.lguard[1]))
            if b.rguard:
                out.append(b.rguard)
    return out


@pytest.mark.parametrize(
    "body, bound",
    [
        (f"not {COUNT} >= 2", ("<", "2")),
        (f"not {COUNT} > 2", ("<=", "2")),
        (f"not {COUNT} = 3", ("!=", "3")),
        (f"not {COUNT} = 0", (">=", "1")),
        (f"not 2 <= {COUNT}", ("<", "2")),
        (f"not 0 = {COUNT}", (">=", "1")),
        (f"{COUNT} >= 2", (">=", "2")),  # unchanged without "not"
    ],
)
def test_negated_aggregate_flips_its_bound(body, bound):
    (clause,) = parse_program(f"p(M) :- has_atom(M,_), {body}.")
    assert bounds(clause) == [bound]


def test_negated_two_sided_aggregate_is_two_clauses():
    clauses = parse_program(f"p(M) :- has_atom(M,_), not 1 <= {COUNT} <= 3, q(M).")
    assert [bounds(c) for c in clauses] == [[("<", "1")], [(">", "3")]]
    assert all(str(c.body[-1]) == "q(M)" for c in clauses)


def test_negated_aggregate_without_bound_is_rejected():
    with pytest.raises(ValueError, match="without a bound"):
        parse_program(f"p(M) :- has_atom(M,_), not {COUNT}.")
