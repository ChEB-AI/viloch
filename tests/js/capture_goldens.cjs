// Capture the editor's ASP <-> model behaviour as golden files.
//
//   node tests/js/capture_goldens.cjs <path/to/blocks.js> [fixture dir]
//
// For every <name>.lp in the fixture dir (default tests/fixtures/editor) it writes
// <name>.model.json (parseRule, ids renumbered) and <name>.compiled.lp
// (compileModel(parseRule(text))). Run once against icarus' original blocks.js (which
// parsed and compiled in JS) to pin today's behaviour for the Python port.
"use strict";
const fs = require("fs");
const path = require("path");
const { normalizeIds } = require("./normalize.cjs");

const [blocksPath, dirArg] = process.argv.slice(2);
if (!blocksPath) {
  console.error("usage: node capture_goldens.cjs <blocks.js> [fixture dir]");
  process.exit(2);
}
const pure = require(path.resolve(blocksPath));
const dir = path.resolve(dirArg || path.join(__dirname, "..", "fixtures", "editor"));

for (const file of fs.readdirSync(dir).filter((f) => f.endsWith(".lp") && !f.endsWith(".compiled.lp"))) {
  const name = file.slice(0, -3);
  const text = fs.readFileSync(path.join(dir, file), "utf8");
  const model = pure.parseRule(text);
  const compiled = pure.compileModel(model);
  fs.writeFileSync(path.join(dir, name + ".model.json"), JSON.stringify(normalizeIds(model), null, 2) + "\n");
  fs.writeFileSync(path.join(dir, name + ".compiled.lp"), compiled + "\n");
  console.log(name);
}
