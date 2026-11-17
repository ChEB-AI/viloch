"""High-level entry points: explanations of a :class:`~viloch.definition.Definition`."""

from __future__ import annotations

import base64
import io
import pickle

from viloch.definition import Definition


def as_definition(
    definition: Definition | str, target: str | None = None
) -> Definition:
    """``definition``, parsed if it is text (:meth:`Definition.parse`)."""
    if isinstance(definition, Definition):
        return definition
    return Definition.parse(definition, target)


def prepare(
    definition: Definition | str, library_dir: str | None = None, strict: bool = True
) -> Definition:
    """The definition ready for the explainer: library predicates filled in (see
    :meth:`Definition.resolve` for ``strict``), and the EFG matcher installed."""
    from viloch.chem import efg

    efg.install()
    return as_definition(definition).resolve(library_dir, strict)


def load_chebi_graph(path: str | None):
    """The pickled ChEBI graph (networkx, nodes = ids with a ``name``), or None."""
    if not path:
        return None
    with open(path, "rb") as fh:
        return pickle.load(fh)


def explain_rule(
    definition: Definition | str,
    *,
    library_dir: str | None = None,
    strict: bool = True,
    chebi_graph=None,
    class_name: str | None = None,
):
    """Global explanation: what the definition's rule asks of a molecule.

    Returns an :class:`~viloch.explain.explain.Explanation` (``text``, ``image``).
    """
    from viloch.explain.explain import explain_rule as _explain_rule

    defn = prepare(definition, library_dir, strict)
    return _explain_rule(
        defn.rule,
        chebi_graph=chebi_graph,
        aux_programs=defn.programs(),
        class_name=class_name,
    )


def explain_molecule(
    molecule,
    definition: Definition | str,
    *,
    library_dir: str | None = None,
    strict: bool = True,
    chebi_graph=None,
    class_name: str | None = None,
    name: str | None = None,
):
    """Local explanation: whether and why the rule accepts ``molecule`` (SMILES, InChI,
    molblock or RDKit molecule). Returns an ``Explanation`` (``text``, ``image``,
    ``fires``)."""
    from viloch.explain.explain import explain_molecule as _explain_molecule

    defn = prepare(definition, library_dir, strict)
    return _explain_molecule(
        molecule,
        defn.rule,
        chebi_graph=chebi_graph,
        aux_programs=defn.programs(),
        class_name=class_name,
        name=name,
    )


def as_json(expl) -> dict:
    """An explanation as JSON: ``{"text", "image" (PNG data URL)}``, plus ``"fires"``
    for a molecule."""
    out = {"text": expl.text, "image": png_data_url(expl.image)}
    return out if expl.fires is None else {"fires": expl.fires, **out}


def png_data_url(image) -> str:
    """A PIL image as a ``data:image/png;base64,…`` URL."""
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
