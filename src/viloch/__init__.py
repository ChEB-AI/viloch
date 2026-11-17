"""viloch: visualise chemical logic rules.

- :func:`explain_rule` / :func:`explain_molecule`: global and local explanations of a
  :class:`Definition` (a rule plus its auxiliary predicates).
- :mod:`viloch.editor`: ASP text <-> the block editor's model.
- :mod:`viloch.web`: the editor's HTTP API and static assets (``viloch serve``).
"""

from viloch.definition import AuxProgram, Definition

__all__ = ["AuxProgram", "Definition", "explain_molecule", "explain_rule"]


def __getattr__(name):  # explanations pull in RDKit/PIL: import them on first use
    if name in ("explain_rule", "explain_molecule"):
        from viloch import api

        return getattr(api, name)
    raise AttributeError(name)
