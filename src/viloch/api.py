"""High-level entry points: explanations of a :class:`~viloch.definition.Definition`."""

from __future__ import annotations

import base64
import io
import pickle

from viloch.definition import Definition
from viloch.editor.boxes import explainer_inputs


def as_definition(
    definition: Definition | str, target: str | None = None
) -> Definition:
    return (
        definition
        if isinstance(definition, Definition)
        else Definition.parse(definition, target)
    )


def prepare(definition: Definition | str, library_dir: str | None = None) -> Definition:
    """The definition ready for the explainer: library predicates filled in and the
    editor's "not" boxes turned into negated helper predicates."""
    from viloch.chem import efg

    efg.install()
    defn = as_definition(definition).resolve(library_dir)
    return explainer_inputs(defn)


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
    chebi_graph=None,
    class_name: str | None = None,
):
    """Global explanation: what the definition's rule asks of a molecule.

    Returns an :class:`~viloch.explain.explain.Explanation` (``text``, ``image``).
    """
    from viloch.explain.explain import explain_rule as _explain_rule

    defn = prepare(definition, library_dir)
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
    chebi_graph=None,
    class_name: str | None = None,
    name: str | None = None,
):
    """Local explanation: whether and why the rule accepts ``molecule`` (SMILES, InChI,
    molblock or RDKit molecule). Returns an ``Explanation`` (``text``, ``image``,
    ``fires``)."""
    from viloch.explain.explain import explain_molecule as _explain_molecule

    defn = prepare(definition, library_dir)
    return _explain_molecule(
        molecule,
        defn.rule,
        chebi_graph=chebi_graph,
        aux_programs=defn.programs(),
        class_name=class_name,
        name=name,
    )


def png_data_url(image) -> str:
    """A PIL image as a ``data:image/png;base64,…`` URL."""
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
