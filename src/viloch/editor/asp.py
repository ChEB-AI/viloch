"""ASP text <-> the block editor's model.

A rule is an OR of clauses. Each clause of the model is either drawn or raw::

    {"atoms": [...], "molChips": [...], "bonds": [...], "groups": [...]}
    {"rawClause": "<clause text>", "why": "<why it has no blocks>"}

- atom: ``{"id", "chips": [{"pred"}], "x", "y", "group"?, "counted"?, "bare"?}``
- molecule property: ``{"pred"}`` in ``molChips``
- bond: ``{"a", "b", "pred"}`` between two atom ids. ``pred`` is a binary predicate or
  one of the pseudo-predicates ``"!="`` / ``"<"`` (a comparison of the two atoms).
- negation: a chip or bond whose ``pred`` starts with ``"not "``
- group: a "not" or "count" box ``{"id", "kind", "op"?, "n"?, "n2"?, "molChips",
  "inMol"?, "x", "y", "w", "h"}``; its atoms carry ``"group": <id>``.

Variables are not stored: :func:`to_asp` names the molecule ``V0`` and atom *i* ``V<i+1>``.
See ``model.schema.json`` for the full schema.

:func:`from_asp` parses with clingo's AST (via :mod:`viloch.logic.rule_ir`), one clause
at a time, so a clause the editor cannot draw stays raw with the reason, and the rest
still becomes blocks.
"""

from __future__ import annotations

import itertools
import math

from viloch.definition import split_clauses
from viloch.logic.rule_ir import Agg, Cmp, Lit, parse_program

DEFAULT_TARGET = "concept"
NEQ = "!="
LT = "<"
COUNT_OPS = ("=", ">=", "<=", ">", "<", "between")
_FLIP = {"=": "=", "!=": "!=", "<": ">", "<=": ">=", ">": "<", ">=": "<="}


def _is_var(a: str) -> bool:
    return bool(a) and (a[0].isupper() or a[0] == "_") and a.replace("_", "a").isalnum()


def _is_int(a: str) -> bool:
    return a.lstrip("-").isdigit() and a.count("-") <= 1


# ── compile: model -> ASP ──────────────────────────────────────────────────


def to_asp(model: dict, target: str = DEFAULT_TARGET) -> str:
    """The ASP text of an editor model, one clause per line."""
    if not model or not model.get("clauses"):
        return ""
    lines = []
    for cl in model["clauses"]:
        if cl.get("rawClause") is not None:
            lines.append(cl["rawClause"].strip())
            continue
        line = compile_clause(cl, target)
        if line:
            lines.append(line)
    return "\n".join(lines)


def compile_clause(cl: dict, target: str = DEFAULT_TARGET) -> str | None:
    atoms = cl.get("atoms") or []
    groups = cl.get("groups") or []
    by_id = {g["id"]: g for g in groups}
    var_of, group_of_atom = {}, {}
    for i, a in enumerate(atoms):
        var_of[a["id"]] = f"V{i + 1}"
        group_of_atom[a["id"]] = a.get("group") if a.get("group") in by_id else None

    def bond_lit(b):
        if b["pred"] in (NEQ, LT):
            return f"{var_of[b['a']]} {b['pred']} {var_of[b['b']]}"
        return f"{b['pred']}({var_of[b['a']]},{var_of[b['b']]})"

    bonds = [b for b in cl.get("bonds") or [] if b["a"] in var_of and b["b"] in var_of]

    def positive(p):
        return p not in (NEQ, LT) and not p.startswith("not ")

    def bond_scope(b):  # a bond is written in the scope of its boxed end, if any
        return group_of_atom[b["a"]] or group_of_atom[b["b"]] or None

    def atom_lits(a):
        chips = [f"{ch['pred']}({var_of[a['id']]})" for ch in a.get("chips") or []]
        # A bare atom (no has_atom in the source rule) keeps going without one while a
        # positive chip or bond in its scope binds it.
        bound = any(positive(ch["pred"]) for ch in a.get("chips") or []) or any(
            a["id"] in (b["a"], b["b"])
            and positive(b["pred"])
            and bond_scope(b) == group_of_atom[a["id"]]
            for b in bonds
        )
        if a.get("bare") and bound:
            return chips
        return [f"has_atom(V0,{var_of[a['id']]})", *chips]

    lits = []
    for a in atoms:
        if not group_of_atom[a["id"]]:
            lits += atom_lits(a)
    lits += [f"{ch['pred']}(V0)" for ch in cl.get("molChips") or []]
    lits += [
        bond_lit(b)
        for b in bonds
        if not group_of_atom[b["a"]] and not group_of_atom[b["b"]]
    ]
    binds_mol = any(not lit.startswith("not ") and _mentions_v0(lit) for lit in lits)

    aggs = []
    # Molecule-level nots first: the order the parser reads them back in.
    ordered = [g for g in groups if g.get("inMol")] + [
        g for g in groups if not g.get("inMol")
    ]
    for g in ordered:
        members = [a for a in atoms if group_of_atom[a["id"]] == g["id"]]
        cond = []
        for a in members:
            cond += atom_lits(a)
        cond += [f"{ch['pred']}(V0)" for ch in g.get("molChips") or []]
        for b in bonds:
            ga, gb = group_of_atom[b["a"]], group_of_atom[b["b"]]
            if g["id"] in (ga, gb) and (not ga or not gb or ga == gb):
                cond.append(bond_lit(b))
        if not cond:
            continue
        if g.get("kind") == "not":
            if not members and len(cond) == 1 and not cond[0].startswith("not "):
                aggs.append(f"not {cond[0]}")
            else:
                terms = ",".join(var_of[a["id"]] for a in members) if members else "V0"
                aggs.append(f"#count{{ {terms} : {', '.join(cond)} }} = 0")
            continue
        if not members:
            continue
        counted = [a for a in members if a.get("counted")]
        terms = ",".join(var_of[a["id"]] for a in (counted or members))
        agg = f"#count{{ {terms} : {', '.join(cond)} }}"
        n = _int(g.get("n"))
        if g.get("op") == "between":
            aggs.append(f"{n} <= {agg} <= {max(n, _int(g.get('n2')))}")
        else:
            op = g.get("op") if g.get("op") in COUNT_OPS else "="
            aggs.append(f"{agg} {op} {n}")
    if not lits and not aggs:
        return None
    if not binds_mol:  # something positive has to bind the molecule (ASP safety)
        lits.insert(0, "has_atom(V0,_)")
    return f"{target}(V0) :- {', '.join(lits + aggs)}."


def _mentions_v0(lit: str) -> bool:
    import re

    return re.search(r"\bV0\b", lit) is not None


def _int(v) -> int:
    """``parseInt(v, 10) || 0``: a leading integer, else 0."""
    if isinstance(v, bool):
        return 0
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return 0 if math.isnan(v) else int(v)
    import re

    m = re.match(r"\s*([+-]?\d+)", str(v or ""))
    return int(m.group(1)) if m else 0


# ── parse: ASP -> model ────────────────────────────────────────────────────


class _Unsupported(Exception):
    """A clause the editor has no blocks for; the message is shown to the user."""


def from_asp(text: str, target: str = DEFAULT_TARGET) -> dict:
    """The editor model of ``text``. Clauses without a body (facts) are skipped."""
    model = {"clauses": []}
    ids = itertools.count(1)
    for clause_text in split_clauses(text or ""):
        if ":-" not in clause_text:
            continue
        try:
            model["clauses"].append(_parse_clause(clause_text, target, ids))
        except _Unsupported as e:
            model["clauses"].append({"rawClause": clause_text.strip(), "why": str(e)})
    return model


def _parse_clause(text: str, target: str, ids) -> dict:
    try:
        clauses = parse_program(text)
    except Exception as e:  # clingo syntax error, unsupported construct
        raise _Unsupported(f"it could not be parsed ({_short(e)})") from None
    if len(clauses) > 1:  # "not L <= #count{…} <= U": count < L or count > U
        raise _Unsupported("a “not” before a count with two bounds is an “or”")
    if len(clauses) != 1:
        raise _Unsupported("it is not a rule with a head")
    clause = clauses[0]
    head = clause.head
    if head.pred != target or not head.args or head.neg:
        raise _Unsupported(f"its head is not {target}(M)")
    anon = itertools.count(1)
    literals = [_body_literal(b, anon) for b in clause.body]
    return _structure(head.args[0], literals, ids)


def _short(e: Exception) -> str:
    msg = str(e).strip().splitlines()
    return msg[0][:80] if msg else type(e).__name__


def _plain(pred: str, args, neg: bool, anon) -> dict:
    args = [f"_Anon{next(anon)}" if a == "_" else a for a in args]
    return {"pred": ("not " + pred) if neg else pred, "args": args, "neg": neg}


def _body_literal(item, anon, in_aggregate: bool = False) -> dict:
    """``{pred, args, neg}`` for one body item; flags ``agg`` / ``cmpConst`` /
    ``unsupported`` mark the special cases (as blocks.js did)."""
    if isinstance(item, Lit):
        return _plain(item.pred, item.args, item.neg, anon)
    if isinstance(item, Cmp):
        left, op, right = item.left, item.op, item.right
        if op in (NEQ, LT) and _is_var(left) and _is_var(right):
            return {"pred": op, "args": [left, right], "neg": False}
        if not in_aggregate:
            if _is_var(left) and left != "_" and _is_int(right):
                return _cmp_const(item, left, op, int(right))
            if _is_int(left) and _is_var(right) and right != "_":
                return _cmp_const(item, right, _FLIP[op], int(left))
        return _unsupported(str(item))
    if isinstance(item, Agg) and not in_aggregate:
        return _aggregate(item, anon)
    return _unsupported(str(item))


def _cmp_const(item, v: str, op: str, n: int) -> dict:
    return {
        "cmpConst": True,
        "v": v,
        "op": op,
        "n": n,
        "pred": str(item),
        "args": [],
        "neg": False,
    }


def _unsupported(text: str) -> dict:
    return {"pred": text, "args": [], "neg": False, "unsupported": True}


def _aggregate(agg: Agg, anon) -> dict:
    """``[N op] #count{ T,… : cond } [op M]`` -> ``{agg, terms, cond, op, n, n2}``, with
    the guard normalised to ``#count op n`` (or ``between``: n <= count <= n2). A count
    assigned to a variable (``N = #count{…}``) comes back with ``guardVar``."""
    bad = _unsupported(str(agg))
    if agg.func != "count" or len(agg.elems) != 1:
        return bad
    elem = agg.elems[0]
    terms = list(elem.terms)
    cond = [_body_literal(c, anon, in_aggregate=True) for c in elem.cond]
    if not terms or not cond or any(c.get("unsupported") for c in cond):
        return bad
    base = {
        "agg": True,
        "terms": terms,
        "cond": cond,
        "pred": "#count",
        "args": [],
        "neg": False,
    }
    lg, rg = agg.lguard, agg.rguard
    for guard, other in ((lg, rg), (rg, lg)):
        if guard and other is None and guard[0] == "=" and _is_var(guard[1]):
            return {**base, "guardVar": guard[1]}
    if lg is None and rg is None:
        return bad
    if lg and not _is_int(lg[1]) or rg and not _is_int(rg[1]):
        return bad
    if lg and rg:
        if lg[0] not in ("<", "<=") or rg[0] not in ("<", "<="):
            return bad
        op = "between"
        n = int(lg[1]) + (1 if lg[0] == "<" else 0)
        n2 = int(rg[1]) - (1 if rg[0] == "<" else 0)
        return {**base, "op": op, "n": n, "n2": n2}
    if lg:
        op, n = _FLIP[lg[0]], int(lg[1])
    else:
        op, n = rg[0], int(rg[1])
    if op == "!=":
        return bad
    return {**base, "op": op, "n": n}


def _key(lit: dict) -> str:
    return f"{lit['pred']}({','.join(lit['args'])})"


def _structure(mol_var: str, literals: list[dict], ids) -> dict:
    """The block model of one parsed clause; raises ``_Unsupported`` when it uses
    something the block grammar cannot place."""
    odd = next((x for x in literals if x.get("unsupported")), None)
    if odd:
        raise _Unsupported(f"no block for “{odd['pred']}”")

    # "N = #count{…}, N >= 2, N <= 5": the comparisons on N bound the count.
    aggs = [x for x in literals if x.get("agg")]
    for agg in [g for g in aggs if g.get("guardVar")]:
        v = agg["guardVar"]
        cmps = [x for x in literals if x.get("cmpConst") and x["v"] == v]
        used_elsewhere = any(
            x not in cmps
            and x is not agg
            and (
                v in x["args"]
                or (
                    x.get("agg")
                    and (v in x["terms"] or any(v in c["args"] for c in x["cond"]))
                )
            )
            for x in literals
        )
        if used_elsewhere or not cmps:
            raise _Unsupported(f"the count {v} is used in arithmetic")
        lo, hi = -math.inf, math.inf
        for c in cmps:
            op, n = c["op"], c["n"]
            if op == "=":
                lo, hi = max(lo, n), min(hi, n)
            elif op == ">=":
                lo = max(lo, n)
            elif op == ">":
                lo = max(lo, n + 1)
            elif op == "<=":
                hi = min(hi, n)
            elif op == "<":
                hi = min(hi, n - 1)
            else:
                raise _Unsupported(f"the count {v} is compared with {op}")
        if lo == hi:
            agg.update(op="=", n=lo)
        elif lo > -math.inf and hi < math.inf:
            agg.update(op="between", n=lo, n2=hi)
        elif lo > -math.inf:
            agg.update(op=">=", n=lo)
        else:
            agg.update(op="<=", n=hi)
        for c in cmps:
            c["consumed"] = True
    loose = next(
        (x for x in literals if x.get("cmpConst") and not x.get("consumed")), None
    )
    if loose:
        raise _Unsupported(f"no block for “{loose['pred']}”")
    plain = [x for x in literals if not x.get("agg") and not x.get("cmpConst")]

    bound = {mol_var}
    for x in plain:
        if not x["neg"] and x["pred"] not in (NEQ, LT):
            bound.update(x["args"])
    # "not p(X, _)" over an atom no positive literal binds: "no such atom" -> a not box.
    kept = []
    for x in plain:
        if not x["neg"] or all(a in bound for a in x["args"]):
            kept.append(x)
            continue
        aggs.append(
            {
                "agg": True,
                "op": "=",
                "n": 0,
                "terms": [a for a in x["args"] if a not in bound],
                "cond": [{"pred": x["pred"][4:], "args": x["args"], "neg": False}],
            }
        )
    plain = kept

    # has_atom(M, X) with X used nowhere else only says "the molecule has an atom".
    uses: dict[str, int] = {}
    for x in plain:
        for a in x["args"]:
            uses[a] = uses.get(a, 0) + 1
    for g in aggs:
        for a in g["terms"] + [a for c in g["cond"] for a in c["args"]]:
            uses[a] = uses.get(a, 0) + 1

    def lonely_guard(x):
        return (
            x["pred"] == "has_atom"
            and not x["neg"]
            and len(x["args"]) == 2
            and x["args"][0] == mol_var
            and uses.get(x["args"][1]) == 1
        )

    main_keys = {_key(x) for x in plain if not x["neg"]}

    # Variables the clause never puts in has_atom(M, X) (e.g. the element E of
    # aux_atom_element(X, E)) become "bare" atoms: compiled without a has_atom while
    # another positive literal binds them, so the clause keeps its meaning.
    guarded = set()
    for x in plain + [c for g in aggs for c in g["cond"]]:
        if x["pred"] == "has_atom" and not x["neg"] and x["args"][:1] == [mol_var]:
            if len(x["args"]) > 1:
                guarded.add(x["args"][1])

    atoms, mol_chips, bonds, groups = [], [], [], []
    outer_atom: dict[str, dict] = {}

    def new_id() -> str:
        return f"a{next(ids)}"

    def atom_for(scope: dict, v: str, group: dict | None = None) -> dict:
        if v not in scope:
            a = {"id": new_id(), "chips": [], "x": 24 + len(atoms) * 172, "y": 20}
            if group:
                a["group"] = group["id"]
            if v not in guarded:
                a["bare"] = True
            scope[v] = a
            atoms.append(a)
        return scope[v]

    def new_group(**props) -> dict:
        g = {"id": new_id(), "molChips": [], "x": 0, "y": 0, "w": 0, "h": 0, **props}
        groups.append(g)
        return g

    def constant(x):
        return _Unsupported(f"“{_key(x)}” has a constant argument")

    def not_atom(x):
        return _Unsupported(f"“{_key(x)}” is not an atom of the molecule {mol_var}")

    def mol_value(x):
        return _Unsupported(f"“{_key(x)}” relates the molecule to a value")

    # A clause of nothing but guards ("concept(M) :- has_atom(M,_).") keeps one atom:
    # with none it would compile to nothing.
    only_guards = not aggs and all(lonely_guard(x) for x in plain)

    # Main pattern.
    for x in plain:
        pred, args, neg = x["pred"], x["args"], x["neg"]
        if lonely_guard(x):
            if only_guards and not atoms:
                atom_for(outer_atom, args[1])
            continue
        if not all(_is_var(a) for a in args):
            raise constant(x)
        if pred == "has_atom":
            if neg or len(args) != 2 or args[0] != mol_var or args[1] == mol_var:
                raise not_atom(x)
            atom_for(outer_atom, args[1])
        elif len(args) == 1:
            if args[0] != mol_var:
                atom_for(outer_atom, args[0])["chips"].append({"pred": pred})
            elif neg:
                new_group(kind="not", inMol=True)["molChips"].append({"pred": pred[4:]})
            else:
                mol_chips.append({"pred": pred})
        elif len(args) == 2:
            if mol_var in args:
                raise mol_value(x)
            a, b = atom_for(outer_atom, args[0]), atom_for(outer_atom, args[1])
            bonds.append({"a": a["id"], "b": b["id"], "pred": pred})
        else:
            raise _Unsupported(f"“{pred}” has {len(args)} arguments")

    # Boxes: each aggregate's own variables are its atoms.
    for agg in aggs:
        own: list[str] = []
        for c in agg["cond"]:
            for a in c["args"]:
                if a != mol_var and a not in bound and a not in own:
                    own.append(a)
        is_not = agg["op"] == "=" and agg["n"] == 0
        kind = "not" if is_not else "count"
        if not is_not and not own:
            raise _Unsupported("a count without atoms of its own")
        if not is_not and any(t not in own for t in agg["terms"]):
            raise _Unsupported("a count of something other than its atoms")
        if is_not:
            g = new_group(kind=kind, inMol=not own)
        else:
            extra = {"n2": agg["n2"]} if agg.get("n2") is not None else {}
            g = new_group(kind=kind, op=agg["op"], n=agg["n"], **extra)
        scope: dict[str, dict] = {}
        for v in own:
            a = atom_for(scope, v, g)
            if not is_not:
                a["counted"] = v in agg["terms"]

        def atom_of(v, scope=scope):
            return scope.get(v) or outer_atom.get(v)

        for c in agg["cond"]:
            pred, args, neg = c["pred"], c["args"], c["neg"]
            if not neg and _key(c) in main_keys:
                continue  # repeats the main pattern
            if not all(_is_var(a) for a in args):
                raise constant(c)
            if pred == "has_atom":
                if neg or len(args) != 2 or args[0] != mol_var or args[1] not in scope:
                    raise not_atom(c)
            elif len(args) == 1:
                if args[0] in scope:
                    scope[args[0]]["chips"].append({"pred": pred})
                elif args[0] == mol_var and not neg:
                    g["molChips"].append({"pred": pred})
                else:
                    raise _Unsupported(
                        f"“{_key(c)}” in a {kind} box constrains an atom outside it"
                    )
            elif len(args) == 2:
                if mol_var in args:
                    raise mol_value(c)
                if not any(a in scope for a in args) or not all(
                    atom_of(a) for a in args
                ):
                    raise _Unsupported(
                        f"“{_key(c)}” in a {kind} box does not involve its atoms"
                    )
                bonds.append(
                    {
                        "a": atom_of(args[0])["id"],
                        "b": atom_of(args[1])["id"],
                        "pred": pred,
                    }
                )
            else:
                raise _Unsupported(f"“{pred}” has {len(args)} arguments")
    return {
        "atoms": atoms,
        "molChips": mol_chips,
        "bonds": bonds,
        "groups": groups,
        "_needsLayout": True,
    }
