"use strict";
// The standalone page: an ASP text pane and the block editor, kept in sync through
// the server (POST api/parse: text -> model, POST api/compile: model -> text).
(function () {
  const $ = (id) => document.getElementById(id);

  // What the blocks currently show: the target predicate and the auxiliary programs
  // that came with the parsed text (compile writes back the ones still used).
  const state = { target: null, aux: [], blocks: null, syncing: false };

  async function api(path, body) {
    const res = await fetch("api/" + path, body === undefined ? {} : {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
    if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  }

  function status(msg, kind) {
    const el = $("status");
    el.textContent = msg || "";
    el.className = "status" + (kind ? " " + kind : "");
  }

  function debounce(fn, ms) {
    let t = null;
    return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
  }

  async function textToBlocks() {
    try {
      const data = await api("parse", { definition: $("asp-text").value, unfold: $("unfold").checked });
      state.target = data.target;
      state.aux = data.aux;
      state.syncing = true;
      // Rebuilding the palette resets its search; only do it when the blocks change.
      const blocks = JSON.stringify(data.blocks);
      if (blocks !== state.blocks) {
        state.blocks = blocks;
        Blocks.setCatalog(catalog, data.blocks);
      }
      Blocks.load(data.model);
      state.syncing = false;
      const raw = data.model.clauses.filter((c) => c.rawClause != null).length;
      status(raw ? `${raw} clause(s) have no blocks and are shown as text.` : "", raw ? "warn" : "");
    } catch (e) {
      status(e.message, "error");
    }
  }

  async function blocksToText() {
    try {
      const data = await api("compile", { model: Blocks.getModel(), aux: state.aux, target: state.target });
      $("asp-text").value = data.definition;
      status("");
    } catch (e) {
      status(e.message, "error");
    }
  }

  async function explain(path, extra) {
    const out = $("explanation");
    out.innerHTML = '<span class="muted">Drawing…</span>';
    try {
      const data = await api(path, { definition: $("asp-text").value, ...extra });
      const verdict = data.fires == null ? "" :
        `<div class="verdict ${data.fires ? "pos" : "neg"}">${data.fires ? "accepted" : "rejected"}</div>`;
      out.innerHTML = `${verdict}<p></p><img alt="explanation">`;
      out.querySelector("p").textContent = data.text;
      out.querySelector("img").src = data.image;
    } catch (e) {
      out.innerHTML = "";
      status(e.message, "error");
    }
  }

  let catalog = [];
  const syncText = debounce(() => { if ($("auto-sync").checked) blocksToText(); }, 250);
  const syncBlocks = debounce(() => { if ($("auto-sync").checked) textToBlocks(); }, 600);

  Blocks.init({
    palette: $("block-palette"),
    canvas: $("block-canvas"),
    searchAux: (q, offset) => api(`search?q=${encodeURIComponent(q)}&offset=${offset}`),
    unfold: async (clause, pred) => {
      try {
        const data = await api("unfold", { clause, pred, aux: state.aux, target: state.target });
        state.aux = data.aux || state.aux;
        return data;
      } catch (e) {
        return { error: e.message };
      }
    },
    notify: (msg) => status(msg, "warn"),
    onChange: () => { if (!state.syncing) syncText(); },
  });

  $("to-blocks").onclick = textToBlocks;
  $("to-text").onclick = blocksToText;
  $("unfold").onchange = textToBlocks;
  $("asp-text").addEventListener("input", syncBlocks);
  $("explain-rule").onclick = () => explain("explain/rule", {});
  $("explain-molecule").onclick = () => {
    const smiles = $("smiles").value.trim();
    if (!smiles) { status("Enter a SMILES first.", "warn"); return; }
    explain("explain/molecule", { molecule: smiles, name: $("mol-name").value.trim() || undefined });
  };

  api("catalog").then((data) => {
    catalog = data.catalog;
    state.target = data.target;
    textToBlocks();
  }).catch((e) => status(e.message, "error"));
})();
