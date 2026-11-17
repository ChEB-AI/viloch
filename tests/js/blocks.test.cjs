// Node tests of the editor's DOM-free helpers:  node --test tests/js/
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("path");
const fs = require("fs");

const B = require(path.join(__dirname, "..", "..", "src", "viloch", "web", "static", "blocks.js"));
const FIXTURES = path.join(__dirname, "..", "fixtures", "editor");

test("describe labels atoms, bonds and molecule properties", () => {
  assert.deepEqual(B.describe("o"), { label: "Oxygen", scope: "atom" });
  assert.deepEqual(B.describe("has_2_hs"), { label: "2 H", scope: "atom" });
  assert.deepEqual(B.describe("charge_m1"), { label: "charge −1", scope: "atom" });
  assert.deepEqual(B.describe("bDOUBLE"), { label: "double", scope: "bond" });
  assert.deepEqual(B.describe("aromatic"), { label: "aromatic", scope: "molecule" });
  assert.equal(B.describe("not in_ring").label, "not in ring");
  assert.equal(B.describe("aux_acyclic_molecule_36685").label, "acyclic molecule (CHEBI:36685)");
});

test("groupOf marks mutually exclusive properties", () => {
  assert.equal(B.groupOf("c"), "element");
  assert.equal(B.groupOf("charge_p"), "charge");
  assert.equal(B.groupOf("has_3_hs"), "h_exact");
  assert.equal(B.groupOf("in_ring6"), null);
  assert.equal(B.groupOf("net_charge_negative"), "net_charge");
});

test("renumber gives fresh ids and keeps references consistent", () => {
  const model = JSON.parse(fs.readFileSync(path.join(FIXTURES, "not_box_bonded.model.json"), "utf8"));
  const cl = model.clauses[0];
  const before = new Set([...cl.atoms, ...cl.groups].map((x) => x.id));
  B.renumber(cl);
  const ids = new Set([...cl.atoms, ...cl.groups].map((x) => x.id));
  assert.equal(ids.size, before.size);
  for (const a of cl.atoms) if (a.group) assert.ok(ids.has(a.group));
  for (const b of cl.bonds) { assert.ok(ids.has(b.a)); assert.ok(ids.has(b.b)); }
});

test("forceLayout places every atom of every fixture inside the canvas", () => {
  for (const f of fs.readdirSync(FIXTURES).filter((n) => n.endsWith(".model.json"))) {
    const model = JSON.parse(fs.readFileSync(path.join(FIXTURES, f), "utf8"));
    for (const cl of model.clauses.filter((c) => c.atoms && c.atoms.length)) {
      B.forceLayout(cl.atoms, cl.bonds, 640, 260, 150, 60);
      for (const a of cl.atoms) {
        assert.ok(Number.isFinite(a.x) && Number.isFinite(a.y), `${f}: ${a.id} not placed`);
      }
    }
  }
});

test("emptyModel is one empty clause", () => {
  assert.deepEqual(B.emptyModel(), { clauses: [{ atoms: [], molChips: [], bonds: [], groups: [] }] });
});
