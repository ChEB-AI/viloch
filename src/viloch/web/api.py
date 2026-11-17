"""The block editor's HTTP API (JSON), as Starlette routes.

``make_routes()`` is mounted by the standalone app (:mod:`viloch.web.app`) and can be
mounted by other apps (icarus) next to their own endpoints.

- ``POST parse``      ``{definition, target?, unfold?}`` -> ``{target, model, aux, blocks}``
- ``POST compile``    ``{model, aux?, target?}`` -> ``{rule, definition}``
- ``POST unfold``     ``{clause, pred, aux?, target?}`` -> ``{model, aux}`` or ``{error}``
- ``GET  catalog``    -> ``{catalog, target}``: the static palette blocks
- ``GET  search``     ``?q=&offset=`` -> ``{results, total}``: library + EFG predicates
- ``POST explain/rule``      ``{definition}`` -> ``{text, image}``
- ``POST explain/molecule``  ``{definition, molecule, name?}`` -> ``{fires, text, image}``

``definition`` is ASP text (a rule plus auxiliary programs); ``aux`` is a list of
``{name, description, source}``; ``image`` is a PNG data URL. Errors are
``{error}`` with status 400 (bad input), 422 (input the pipeline cannot use) or 500.
"""

from __future__ import annotations

import re
import traceback

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from viloch.definition import AuxProgram, Definition
from viloch.editor import asp, catalog
from viloch.editor.unfold import editor_rule, unfold_pred

MAX_RULE_CHARS = 20_000

# Interval terms ("1..1000000000") outside comments: a one-line way to make clingo
# ground an enormous program. No library program or learned rule uses them.
_INTERVAL_RE = re.compile(
    r"^[^%\n]*(?:\d|[A-Z_]\w*|\))\s*\.\.\s*(?:\d|[A-Z_(-])", re.MULTILINE
)
_PRED_RE = re.compile(r"[a-z]\w{0,200}")


class BadRequest(ValueError):
    """A client input that is refused; the message is shown to the user."""


def check_rule_text(text, what: str = "rule", max_chars: int = MAX_RULE_CHARS) -> str:
    """``text`` stripped, or ``BadRequest``: it must be a string of bounded size
    without interval terms, since it is grounded with clingo."""
    if text is None:
        return ""
    if not isinstance(text, str):
        raise BadRequest(f"The {what} must be text.")
    if len(text) > max_chars:
        raise BadRequest(f"The {what} is too long (at most {max_chars} characters).")
    if _INTERVAL_RE.search(text):
        raise BadRequest("Intervals (a..b) are not supported in rules.")
    return text.strip()


def aux_programs(items) -> tuple[AuxProgram, ...]:
    """Client-sent ``[{name, description, source}]`` as checked programs."""
    if not items:
        return ()
    bad = BadRequest("aux must be a list of {name, description, source}.")
    if not isinstance(items, list):
        raise bad
    out = []
    for p in items:
        if not isinstance(p, dict) or not isinstance(p.get("name"), str):
            raise bad
        if not _PRED_RE.fullmatch(p["name"]):
            raise BadRequest("Bad auxiliary predicate name.")
        source = check_rule_text(p.get("source"), "auxiliary program")
        out.append(AuxProgram(p["name"], source, str(p.get("description") or "")))
    return tuple(out)


def _target(body: dict, default: str) -> str:
    t = body.get("target") or default
    if not isinstance(t, str) or not _PRED_RE.fullmatch(t):
        raise BadRequest("Bad target predicate name.")
    return t


def _model(value) -> dict:
    if not isinstance(value, dict) or not isinstance(value.get("clauses"), list):
        raise BadRequest("model must be an object with a list of clauses.")
    if not all(isinstance(c, dict) for c in value["clauses"]):
        raise BadRequest("Each clause of the model must be an object.")
    return value


def _compile(model: dict, target: str) -> str:
    try:
        return asp.to_asp(model, target)
    except (KeyError, TypeError, AttributeError) as e:
        raise BadRequest(f"Malformed editor model ({type(e).__name__}: {e}).") from None


def make_routes(library_dir: str | None = None, target: str = "concept") -> list[Route]:
    """The editor API routes. ``library_dir``: the aux rule library that resolves
    ``aux_*`` predicates a definition uses but does not define (optional);
    ``target``: the head predicate of edited rules unless a request names one."""

    def definition_of(body: dict) -> Definition:
        text = check_rule_text(body.get("definition"), "definition")
        defn = Definition.parse(text, body.get("target") and _target(body, target))
        return defn if defn.rule else Definition("", defn.aux, _target(body, target))

    def parse(body: dict) -> dict:
        defn = definition_of(body)
        rule = defn.rule
        if body.get("unfold"):
            rule = editor_rule(defn.resolve(library_dir))
        return {
            "target": defn.target,
            "model": asp.from_asp(rule, defn.target),
            "aux": defn.programs(),
            "blocks": catalog.definition_blocks(defn, library_dir),
        }

    def compile_(body: dict) -> dict:
        t = _target(body, target)
        rule = _compile(_model(body.get("model")), t)
        defn = Definition(rule, aux_programs(body.get("aux")), t).prune()
        return {"rule": rule, "definition": defn.to_text()}

    def unfold(body: dict) -> dict:
        t = _target(body, target)
        pred = body.get("pred")
        if not isinstance(pred, str) or not _PRED_RE.fullmatch(pred):
            raise BadRequest("Bad predicate name.")
        clause = body.get("clause")
        if not isinstance(clause, dict):
            raise BadRequest("clause must be an editor clause.")
        rule = _compile({"clauses": [clause]}, t)
        if not rule:
            raise BadRequest("The clause is empty.")
        defn = Definition(rule, aux_programs(body.get("aux")), t).resolve(library_dir)
        out, error = unfold_pred(defn, pred)
        if error:
            return {"error": error}
        return {"model": asp.from_asp(out, t), "aux": defn.programs()}

    def class_name(body: dict) -> str | None:
        name = body.get("class_name")
        return name if isinstance(name, str) and name.strip() else None

    def explain_rule(body: dict) -> dict:
        from viloch.api import as_json
        from viloch.api import explain_rule as _explain

        expl = _explain(
            definition_of(body), library_dir=library_dir, class_name=class_name(body)
        )
        return as_json(expl)

    def explain_molecule(body: dict) -> dict:
        from viloch.api import as_json
        from viloch.api import explain_molecule as _explain

        molecule = body.get("molecule")
        if not isinstance(molecule, str) or not molecule.strip():
            raise BadRequest("molecule must be a SMILES, InChI or molblock.")
        if len(molecule) > 100_000:
            raise BadRequest("The molecule is too large.")
        name = body.get("name") if isinstance(body.get("name"), str) else None
        expl = _explain(
            molecule,
            definition_of(body),
            library_dir=library_dir,
            name=name or None,
            class_name=class_name(body),
        )
        return as_json(expl)

    def post(fn):
        async def endpoint(request: Request):
            try:
                body = await request.json()
            except ValueError:
                return JSONResponse({"error": "The request body must be JSON."}, 400)
            if not isinstance(body, dict):
                return JSONResponse(
                    {"error": "The request body must be an object."}, 400
                )
            try:
                return JSONResponse(await run_in_threadpool(fn, body))
            except BadRequest as e:
                return JSONResponse({"error": str(e)}, 400)
            except ValueError as e:  # unparseable molecule, missing library, …
                return JSONResponse({"error": str(e)}, 422)
            except Exception as e:  # noqa: BLE001 - reported to the client
                traceback.print_exc()
                return JSONResponse({"error": f"{type(e).__name__}: {e}"}, 500)

        return endpoint

    async def get_catalog(request: Request):
        return JSONResponse({"catalog": catalog.catalog(), "target": target})

    async def search(request: Request):
        q = request.query_params.get("q", "")[:200]
        try:
            offset = max(0, int(request.query_params.get("offset", "0")))
        except ValueError:
            offset = 0
        results, total = await run_in_threadpool(
            catalog.search_aux_blocks, library_dir, q, 50, offset
        )
        return JSONResponse({"results": results, "total": total})

    return [
        Route("/parse", post(parse), methods=["POST"]),
        Route("/compile", post(compile_), methods=["POST"]),
        Route("/unfold", post(unfold), methods=["POST"]),
        Route("/catalog", get_catalog, methods=["GET"]),
        Route("/search", search, methods=["GET"]),
        Route("/explain/rule", post(explain_rule), methods=["POST"]),
        Route("/explain/molecule", post(explain_molecule), methods=["POST"]),
    ]
