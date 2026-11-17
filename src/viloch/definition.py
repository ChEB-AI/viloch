"""Definitions: a rule plus the auxiliary predicates it relies on.

A definition is plain ASP text. The *main rule* is one or more clauses of the target
predicate (``chebi_<id>(M) :- …`` or ``concept(M) :- …``). Every other predicate the
text defines is an *auxiliary program*, optionally introduced by a header::

    concept(M) :- has_atom(M, A), o(A), aux_carboxy(M).

    % PREDICATE_NAME: aux_carboxy
    % DESCRIPTION: contains a carboxylic acid group
    aux_carboxy(M) :- has_atom(M, C), c(C), bDOUBLE(C, O), o(O), ...

Auxiliary predicates the text only *uses* can be filled in from a rule library
directory (chebILP's ``<dir>/programs/<name>.pl`` layout) with :meth:`Definition.resolve`.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, replace

_HEAD_RE = re.compile(r"^([a-z_][A-Za-z0-9_]*)\s*(?:\(|$)")
_HEADER_RE = re.compile(r"^%\s*(PREDICATE_NAME|DESCRIPTION)\s*:\s*(.+?)\s*$", re.I)
_CALL_RE = re.compile(r"(?<![A-Za-z0-9_])([a-z][A-Za-z0-9_]*)\s*\(")
_AUX_RE = re.compile(r"(?<![A-Za-z0-9_])(aux_[A-Za-z0-9_]+)\s*\(")


@dataclass(frozen=True)
class AuxProgram:
    """One auxiliary predicate: its clauses (``source``) and an English description."""

    name: str
    source: str
    description: str = ""

    def as_dict(self) -> dict:
        """The ``{"name", "description", "source"}`` form the explainer takes."""
        return {
            "name": self.name,
            "description": self.description,
            "source": self.source,
        }

    def to_text(self) -> str:
        head = f"% PREDICATE_NAME: {self.name}\n"
        if self.description:
            head += f"% DESCRIPTION: {self.description}\n"
        return head + self.source


@dataclass(frozen=True)
class Definition:
    """A main rule (clauses of ``target``) plus auxiliary programs."""

    rule: str
    aux: tuple[AuxProgram, ...] = field(default_factory=tuple)
    target: str | None = None

    # ── construction ───────────────────────────────────────────────────────

    @classmethod
    def parse(cls, text: str, target: str | None = None) -> Definition:
        """Split ``text`` into the main rule and auxiliary programs.

        The main rule is the clauses of ``target`` if given. Otherwise it is the one
        predicate no other clause uses; if that is ambiguous, the last predicate
        defined. Clauses keep their text (one line each); ``%`` comments other than
        the ``PREDICATE_NAME`` / ``DESCRIPTION`` headers are dropped.
        """
        order, groups = [], {}
        for clause in split_clauses(text or ""):
            head = clause_head(clause)
            if head is None:
                continue
            if head not in groups:
                groups[head] = []
                order.append(head)
            groups[head].append(clause)
        if not order:
            return cls("", (), target)
        main = target if target in groups else _main_predicate(order, groups)
        descriptions = header_descriptions(text)
        aux = tuple(
            AuxProgram(n, "\n".join(groups[n]), descriptions.get(n, ""))
            for n in order
            if n != main
        )
        return cls("\n".join(groups[main]), aux, target or main)

    @classmethod
    def from_file(cls, path: str, target: str | None = None) -> Definition:
        with open(path, encoding="utf-8") as fh:
            return cls.parse(fh.read(), target)

    # ── views ──────────────────────────────────────────────────────────────

    @property
    def defined(self) -> set[str]:
        return {p.name for p in self.aux}

    def programs(self) -> list[dict]:
        """The auxiliary programs as the explainer's ``{"name", "description", "source"}``."""
        return [p.as_dict() for p in self.aux]

    def programs_key(self) -> tuple[tuple[str, str], ...]:
        """``((name, source), …)``: a hashable key of the programs (for caching)."""
        return tuple((p.name, p.source) for p in self.aux)

    def used_aux(self) -> list[str]:
        """``aux_*`` predicates the rule or its programs use but do not define."""
        text = self.rule + "\n" + "\n".join(p.source for p in self.aux)
        return [
            n for n in dict.fromkeys(_AUX_RE.findall(text)) if n not in self.defined
        ]

    def to_text(self) -> str:
        """The definition as one program text (round-trips through :meth:`parse`)."""
        parts = [self.rule] + [p.to_text() for p in self.aux]
        return "\n\n".join(p for p in parts if p.strip()) + "\n"

    # ── transformations ────────────────────────────────────────────────────

    def with_rule(self, rule: str) -> Definition:
        return replace(self, rule=rule)

    def with_descriptions(self, descriptions: dict[str, str]) -> Definition:
        """Fill in missing aux descriptions from ``descriptions``."""
        return replace(
            self,
            aux=tuple(
                p
                if p.description
                else replace(p, description=descriptions.get(p.name, ""))
                for p in self.aux
            ),
        )

    def prune(self) -> Definition:
        """Only the auxiliary programs the main rule uses, directly or through other
        programs (e.g. after an edit removed a predicate)."""
        by_name = {p.name: p for p in self.aux}
        keep, todo = set(), [self.rule]
        while todo:
            for name in _CALL_RE.findall(todo.pop()):
                if name in by_name and name not in keep:
                    keep.add(name)
                    todo.append(by_name[name].source)
        return replace(self, aux=tuple(p for p in self.aux if p.name in keep))

    def resolve(self, library_dir: str | None, strict: bool = True) -> Definition:
        """Append the library programs of the ``aux_*`` predicates this definition uses
        but does not define, transitively (chebILP's ``resolve_rule_dependencies``).

        ``strict``: raise ``ValueError`` if predicates stay undefined (no library, or
        the library does not define them). Otherwise return what could be resolved,
        also when the library cannot be read.
        """
        missing = self.used_aux()
        if not missing:
            return self
        if library_dir is None or not os.path.isdir(library_dir):
            if not strict:
                return self
            raise ValueError(
                f"The rule uses {', '.join(missing)}, which it does not define; "
                "pass the aux library directory that defines them."
            )
        from chebILP.predicate_generation.auxiliary_rules import (
            RuleProgram,
            resolve_rule_dependencies,
        )

        source = self.rule + "\n" + "\n".join(p.source for p in self.aux)
        try:
            deps = resolve_rule_dependencies(
                [RuleProgram(name="__rule__", source=source)], library_dir
            )
        except OSError, ValueError:  # an unreadable library file
            if strict:
                raise
            return self
        extra, seen = [], set(self.defined)
        for d in deps:
            if d.name not in seen:
                seen.add(d.name)
                # Library sources carry their own header comments; the program keeps
                # the description separately, so only the clauses are kept.
                clauses = "\n".join(split_clauses(d.source))
                extra.append(AuxProgram(d.name, clauses, d.description or ""))
        resolved = replace(self, aux=self.aux + tuple(extra))
        still = resolved.used_aux()
        if still and strict:
            raise ValueError(
                f"{', '.join(still)} {'is' if len(still) == 1 else 'are'} not defined "
                f"in the definition or the library {library_dir}."
            )
        return resolved


# ── clause-level helpers ───────────────────────────────────────────────────


def split_clauses(text: str) -> list[str]:
    """Split a program into clauses on the ``.`` terminators at bracket depth 0 (so a
    ``.`` inside an aggregate or a range never splits), dropping ``%`` comment lines and
    collapsing each clause onto one line."""
    text = "\n".join(_strip_comment(line) for line in text.splitlines())
    depth, cur, clauses, quoted = 0, [], [], False
    for i, ch in enumerate(text):
        if ch == '"':
            quoted = not quoted
        elif not quoted and ch in "([{":
            depth += 1
        elif not quoted and ch in ")]}":
            depth = max(0, depth - 1)
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if ch == "." and depth == 0 and not quoted and nxt != ".":
            prev = text[i - 1] if i else ""
            if prev != ".":
                c = " ".join("".join(cur).split()).strip()
                if c:
                    clauses.append(c + ".")
                cur = []
                continue
        cur.append(ch)
    tail = " ".join("".join(cur).split()).strip()
    if tail:
        clauses.append(tail if tail.endswith(".") else tail + ".")
    return clauses


def clause_head(clause: str) -> str | None:
    """The head predicate of one clause, or ``None`` (constraint, unparseable head)."""
    m = _HEAD_RE.match(clause.split(":-", 1)[0].strip().rstrip("."))
    return m.group(1) if m else None


def header_descriptions(text: str) -> dict[str, str]:
    """``name -> description`` from ``% PREDICATE_NAME`` / ``% DESCRIPTION`` headers.

    A header may name the predicate without its ``aux_`` prefix (chebILP writes the
    name as the model gave it); the clauses always carry it, so both are recorded.
    """
    out, name = {}, None
    for line in (text or "").splitlines():
        m = _HEADER_RE.match(line.strip())
        if not m:
            continue
        if m.group(1).upper() == "PREDICATE_NAME":
            name = m.group(2)
        elif name:
            out[name] = m.group(2)
            if not name.startswith(("aux_", "efg_")):
                out.setdefault("aux_" + name, m.group(2))
    return out


def mentions(text: str, pred: str) -> bool:
    """Whether ``text`` has a literal of ``pred``."""
    return (
        re.search(rf"(?<![A-Za-z0-9_]){re.escape(pred)}\s*\(", text or "") is not None
    )


def _strip_comment(line: str) -> str:
    """``line`` without a ``%`` comment (outside string constants)."""
    quoted = False
    for i, ch in enumerate(line):
        if ch == '"':
            quoted = not quoted
        elif ch == "%" and not quoted:
            return line[:i]
    return line


def _main_predicate(order: list[str], groups: dict[str, list[str]]) -> str:
    used = set()
    for name in order:
        for clause in groups[name]:
            body = clause.split(":-", 1)[1] if ":-" in clause else ""
            used.update(n for n in _CALL_RE.findall(body) if n != name)
    roots = [n for n in order if n not in used]
    return roots[0] if len(roots) == 1 else order[-1]
