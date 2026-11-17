"""The block editor's "not" boxes, as the explainer wants them.

The editor writes "no atoms X,… with …" as ``#count{ X,… : cond } = 0``. The explainer
presents a negated predicate as a pattern the molecule must not contain, but an
aggregate as "exactly 0 …". :func:`explainer_inputs` turns each such box back into a
negated helper predicate ``not aux_viloch_no_match_<k>(Shared…)`` with its own program.
"""

from __future__ import annotations

from viloch.definition import AuxProgram, Definition
from viloch.logic.rule_ir import Agg, Clause, Lit, ordered_vars, parse_program

HELPER_PREFIX = "aux_viloch_no_match_"


def explainer_inputs(defn: Definition) -> Definition:
    """``defn`` with each "not" box of its main rule replaced by a negated helper."""
    if "#count" not in defn.rule:
        return defn
    try:
        clauses = parse_program(defn.rule)
    except Exception:
        return defn
    helpers, out = [], []
    for c in clauses:
        outer = set(
            ordered_vars([c.head] + [b for b in c.body if not isinstance(b, Agg)])
        )
        body = []
        for b in c.body:
            helper = (
                no_match_helper(b, outer, len(helpers) + 1)
                if isinstance(b, Agg)
                else None
            )
            if helper is None:
                body.append(b)
                continue
            lit, program = helper
            helpers.append(program)
            body.append(lit)
        out.append(Clause(c.head, body))
    if not helpers:
        return defn
    return Definition("\n".join(map(str, out)), defn.aux + tuple(helpers), defn.target)


def no_match_helper(agg: Agg, outer: set, k: int) -> tuple[Lit, AuxProgram] | None:
    """``(not aux_viloch_no_match_k(Shared…), program)`` for ``#count{ … : cond } = 0``,
    or None when ``agg`` is anything else or the helper would be unsafe."""
    zero = ("=", "0")
    if agg.func != "count" or len(agg.elems) != 1:
        return None
    if not (
        (agg.lguard == zero and agg.rguard is None)
        or (agg.rguard == zero and agg.lguard is None)
    ):
        return None
    cond = list(agg.elems[0].cond)
    shared = [v for v in ordered_vars(cond) if v in outer]
    positive = set(ordered_vars([x for x in cond if isinstance(x, Lit) and not x.neg]))
    if any(v not in positive for v in shared):
        return None
    name = f"{HELPER_PREFIX}{k}"
    head = f"{name}({','.join(shared)})" if shared else name
    program = AuxProgram(
        name,
        f"{head} :- {', '.join(map(str, cond))}.",
        "",
    )
    return Lit(name, tuple(shared), True), program
