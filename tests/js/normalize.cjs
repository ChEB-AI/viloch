// Renumber the ids of an editor model ("a1", "a2", … in order of first appearance), so
// models from different parsers (or parse calls) compare equal. Mirrors
// tests/editor_util.py:normalize_ids.
"use strict";

function normalizeIds(model) {
  const map = {};
  let n = 0;
  const id = (old) => (old in map ? map[old] : (map[old] = "a" + ++n));
  const clauses = (model.clauses || []).map((cl) => {
    if (cl.rawClause != null) return cl;
    // Atoms and groups get ids in creation order: atoms of the main pattern first,
    // then each group followed by its atoms.
    const order = [];
    for (const a of cl.atoms) if (!a.group) order.push(a.id);
    for (const g of cl.groups) {
      order.push(g.id);
      for (const a of cl.atoms) if (a.group === g.id) order.push(a.id);
    }
    order.forEach(id);
    return {
      ...cl,
      atoms: cl.atoms.map((a) => ({ ...a, id: id(a.id), ...(a.group ? { group: id(a.group) } : {}) })),
      bonds: cl.bonds.map((b) => ({ ...b, a: id(b.a), b: id(b.b) })),
      groups: cl.groups.map((g) => ({ ...g, id: id(g.id) })),
    };
  });
  return { ...model, clauses };
}

module.exports = { normalizeIds };
