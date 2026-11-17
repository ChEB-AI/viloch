# CLAUDE.md

Guidance for working in this repo. Keep entries factual and present-tense.

## Environment

- Run repo Python through the project-local WSL venv `.wslvenv` (Python 3.14), never Windows
  Python. The agent's Bash tool is Git Bash, so invoke it through WSL:
  `wsl -e bash -lc 'cd /mnt/c/Users/sifluegel/PycharmProjects/viloch && .wslvenv/bin/python -m pytest -q'`.
- Node runs on Windows: `node --test tests/js/*.test.cjs` (a directory argument does not work).
- In Git Bash, `git show <rev>:<path>` needs `MSYS_NO_PATHCONV=1`.

## Structure

- `Definition` (`definition.py`) is the one parser of rule text + aux programs
  (`% PREDICATE_NAME` / `% DESCRIPTION` headers). `resolve(library_dir)` fills in library
  `aux_*` predicates via chebILP's `resolve_rule_dependencies` and raises for any left undefined.
- `logic/` and `explain/` are the explanation pipeline, copied from chebILP
  `feature/better-chebi-explanations` @ 802ccbc (chebILP keeps its own frozen copy). They still
  import chebILP core: `preprocessing.chebi.mol_to_fol` (molecule facts), `fg_matching` (FG seeds),
  `predicate_generation.auxiliary_rules` (library loading).
- `editor/asp.py` is the only ASP <-> editor-model conversion; the JS editor (`web/static/blocks.js`)
  has no parser or compiler and talks to the server. Its behaviour is pinned by the goldens in
  `tests/fixtures/editor/`, captured from icarus' original `blocks.js`.
- The explainer's unfolders (`logic/tagged.py`, `logic/display_logic.py`) read a count that
  must be zero (the editor's "not" box, `#count{…} = 0`) as a negation (`NegGroup`);
  `rule_ir.unfold` keeps it, because the editor's unfold view uses it.
- `logic/rule_ir.py` has no negated aggregates: `not #count{…} > 2` parses as
  `#count{…} <= 2`, and a negated two-sided count as two clauses (one per failing bound).

## Testing

- `tests/test_editor_semantics.py` grounds each fixture rule and its editor round trip on
  `tests/fixtures/molecules.tsv` and requires the same accepted molecules. Fixture rules must be
  safe ASP. `only_guard` and `not_count_*` goldens come from the Python converter (bug fixes
  over blocks.js), all others from blocks.js.
- Explanation tests check verdicts (`definitions/expected.tsv`) and that texts contain no rule
  syntax; no pixel comparisons.
