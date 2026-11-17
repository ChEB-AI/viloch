# viloch

Visualise chemical logic rules. A *definition* is an ASP rule over molecules (atoms,
bonds, element and charge properties, as produced by chebILP / chebi-utils) plus the
auxiliary predicates it relies on. viloch

- **explains** definitions: a *global* explanation (what the rule asks of a molecule:
  a pattern picture and one or two sentences) and a *local* explanation (why the rule
  accepts or rejects one molecule: the molecule with the match, or the closest match,
  highlighted);
- **edits** them as building blocks: a drag-and-drop editor (atoms, bonds, molecule
  properties, "not" and "count" boxes) that converts to and from ASP text.

It is used standalone (CLI, web page) and inside [icarus](https://github.com/sfluegel05/icarus).

## Install

Python ≥ 3.14 (the version chebILP needs), Linux or WSL:

```bash
uv venv --python 3.14 && uv pip install -e ".[web,dev]"
```

`web` adds the editor server (Starlette, uvicorn); `dev` the test tools; `e2e` Playwright
for the browser tests.

## Definitions

```prolog
% the main rule: clauses of one predicate (here the ChEBI class 33575)
chebi_33575(M) :- aux_carboxy_group(M).

% auxiliary predicates, each optionally with a header
% PREDICATE_NAME: aux_carboxy_group
% DESCRIPTION: contains a carboxy group, C(=O)O
aux_carboxy_group(M) :- has_atom(M,C), c(C), has_atom(M,O1), o(O1), bDOUBLE(C,O1),
    has_atom(M,O2), o(O2), bSINGLE(C,O2).
```

The main rule is the predicate no other clause uses (or `--target`). `aux_*` predicates
the text uses but does not define are read from a rule library (`--library DIR`, chebILP's
`DIR/programs/<name>.pl` layout). `efg_*` predicates are Extended Functional Groups,
matched with RDKit.

## CLI

```bash
viloch explain-rule def.lp -o rule.png                     # global explanation
viloch explain-molecule def.lp --smiles "CC(=O)O" --name "acetic acid" -o why.png
viloch explain-molecule def.lp --batch molecules.tsv --out-dir out/ --json
viloch convert def.lp --to model > model.json              # ASP -> editor model
viloch convert model.json --to asp                         # editor model -> ASP
viloch serve --port 8000 [--library DIR]                   # the standalone editor page
```

`--chebi-graph chebi_graph.pkl` (or `--class-name`) names the class in the texts.

## Python

```python
from viloch import Definition, explain_rule, explain_molecule

defn = Definition.from_file("def.lp")
expl = explain_molecule("CC(=O)O", defn, name="acetic acid")
print(expl.fires, expl.text)
expl.image.save("why.png")

from viloch.editor.asp import from_asp, to_asp     # ASP <-> editor model
```

## Web

`viloch serve` shows an ASP text pane next to the block editor; edits on either side
update the other (through the server, which owns the ASP <-> model conversion).

Other apps reuse the pieces:

- `viloch.web.api.make_routes(library_dir, target)`: the JSON API (parse, compile,
  unfold, catalog, search, explain) as Starlette routes to mount anywhere;
- `viloch.web.app.static_files()`: `blocks.js` / `blocks.css`. The editor is
  `Blocks.init({palette, canvas, onChange, searchAux?, unfold?, notify?})`,
  `Blocks.setCatalog(catalog, aux)`, `Blocks.load(model)`, `Blocks.getModel()`.

The model is documented in `src/viloch/editor/model.schema.json`.

## Layout

| Package | Contents |
|---|---|
| `viloch.definition` | `Definition`: rule + aux programs; parsing, library resolution |
| `viloch.logic` | rule IR (clingo AST), unfolding of aux predicates |
| `viloch.explain` | the explanation pipeline (patterns, near misses, drawing, text) |
| `viloch.chem` | EFG functional groups (packaged tables) |
| `viloch.editor` | ASP <-> editor model, unfolding for the editor, palette catalogue |
| `viloch.web` | HTTP API, standalone app, editor assets |

The explanation pipeline started in chebILP (`feature/better-chebi-explanations`); chebILP
core still provides the molecule facts, functional-group seeds and library loading.

## Tests

```bash
pytest                       # unit, golden, semantic and explanation tests
pytest -m e2e tests/e2e      # browser tests (playwright install chromium)
node --test tests/js/*.test.cjs
```

`tests/fixtures/editor/*.{model.json,compiled.lp}` are goldens captured from the original
JS editor (`node tests/js/capture_goldens.cjs <blocks.js>`); the Python conversion must
match them, and a round trip through the editor must accept the same molecules
(`tests/test_editor_semantics.py`). Where the Python converter fixes a bug of the JS one
(`only_guard`, `not_count_*`), the golden was written by the Python converter instead.
