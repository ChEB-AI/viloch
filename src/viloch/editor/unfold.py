"""A definition's main rule with its auxiliary predicates unfolded, for the block editor.

The editor draws plain clauses: atoms, bonds, molecule properties, and "not"/"count"
boxes. :func:`editor_rule` inlines the definition's auxiliary predicates as far as the
editor can draw the result (``rule_ir.unfold``; a multi-clause definition becomes several
OR'ed clauses), and turns negated auxiliary predicates into "not" boxes.
"""

from __future__ import annotations

import functools
import itertools
import re

from viloch.definition import Definition
from viloch.logic.rule_ir import (
    Agg,
    AggElem,
    Clause,
    Cmp,
    Lit,
    UnfoldPolicy,
    definitions,
    ordered_vars,
    parse_program,
    unfold,
)


def _occurrences(var: str, text: str) -> int:
    return len(re.findall(rf"(?<![A-Za-z0-9_]){re.escape(var)}(?![A-Za-z0-9_])", text))


def _uses(defs: dict, pred: str) -> set[str]:
    """``pred`` and every predicate its definition uses, transitively."""
    seen, todo = set(), [pred]
    while todo:
        p = todo.pop()
        if p in seen:
            continue
        seen.add(p)
        for c in defs.get(p, []):
            todo += re.findall(
                r"(?<![A-Za-z0-9_])([a-z]\w*)\s*\(", " ".join(map(str, c.body))
            )
    return seen


def editor_rule(defn: Definition, only: str | None = None) -> str:
    """The main rule with its auxiliary predicates unfolded into plain clauses.

    A negated auxiliary predicate becomes "not" boxes where the editor can draw its
    definition, and stays as written otherwise, as does anything the unfolding policy
    keeps folded (recursion, too many alternatives); those still need their
    definitions, which ``defn`` keeps. Equivalent to the main rule under the
    definition's programs.

    With ``only``, just that predicate is unfolded (with the helpers its definition
    uses); every other defined predicate stays as written: the editor's "unfold" on one
    chip.
    """
    return _editor_rule(defn.rule, tuple(defn.programs_key()), only)


@functools.lru_cache(maxsize=256)
def _editor_rule(hypothesis: str, programs: tuple, only: str | None) -> str:
    if not programs or not hypothesis:
        return hypothesis
    try:
        clauses = parse_program(hypothesis)
        defs = definitions([src for _name, src in programs])
    except Exception:
        return hypothesis
    support = "\n".join(src for _name, src in programs)
    keep = frozenset(defs) - _uses(defs, only) if only else frozenset()
    policy = UnfoldPolicy(inline_negation=False, keep=keep)
    lines = []
    for clause in clauses:
        # Unfolded clause by clause: one that does not come out as valid, groundable ASP
        # (an aggregate inlined into another aggregate's condition, a "_" from a
        # definition's aggregate) is kept as written.
        try:
            unfolded = []
            for c in unfold([clause], defs, policy).clauses:
                body = _drop_lonely_guards(
                    c.head,
                    _restore_anonymous(list(c.body), set(ordered_vars([c.head]))),
                )
                body = _negations_as_boxes(c.head, body, defs, policy)
                unfolded.append(
                    f"{c.head} :- {', '.join(map(str, body))}."
                    if body
                    else f"{c.head}."
                )
            check_grounds("\n".join(unfolded), support)
            lines += unfolded
        except Exception:
            lines.append(f"{clause}")
    return "\n".join(lines)


def unfold_failure(defn: Definition, pred: str) -> str:
    """Why ``editor_rule(defn, pred)`` left ``pred`` folded, as a phrase for the user."""
    try:
        defs = definitions(defn.programs())
        if pred not in defs:
            return "it has no definition"
        keep = frozenset(defs) - _uses(defs, pred)
        res = unfold(
            parse_program(defn.rule),
            defs,
            UnfoldPolicy(inline_negation=False, keep=keep),
        )
    except Exception:
        return "its definition could not be read"
    reason = res.kept.get(pred, "")
    if reason == "recursive definition":
        return "its definition is recursive"
    if reason == "too many alternatives":
        return "its definition has too many alternatives"
    if reason.startswith("negated"):
        return "it is negated and its definition has no not-box form"
    return "the unfolded pattern has no block form"


def check_grounds(clauses: str, support: str = "") -> None:
    """Raise unless ``clauses`` (with the definitions in ``support``) parse and ground."""
    import clingo

    ctl = clingo.Control(["--warn=none"], logger=lambda _code, _msg: None)
    ctl.add("base", [], support + "\n" + clauses)
    ctl.ground([("base", [])])


# ── clean-up of unfolded bodies ────────────────────────────────────────────


def _restore_anonymous(items, bound: set[str]) -> list:
    """``items`` with each variable that occurs only in negated literals turned back into
    ``_``. Unfolding renames every ``_`` of an inlined definition apart, which inside
    ``not …`` would make the clause unsafe."""
    bound = bound | set(
        ordered_vars([b for b in items if not (isinstance(b, Lit) and b.neg)])
    )

    def unbound_var(term: str) -> bool:
        return (term[:1].isupper() or term[:1] == "_") and term not in bound

    out = []
    for b in items:
        if isinstance(b, Lit) and b.neg:
            b = Lit(b.pred, tuple("_" if unbound_var(a) else a for a in b.args), True)
        elif isinstance(b, Agg):
            b = Agg(
                b.func,
                tuple(
                    AggElem(
                        e.terms,
                        tuple(
                            _restore_anonymous(
                                list(e.cond),
                                bound | set(ordered_vars([" ".join(e.terms)])),
                            )
                        ),
                    )
                    for e in b.elems
                ),
                b.lguard,
                b.rguard,
            )
        out.append(b)
    return out


def _drop_lonely_guards(head, body: list) -> list:
    """``body`` without ``has_atom(M, X)`` literals whose ``X`` is used nowhere else (an
    inlined definition's "the molecule has an atom" guard, an empty atom block in the
    editor), as long as another positive literal still binds ``M``."""
    mol = head.args[0] if head.args else None
    text = " ".join(map(str, [head] + body))

    def lonely(b) -> bool:
        return (
            isinstance(b, Lit)
            and not b.neg
            and b.pred == "has_atom"
            and len(b.args) == 2
            and b.args[0] == mol
            and b.args[1][:1].isupper()
            and _occurrences(b.args[1], text) == 1
        )

    kept = [b for b in body if not lonely(b)]
    binds_mol = any(isinstance(b, Lit) and not b.neg and mol in b.args for b in kept)
    if not binds_mol:  # keep exactly one guard so the clause stays safe
        guard = next((b for b in body if lonely(b)), None)
        kept = ([guard] if guard is not None else []) + kept
    return kept


def _negations_as_boxes(head, body: list, defs: dict, policy) -> list:
    """``body`` with each negated auxiliary literal whose definition the editor can draw
    replaced by "not" boxes: ``#count{ X,… : <definition body> } = 0`` ("no atoms X,…
    with …"), one per clause of the definition (``not (a ; b)`` is ``not a, not b``). A
    definition with no atoms of its own and a single molecule property becomes
    ``not p(M)``. Kept folded: definitions with aggregates or nested negated groups, ones
    that constrain the clause's own atoms (``c(X)`` on an outer ``X``), recursive ones."""
    mol = head.args[0] if head.args else None
    bound = set(
        ordered_vars(
            [head]
            + [
                b
                for b in body
                if not (isinstance(b, Lit) and b.neg) and not isinstance(b, Agg)
            ]
        )
    )
    taken = tuple(ordered_vars([head] + body))
    out = []
    for b in body:
        boxes = None
        if isinstance(b, Lit) and b.neg and b.pred in defs and mol:
            boxes = _neg_boxes(b, mol, bound, taken, defs, policy)
        out.extend(boxes if boxes is not None else [b])
    return out


def _is_var(t: str) -> bool:
    return t[:1].isupper() or t[:1] == "_"


def _neg_boxes(lit, mol: str, bound: set, taken: tuple, defs: dict, policy):
    anon = (f"_Anon{i}" for i in itertools.count(1))
    args = tuple(next(anon) if a == "_" else a for a in lit.args)
    call = Lit(lit.pred, args)
    # The helper head carries every variable of the clause, so unfolding renames the
    # definition's own variables apart from all of them.
    res = unfold([Clause(Lit("__neg", taken + args), [call])], defs, policy)
    if lit.pred in res.kept or "*" in res.kept:
        return None
    boxes = []
    for c in res.clauses:
        alt = list(dict.fromkeys(c.body))  # drop exact duplicates, keep order
        if not alt or any(isinstance(x, Lit) and x.pred == lit.pred for x in alt):
            return None
        own = [v for v in ordered_vars(alt) if v not in bound and v != mol]
        text = " ".join(map(str, alt))
        # "the molecule has an atom" guards over an atom used nowhere else
        alt = [
            x
            for x in alt
            if not (
                isinstance(x, Lit)
                and not x.neg
                and x.pred == "has_atom"
                and len(x.args) == 2
                and x.args[0] == mol
                and x.args[1] in own
                and _occurrences(x.args[1], text) == 1
            )
        ]
        own = [v for v in ordered_vars(alt) if v not in bound and v != mol]
        if not alt:
            return None
        for x in alt:
            if isinstance(x, Cmp):
                ok = (
                    x.op in ("!=", "<")
                    and _is_var(x.left)
                    and _is_var(x.right)
                    and mol not in (x.left, x.right)
                    and (x.left in own or x.right in own)
                )
            elif isinstance(x, Lit) and len(x.args) == 1:
                a = x.args[0]
                ok = a in own or (a == mol and not x.neg)
            elif isinstance(x, Lit) and len(x.args) == 2 and x.pred == "has_atom":
                ok = not x.neg and x.args[0] == mol and x.args[1] in own
            elif isinstance(x, Lit) and len(x.args) == 2:
                ok = all(_is_var(a) and a != mol for a in x.args) and any(
                    a in own for a in x.args
                )
            else:
                ok = False
            if not ok:
                return None
        if not own and len(alt) == 1:
            boxes.append(f"not {alt[0]}")
        else:
            terms = ",".join(own) if own else mol
            boxes.append(f"#count{{ {terms} : {', '.join(map(str, alt))} }} = 0")
    return boxes or None


def unfold_pred(defn: Definition, pred: str) -> tuple[str, str | None]:
    """``(rule, error)``: the main rule with only ``pred`` unfolded, and why it stayed
    folded (``None`` if it was unfolded)."""
    out = editor_rule(defn, pred)
    if not re.search(rf"(?<![A-Za-z0-9_]){re.escape(pred)}\s*\(", out):
        return out, None
    return out, f"Could not unfold {pred}: {unfold_failure(defn, pred)}."
