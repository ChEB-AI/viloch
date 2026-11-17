"use strict";
// ── Visual building-block rule editor ───────────────────────────────────────
// A rule is an OR of clauses ("alternatives"). Each clause has a molecule area
// (global properties), freely-placed atom areas (per-atom properties), bonds
// drawn between two atom areas, and "not" / "count" boxes: frames around some of
// the atoms, which become `#count{ … } = 0` / `#count{ … } >= n` over them (a
// negated molecule property sits in the molecule area as `not p(V0)`).
//
// The editor edits a model (see viloch/editor/model.schema.json); converting it to
// and from ASP text is the server's job (viloch.editor.asp, e.g. POST api/parse and
// api/compile of `viloch serve`). Clauses the server could not turn into blocks come
// as {rawClause, why} and are shown as text.
//
//   Blocks.init({palette, canvas, onChange, searchAux?, unfold?, notify?})
//   Blocks.setCatalog(catalog, aux)     palette blocks (GET api/catalog)
//   Blocks.load(model)                  show a model (null: one empty clause)
//   Blocks.getModel()                   a copy of the current model
//
// describe / groupOf / forceLayout are DOM-free (unit-tested in Node).
(function (global) {

  // Built-in element symbol → name (mirrors viloch.editor.catalog.COMMON_ELEMENTS),
  // so describe() labels elements even before the catalog loads / in Node tests.
  const ELEMENTS = {
    c: "Carbon", n: "Nitrogen", o: "Oxygen", s: "Sulfur", p: "Phosphorus",
    f: "Fluorine", cl: "Chlorine", br: "Bromine", i: "Iodine", h: "Hydrogen",
    b: "Boron", si: "Silicon", se: "Selenium",
  };

  // Pseudo-predicates for comparisons between two atom variables, drawn as bond-like
  // links: X != Y ("different atoms") and X < Y (an order, so a count box counts a
  // pair of interchangeable atoms once). A negated literal is a chip/bond whose pred
  // is "not <pred>".
  const NEQ = "!=";
  const LT = "<";

  // ── readable description of a ground predicate ────────────────────────────
  // Returns {label, scope}. `label` is the compact chip text; `scope` is a hint
  // (molecule|atom|bond) used when the predicate is added from the palette (the
  // parser places predicates by their actual argument role, not this hint).
  function describe(pred) {
    let m;
    if (pred === NEQ) return { label: "≠ different atoms", scope: "bond" };
    if (pred === LT) return { label: "< order", scope: "bond" };
    if (pred.startsWith("not ")) {
      const d = describe(pred.slice(4));
      return { label: "not " + d.label, scope: d.scope };
    }
    if (ELEMENTS[pred]) return { label: ELEMENTS[pred], scope: "atom" };
    if (/^[a-z]{1,2}$/.test(pred)) return { label: pred.toUpperCase(), scope: "atom" };

    if (pred === "charge0") return { label: "charge 0", scope: "atom" };
    if (pred === "charge_p") return { label: "charge +", scope: "atom" };
    if (pred === "charge_n") return { label: "charge −", scope: "atom" };
    if ((m = /^charge_m(\d+)$/.exec(pred))) return { label: "charge −" + m[1], scope: "atom" };
    if ((m = /^charge(\d+)$/.exec(pred))) return { label: "charge +" + m[1], scope: "atom" };

    if ((m = /^has_(\d+)_hs$/.exec(pred))) return { label: m[1] + " H", scope: "atom" };
    if ((m = /^has_at_least_(\d+)_hs$/.exec(pred))) return { label: "≥" + m[1] + " H", scope: "atom" };

    if (pred === "in_ring") return { label: "in ring", scope: "atom" };
    if ((m = /^in_ring(\d+)$/.exec(pred))) return { label: m[1] + "-ring", scope: "atom" };

    if ((m = /^cip_code_([A-Za-z])$/.exec(pred))) return { label: "CIP " + m[1].toUpperCase(), scope: "atom" };
    if ((m = /^steroid_(\d+)$/.exec(pred))) return { label: "steroid " + m[1], scope: "atom" };

    if (pred === "has_bond_to") return { label: "bonded", scope: "bond" };
    if ((m = /^bSTEREO([A-Z]+)$/.exec(pred))) return { label: "stereo " + m[1].toLowerCase(), scope: "bond" };
    if (/^b[A-Z]+$/.test(pred)) return { label: pred.slice(1).toLowerCase(), scope: "bond" };

    if (pred === "aromatic" || pred === "aliphatic") return { label: pred, scope: "molecule" };
    if ((m = /^net_charge_(\w+)$/.exec(pred))) return { label: "net " + m[1], scope: "molecule" };

    // aux_* or anything unrecognised → humanised name (drop aux_). A ChEBI-id
    // suffix disambiguates same-named generated predicates, so keep it readable.
    let name = pred.startsWith("aux_") ? pred.slice(4) : pred;
    const id = /_(\d{4,})$/.exec(name);
    name = name.replace(/_\d{4,}$/, "").replace(/_/g, " ").trim();
    if (name && id) name += ` (CHEBI:${id[1]})`;
    return { label: name || pred, scope: "molecule" };
  }

  // Mutual-exclusivity group of a ground predicate, or null when it can freely
  // coexist with others on the same atom/molecule. An atom is exactly one element,
  // carries one formal charge, one exact H-count, one CIP code, one steroid
  // position; a molecule is aromatic xor aliphatic and has one net charge. Ring
  // membership is intentionally ungrouped — a fused-ring atom is in several rings.
  function groupOf(pred) {
    if (ELEMENTS[pred] || /^[a-z]{1,2}$/.test(pred)) return "element";
    if (/^charge(0|_p|_n|_m?\d+)$/.test(pred)) return "charge";
    if (/^has_\d+_hs$/.test(pred)) return "h_exact";
    if (/^has_at_least_\d+_hs$/.test(pred)) return "h_atleast";
    if (/^cip_code_/.test(pred)) return "cip";
    if (/^steroid_\d+$/.test(pred)) return "steroid";
    if (pred === "aromatic" || pred === "aliphatic") return "aromaticity";
    if (/^net_charge_/.test(pred)) return "net_charge";
    return null;
  }

  // Registered readable labels (from the loaded catalog/aux) win over the generic
  // describe() label, so choice options and aux descriptions read nicely.
  const LABELS = {};
  function labelFor(pred) {
    if (pred.startsWith("not ")) return "not " + labelFor(pred.slice(4));
    return (pred in LABELS) ? LABELS[pred] : describe(pred).label;
  }


  const COUNT_OPS = ["=", ">=", "<=", ">", "<", "between"];

  // Ids of atoms and boxes. Models from the server number them "a1", "a2", …;
  // load() moves the counter past them so new ids never clash.
  let _id = 0;
  const newId = () => "a" + (++_id);
  function reserveIds(model) {
    for (const cl of (model && model.clauses) || []) {
      for (const x of [...(cl.atoms || []), ...(cl.groups || [])]) {
        const m = /^a(\d+)$/.exec(x.id || "");
        if (m) _id = Math.max(_id, parseInt(m[1], 10));
      }
    }
  }

  // Give every atom and box of clause `cl` a fresh id (in place), keeping its bonds
  // and box memberships consistent.
  function renumber(cl) {
    if (!cl || cl.rawClause != null) return cl;
    const map = {};
    const fresh = (old) => (old in map ? map[old] : (map[old] = newId()));
    (cl.groups || []).forEach((g) => { g.id = fresh(g.id); });
    (cl.atoms || []).forEach((a) => {
      a.id = fresh(a.id);
      if (a.group != null) a.group = fresh(a.group);
    });
    (cl.bonds || []).forEach((b) => { b.a = fresh(b.a); b.b = fresh(b.b); });
    return cl;
  }

  function emptyClause() { return { atoms: [], molChips: [], bonds: [], groups: [] }; }
  function emptyModel() { return { clauses: [emptyClause()] }; }

  const GRAVITY = 2;

  // Force-directed (Fruchterman–Reingold) layout of a clause's atoms within a
  // WxH area: atoms repel each other, bonds pull their endpoints together, so a
  // star like A–B, A–C relaxes into a spread where both bonds stay visible
  // instead of collapsing onto one line. Writes top-left {x,y} back onto each
  // atom (boxW/boxH keep boxes inside the area). Deterministic (circle seed).
  function forceLayout(atoms, bonds, W, H, boxW, boxH, gravity = GRAVITY) {
    const n = atoms.length;
    if (!n) return;
    const cx = W / 2, cy = H / 2;
    if (n === 1) { atoms[0].x = Math.round(cx - boxW / 2); atoms[0].y = Math.round(cy - boxH / 2); return; }

    const idx = {};
    atoms.forEach((a, i) => { idx[a.id] = i; });
    const R = Math.min(W, H) * 0.32;
    const pos = atoms.map((_, i) => ({
      x: cx + Math.cos((2 * Math.PI * i) / n) * R,
      y: cy + Math.sin((2 * Math.PI * i) / n) * R,
    }));
    const edges = (bonds || [])
      .filter((b) => idx[b.a] != null && idx[b.b] != null)
      .map((b) => [idx[b.a], idx[b.b]]);

    const k = Math.sqrt((W * H) / n) * 0.62;   // ideal separation
    let temp = W * 0.12;
    for (let it = 0; it < 220; it++) {
      const disp = pos.map(() => ({ x: 0, y: 0 }));
      for (let i = 0; i < n; i++) {
        for (let j = i + 1; j < n; j++) {
          let dx = pos[i].x - pos[j].x, dy = pos[i].y - pos[j].y;
          let d = Math.hypot(dx, dy) || 0.01;
          const f = (k * k) / d, ux = dx / d, uy = dy / d;
          disp[i].x += ux * f; disp[i].y += uy * f;
          disp[j].x -= ux * f; disp[j].y -= uy * f;
        }
      }
      for (const [a, b] of edges) {
        let dx = pos[a].x - pos[b].x, dy = pos[a].y - pos[b].y;
        let d = Math.hypot(dx, dy) || 0.01;
        const f = (d * d) / k, ux = dx / d, uy = dy / d;
        disp[a].x -= ux * f; disp[a].y -= uy * f;
        disp[b].x += ux * f; disp[b].y += uy * f;
      }
      // A weak pull to the centre keeps unconnected parts from drifting into the
      // corners (where the normalisation below would squash each into a clump).
      for (let i = 0; i < n; i++) {
        disp[i].x += (cx - pos[i].x) * gravity;
        disp[i].y += (cy - pos[i].y) * gravity;
      }
      for (let i = 0; i < n; i++) {
        let d = Math.hypot(disp[i].x, disp[i].y) || 0.01;
        pos[i].x += (disp[i].x / d) * Math.min(d, temp);
        pos[i].y += (disp[i].y / d) * Math.min(d, temp);
      }
      temp = Math.max(temp * 0.95, 2);
    }
    // Normalise to fill the area with a margin, then convert centre→top-left.
    const xs = pos.map((p) => p.x), ys = pos.map((p) => p.y);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const mL = boxW / 2 + 8, mR = boxW / 2 + 8, mT = boxH / 2 + 8, mB = boxH / 2 + 8;
    const sx = (maxX - minX) > 1 ? (W - mL - mR) / (maxX - minX) : 1;
    const sy = (maxY - minY) > 1 ? (H - mT - mB) / (maxY - minY) : 1;
    atoms.forEach((a, i) => {
      const px = mL + (pos[i].x - minX) * sx;
      const py = mT + (pos[i].y - minY) * sy;
      a.x = Math.round(px - boxW / 2);
      a.y = Math.round(py - boxH / 2);
    });
  }

  // ════════════════════════════════════════════════════════════════════════
  //  DOM editor
  // ════════════════════════════════════════════════════════════════════════
  const Editor = {
    model: emptyModel(),
    catalog: [],
    aux: [],
    paletteEl: null,
    canvasEl: null,
    onChangeCb: null,
    selected: null,   // {clauseIdx, kind:'mol'|'atom', atomId?} for click-to-add

    init(opts) {
      this.paletteEl = opts.palette;
      this.canvasEl = opts.canvas;
      this.onChangeCb = opts.onChange || null;
      this.searchAuxCb = opts.searchAux || null;  // (q, offset) → {results, total}
      this.unfoldCb = opts.unfold || null;        // (clause, pred) → {model?, error?}
      this.notifyCb = opts.notify || null;        // (message) → shown to the user
      this.canvasEl.addEventListener("click", (e) => this.onCanvasClick(e));
      this.renderCanvas();
    },

    setCatalog(catalog, aux) {
      this.catalog = catalog || [];
      this.aux = aux || [];
      this.registerLabels([...this.catalog, ...this.aux]);
      // Element symbols → nice names.
      for (const b of this.catalog) {
        if (b.category === "Element" && b.input && b.input.type === "toggle") {
          ELEMENTS[b.input.pred] = b.label;
        }
      }
      this.renderPalette();
    },

    // Register readable labels for every ground predicate the blocks name.
    registerLabels(blocks) {
      for (const b of blocks) {
        const inp = b.input || {};
        if (inp.type === "toggle" && inp.pred) LABELS[inp.pred] = b.label;
        if (inp.type === "choice") (inp.options || []).forEach((o) => { LABELS[o.pred] = b.label + ": " + o.label; });
      }
    },

    changed() {
      if (this.onChangeCb) this.onChangeCb();
    },

    // Show a model (from the server's parse); rebuilds the UI.
    load(model) {
      this.model = model && model.clauses && model.clauses.length
        ? JSON.parse(JSON.stringify(model)) : emptyModel();
      reserveIds(this.model);
      this.selected = null;
      this.renderCanvas();
    },

    // A copy of the model, as the server's compile takes it.
    getModel() { return JSON.parse(JSON.stringify(this.model)); },

    // Add a predicate chip to an area's chip list, dropping any exact duplicate and
    // any mutually-exclusive chip (same group) first — so a second element / charge
    // / H-count replaces the first rather than stacking a contradiction.
    addChip(list, pred) {
      const g = groupOf(pred);
      for (let i = list.length - 1; i >= 0; i--) {
        const p = list[i].pred;
        if (p === pred || (g && groupOf(p) === g)) list.splice(i, 1);
      }
      list.push({ pred });
    },

    // ── palette ─────────────────────────────────────────────────────────────
    renderPalette() {
      const el = this.paletteEl;
      el.innerHTML = "";
      // Bond/relation predicates aren't dragged from the palette — a bond needs two
      // atoms, so it's drawn with the 🔗 connect handle and its type is chosen on the
      // bond itself. So the palette lists only molecule- and atom-scope blocks.
      const all = [...this.catalog, ...this.aux].filter((b) => b.scope !== "bond");
      // Popular row first; the collapsible groups hold everything else (so a block
      // isn't listed twice).
      const groups = {};
      const order = [];
      for (const b of all) {
        if (b.popular) continue;
        if (!groups[b.category]) { groups[b.category] = []; order.push(b.category); }
        groups[b.category].push(b);
      }
      if (this.searchAuxCb) el.appendChild(this.auxSearchBox());
      const popular = all.filter((b) => b.popular);
      if (popular.length) {
        const row = document.createElement("div");
        row.className = "palette-popular";
        row.innerHTML = `<div class="palette-group-title">Common</div>`;
        const wrap = document.createElement("div");
        wrap.className = "palette-blocks";
        popular.forEach((b) => wrap.appendChild(this.paletteBlock(b)));
        row.appendChild(wrap);
        el.appendChild(row);
      }
      // Collapsible advanced groups.
      const more = document.createElement("details");
      more.className = "palette-more";
      more.innerHTML = `<summary>More predicates…</summary>`;
      order.forEach((cat) => {
        const g = document.createElement("div");
        g.className = "palette-group";
        g.innerHTML = `<div class="palette-group-title">${escapeHtml(cat)}</div>`;
        const wrap = document.createElement("div");
        wrap.className = "palette-blocks";
        groups[cat].forEach((b) => wrap.appendChild(this.paletteBlock(b)));
        g.appendChild(wrap);
        more.appendChild(g);
      });
      el.appendChild(more);
    },

    // Search over ALL generated predicates in the library — the palette group only
    // lists those relevant to the current class. The query survives palette
    // re-renders (the catalog is reloaded whenever the class or rule changes).
    auxSearchBox() {
      const box = document.createElement("div");
      box.className = "palette-search";
      box.innerHTML = `<input type="search" class="ps-input" placeholder="Search all generated predicates…"
        aria-label="Search all LLM-generated predicates">
        <div class="ps-status"></div><div class="palette-blocks ps-results"></div>`;
      const input = box.querySelector(".ps-input");
      const status = box.querySelector(".ps-status");
      const results = box.querySelector(".ps-results");
      input.value = this.searchQuery || "";
      let timer = null, seq = 0, shown = 0;

      const run = async (append) => {
        const q = input.value.trim();
        this.searchQuery = q;
        const my = ++seq;
        if (!q) { results.innerHTML = ""; status.textContent = ""; shown = 0; return; }
        if (!append) shown = 0;
        status.textContent = "Searching…";
        let data;
        try { data = await this.searchAuxCb(q, shown); } catch (e) { status.textContent = ""; return; }
        if (my !== seq) return;  // a newer query superseded this one
        if (!append) results.innerHTML = "";
        this.registerLabels(data.results);
        data.results.forEach((b) => results.appendChild(this.paletteBlock(b)));
        shown += data.results.length;
        status.innerHTML = "";
        status.append(data.total ? `${shown} of ${data.total} match${data.total === 1 ? "" : "es"}` : "No matches");
        if (shown < data.total) {
          const more = document.createElement("button");
          more.className = "linkbtn ps-more";
          more.textContent = "show more";
          more.onclick = () => run(true);
          status.append(" · ", more);
        }
      };
      input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => run(false), 250); });
      if (input.value) run(false);
      return box;
    },

    // Build one palette block element. Returns the ground predicate via getPred().
    paletteBlock(b) {
      const div = document.createElement("div");
      div.className = "palette-block scope-" + b.scope;
      div.dataset.scope = b.scope;
      const inp = b.input || {};
      let control = "";
      if (inp.type === "choice") {
        const opts = (inp.options || []).map((o) =>
          `<option value="${escapeHtml(o.pred)}"${o.pred === inp.default ? " selected" : ""}>${escapeHtml(o.label)}</option>`).join("");
        control = `<select class="pb-choice">${opts}</select>`;
      } else if (inp.type === "element") {
        control = `<input class="pb-element" type="text" maxlength="2" placeholder="e.g. Cl" size="3">`;
      }
      let info = b.description || "";
      if (b.chebi_id) {
        info += (info ? "\n" : "") + `Generated for CHEBI:${b.chebi_id}` +
          (b.chebi_name && b.chebi_name !== "CHEBI:" + b.chebi_id ? ` (${b.chebi_name})` : "");
      }
      if (b.input && b.input.type === "toggle" && b.input.pred.startsWith("aux_")) info += `\n${b.input.pred}`;
      div.innerHTML = `<span class="pb-label">${escapeHtml(b.label)}</span>${control}` +
        (info ? `<span class="pb-desc" title="${escapeHtml(info.trim())}">ⓘ</span>` : "");

      const getPred = () => {
        if (inp.type === "toggle") return inp.pred;
        if (inp.type === "choice") return div.querySelector(".pb-choice").value;
        if (inp.type === "element") {
          const v = (div.querySelector(".pb-element").value || "").trim().toLowerCase();
          return v || null;
        }
        return null;
      };

      div.draggable = true;
      div.addEventListener("dragstart", (e) => {
        const pred = getPred();
        if (!pred) { e.preventDefault(); return; }
        e.dataTransfer.setData("text/plain", JSON.stringify({ pred, scope: b.scope }));
        e.dataTransfer.effectAllowed = "copy";
        Editor._dragScope = b.scope;  // getData is blocked during dragover, so stash it
      });
      div.addEventListener("dragend", () => { Editor._dragScope = null; });
      // Click-to-add to the selected area (accessibility / no-drag fallback).
      div.addEventListener("click", (e) => {
        if (e.target.closest(".pb-choice, .pb-element")) return;
        const pred = getPred();
        if (pred) this.addToSelected(pred, b.scope);
      });
      return div;
    },

    // ── canvas render ─────────────────────────────────────────────────────────
    renderCanvas() {
      const el = this.canvasEl;
      el.innerHTML = "";
      this.model.clauses.forEach((cl, ci) => el.appendChild(this.clauseCard(cl, ci)));
      const add = document.createElement("button");
      add.className = "add-clause ghost";
      add.textContent = "+ OR alternative";
      add.onclick = () => { this.model.clauses.push(emptyClause()); this.renderCanvas(); this.changed(); };
      el.appendChild(add);
      // Auto-arrange freshly loaded/reflowed clauses (canvas is now in the DOM, so
      // its width is known), then size boxes and canvases to their atoms and draw
      // the bonds.
      this.model.clauses.forEach((cl, ci) => {
        if (cl.rawClause) return;
        if (cl._needsLayout) { this.autoLayout(cl, ci); cl._needsLayout = false; }
        this.fitFrames(cl, ci);
        this.fitCanvas(ci);
        this.drawBonds(ci);
      });
    },

    // Canvas boxes (not/count groups drawn as frames around their atoms).
    frames(cl) { return (cl.groups || []).filter((g) => !g.inMol); },
    members(cl, g) { return (cl.atoms || []).filter((a) => a.group === g.id); },

    // Lay a clause out: the main pattern force-directed at the top, then each box as a
    // frame of its own (its atoms force-directed inside), in rows below.
    autoLayout(cl, ci) {
      const canvas = this.canvasEl.querySelector(`.atom-canvas[data-ci="${ci}"]`);
      const W = Math.max(320, (canvas ? canvas.clientWidth : 0) || 520);
      const frames = this.frames(cl);
      const framed = new Set(frames.map((g) => g.id));
      const bondsAmong = (atoms) => {
        const ids = new Set(atoms.map((a) => a.id));
        return (cl.bonds || []).filter((b) => ids.has(b.a) && ids.has(b.b));
      };
      const place = (atoms, x0, y0, w, h) => {
        if (atoms.length === 1) { atoms[0].x = Math.round(x0 + Math.min(16, (w - 132) / 2)); atoms[0].y = y0 + 10; return; }
        forceLayout(atoms, bondsAmong(atoms), w, h, 138, 78);
        atoms.forEach((a) => { a.x += x0; a.y += y0; });
      };

      const main = (cl.atoms || []).filter((a) => !framed.has(a.group));
      let y = 12;
      if (main.length) {
        const H = main.length === 1 ? 100 : Math.max(240, Math.min(520, 150 + 52 * main.length));
        place(main, main.length === 1 ? 24 : 0, main.length === 1 ? 10 : 0, W, H);
        y = Math.max(...main.map((a) => a.y)) + 100;
      }
      const HEAD = 40;
      let x = 12, rowH = 0;
      for (const g of frames) {
        const mem = this.members(cl, g);
        const n = mem.length;
        const w = Math.min(W - 24, n <= 1 ? 290 : n === 2 ? 360 : 470);
        const h = n <= 1 ? 110 : Math.min(420, 110 + 46 * n);
        if (x > 12 && x + w > W - 12) { x = 12; y += rowH + 16; rowH = 0; }
        Object.assign(g, { x, y, w, h: h + HEAD });
        if (n) place(mem, x, y + HEAD, w, h);
        x += w + 16; rowH = Math.max(rowH, h + HEAD);
      }
      if (canvas) {
        cl.atoms.forEach((a) => {
          const box = canvas.querySelector(`.atom-box[data-aid="${a.id}"]`);
          if (box) { box.style.left = a.x + "px"; box.style.top = a.y + "px"; }
        });
        frames.forEach((g) => this.styleFrame(canvas, g));
      }
    },

    styleFrame(canvas, g) {
      const f = canvas.querySelector(`.group-frame[data-gid="${g.id}"]`);
      if (!f) return;
      Object.assign(f.style, { left: g.x + "px", top: g.y + "px", width: g.w + "px", height: g.h + "px" });
    },

    // Grow each frame so it still encloses its (variable-height) atom boxes.
    fitFrames(cl, ci) {
      const canvas = this.canvasEl.querySelector(`.atom-canvas[data-ci="${ci}"]`);
      if (!canvas) return;
      for (const g of this.frames(cl)) {
        const f = canvas.querySelector(`.group-frame[data-gid="${g.id}"]`);
        const head = f ? f.querySelector(".group-head").offsetHeight : 34;
        g.w = Math.max(g.w || 0, 200);
        g.h = Math.max(g.h || 0, head + 60);
        for (const a of this.members(cl, g)) {
          const box = canvas.querySelector(`.atom-box[data-aid="${a.id}"]`);
          if (!box) continue;
          g.w = Math.max(g.w, box.offsetLeft + box.offsetWidth + 12 - g.x);
          g.h = Math.max(g.h, box.offsetTop + box.offsetHeight + 12 - g.y);
        }
        this.styleFrame(canvas, g);
      }
    },

    // Grow the atom-canvas so every (variable-height) atom box and frame fits.
    fitCanvas(ci) {
      const canvas = this.canvasEl.querySelector(`.atom-canvas[data-ci="${ci}"]`);
      if (!canvas) return;
      let bottom = 0;
      canvas.querySelectorAll(".atom-box, .group-frame").forEach((b) => { bottom = Math.max(bottom, b.offsetTop + b.offsetHeight); });
      canvas.style.height = Math.max(190, bottom + 44) + "px";
    },

    // A free spot for a new frame: below everything on the canvas.
    newFrame(cl, kind) {
      let bottom = 0;
      (cl.atoms || []).forEach((a) => { bottom = Math.max(bottom, (a.y || 0) + 90); });
      this.frames(cl).forEach((g) => { bottom = Math.max(bottom, g.y + g.h); });
      const g = { id: newId(), kind, molChips: [], x: 12, y: bottom + 14, w: 300, h: 140 };
      if (kind === "count") Object.assign(g, { op: ">=", n: 1 });
      (cl.groups = cl.groups || []).push(g);
      return g;
    },

    // Which frame (if any) an atom box centred at (x, y) lies in: the smallest one.
    frameAt(cl, x, y) {
      let best = null;
      for (const g of this.frames(cl)) {
        if (x >= g.x && x <= g.x + g.w && y >= g.y && y <= g.y + g.h &&
            (!best || g.w * g.h < best.w * best.h)) best = g;
      }
      return best;
    },

    // An atom joins (or leaves, g = null) a box. Refused when it would leave a bond
    // between two different boxes (atoms of a box exist only inside it).
    moveToGroup(cl, a, g) {
      const gid = g ? g.id : null;
      const groupOf = (id) => (id === a.id ? gid : ((cl.atoms.find((x) => x.id === id) || {}).group || null));
      const crossing = (cl.bonds || []).some((b) => {
        if (b.a !== a.id && b.b !== a.id) return false;
        const ga = groupOf(b.a), gb = groupOf(b.b);
        return ga && gb && ga !== gb;
      });
      if (crossing) return false;
      if (gid) {
        if (a.group !== gid && g.kind === "count") a.counted = !this.members(cl, g).some((x) => x.counted);
        a.group = gid;
      } else {
        delete a.group; delete a.counted;
      }
      return true;
    },

    clauseCard(cl, ci) {
      const card = document.createElement("div");
      card.className = "clause-card";
      card.dataset.ci = ci;

      const head = document.createElement("div");
      head.className = "clause-head";
      head.innerHTML = `<span class="clause-title">${ci === 0 ? "Rule" : "OR — alternative " + (ci + 1)}</span>`;
      const actions = document.createElement("span");
      actions.className = "clause-head-actions";
      if (!cl.rawClause && (cl.atoms || []).length > 1) {
        const tidy = document.createElement("button");
        tidy.className = "ghost tidy-btn"; tidy.textContent = "⤢ Auto-arrange";
        tidy.title = "re-arrange atoms for a clearer layout";
        tidy.onclick = () => { cl._needsLayout = true; this.renderCanvas(); this.changed(); };
        actions.appendChild(tidy);
      }
      if (this.model.clauses.length > 1 || cl.rawClause) {
        const del = document.createElement("button");
        del.className = "mini-btn x"; del.title = "remove alternative"; del.textContent = "×";
        del.onclick = () => { this.model.clauses.splice(ci, 1); if (!this.model.clauses.length) this.model = emptyModel(); this.renderCanvas(); this.changed(); };
        actions.appendChild(del);
      }
      head.appendChild(actions);
      card.appendChild(head);

      if (cl.rawClause != null) {
        const raw = document.createElement("div");
        raw.className = "clause-raw";
        raw.innerHTML = `<div class="raw-note">Advanced clause, edit as Prolog` +
        (cl.why ? ` <span class="raw-why">(${escapeHtml(cl.why)})</span>` : "") + `:</div>`;
        const ta = document.createElement("textarea");
        ta.className = "rule-text raw-clause"; ta.rows = 2; ta.value = cl.rawClause;
        ta.addEventListener("input", () => { cl.rawClause = ta.value; this.changed(); });
        raw.appendChild(ta);
        card.appendChild(raw);
        return card;
      }

      // Molecule area.
      const mol = document.createElement("div");
      mol.className = "mol-area dropzone";
      mol.dataset.ci = ci;
      const selMol = this.selected && this.selected.ci === ci && this.selected.kind === "mol";
      if (selMol) mol.classList.add("selected");
      mol.innerHTML = `<span class="area-label">Whole molecule</span>`;
      (cl.molChips || []).forEach((ch, idx) => mol.appendChild(this.chipEl(ch.pred, () => { cl.molChips.splice(idx, 1); this.renderCanvas(); this.changed(); }, null, ci)));
      (cl.groups || []).filter((g) => g.inMol).forEach((g) => mol.appendChild(this.molNotBox(cl, ci, g)));
      if (!(cl.molChips || []).length && !(cl.groups || []).some((g) => g.inMol)) {
        mol.insertAdjacentHTML("beforeend", `<span class="area-hint">drop a molecule property here (e.g. aromatic)</span>`);
      }
      const addNot = document.createElement("button");
      addNot.className = "ghost mol-add-not";
      addNot.textContent = "+ not";
      addNot.title = "add a NOT box: the molecule must not have the properties dropped into it";
      addNot.onclick = (e) => {
        e.stopPropagation();
        const g = { id: newId(), kind: "not", inMol: true, molChips: [] };
        (cl.groups = cl.groups || []).push(g);
        this.selected = { ci, kind: "group", gid: g.id };
        this.renderCanvas(); this.changed();
      };
      mol.appendChild(addNot);
      mol.addEventListener("click", (e) => { if (!e.target.closest(".chip, .mol-not")) this.select({ ci, kind: "mol" }); });
      this.wireDrop(mol, "molecule", (pred) => { this.addChip(cl.molChips, pred); this.renderCanvas(); this.changed(); });
      card.appendChild(mol);

      // Atom canvas.
      const canvas = document.createElement("div");
      canvas.className = "atom-canvas";
      canvas.dataset.ci = ci;
      this.frames(cl).forEach((g) => canvas.appendChild(this.groupFrame(cl, ci, g)));
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("class", "bond-layer");
      canvas.appendChild(svg);
      (cl.atoms || []).forEach((a) => canvas.appendChild(this.atomBox(cl, ci, a)));
      const canvasActions = document.createElement("div");
      canvasActions.className = "canvas-actions";
      const button = (text, title, onclick) => {
        const b = document.createElement("button");
        b.className = "ghost"; b.textContent = text; b.title = title; b.onclick = onclick;
        canvasActions.appendChild(b);
      };
      button("+ not box", "a pattern the molecule must NOT contain: drag atoms into the box, or drop atom properties on it", () => {
        const g = this.newFrame(cl, "not");
        this.selected = { ci, kind: "group", gid: g.id };
        this.renderCanvas(); this.changed();
      });
      button("+ count box", "how often a pattern occurs: drag atoms into the box, or drop atom properties on it", () => {
        const g = this.newFrame(cl, "count");
        this.selected = { ci, kind: "group", gid: g.id };
        this.renderCanvas(); this.changed();
      });
      button("+ atom", "add an atom to the pattern", () => {
        const a = { id: newId(), chips: [], x: 24 + (cl.atoms.length % 4) * 172, y: 24 + Math.floor(cl.atoms.length / 4) * 130 };
        cl.atoms.push(a); this.renderCanvas(); this.changed();
      });
      canvas.appendChild(canvasActions);
      // Drop an atom-scope predicate on empty canvas → new atom carrying it.
      this.wireDrop(canvas, "atom", (pred, e) => {
        if (e && e.target.closest(".atom-box, .group-frame")) return; // handled there
        const rect = canvas.getBoundingClientRect();
        const a = { id: newId(), chips: [{ pred }], x: (e ? e.clientX - rect.left - 60 : 40), y: (e ? e.clientY - rect.top - 20 : 40) };
        cl.atoms.push(a); this.renderCanvas(); this.changed();
      }, true);
      card.appendChild(canvas);
      return card;
    },

    // A NOT box over molecule properties, inline in the "Whole molecule" strip.
    molNotBox(cl, ci, g) {
      const box = document.createElement("span");
      box.className = "mol-not dropzone";
      if (this.isSelected(ci, g)) box.classList.add("selected");
      box.innerHTML = `<span class="group-kind">not</span>`;
      (g.molChips || []).forEach((ch, idx) => box.appendChild(this.chipEl(ch.pred, () => { g.molChips.splice(idx, 1); this.renderCanvas(); this.changed(); }, null, ci)));
      if (!(g.molChips || []).length) box.insertAdjacentHTML("beforeend", `<span class="area-hint">drop here</span>`);
      const rm = document.createElement("button");
      rm.className = "chip-x"; rm.textContent = "×"; rm.title = "remove this NOT box";
      rm.onclick = (e) => { e.stopPropagation(); this.removeGroup(cl, g); };
      box.appendChild(rm);
      box.addEventListener("click", (e) => { e.stopPropagation(); if (!e.target.closest(".chip")) this.select({ ci, kind: "group", gid: g.id }); });
      this.wireDrop(box, "molecule", (pred) => { this.addChip(g.molChips, pred); this.renderCanvas(); this.changed(); });
      return box;
    },

    isSelected(ci, g) {
      const s = this.selected;
      return !!(s && s.ci === ci && s.kind === "group" && s.gid === g.id);
    },

    // Remove a box. A canvas box is unwrapped (its atoms stay, in the main pattern).
    removeGroup(cl, g) {
      this.members(cl, g).forEach((a) => { delete a.group; delete a.counted; });
      cl.groups = (cl.groups || []).filter((x) => x !== g);
      this.renderCanvas(); this.changed();
    },

    // A not/count box on the canvas: a frame behind its atoms, with the count
    // condition in its header.
    groupFrame(cl, ci, g) {
      const f = document.createElement("div");
      f.className = `group-frame kind-${g.kind} dropzone`;
      f.dataset.gid = g.id;
      if (this.isSelected(ci, g)) f.classList.add("selected");
      Object.assign(f.style, { left: g.x + "px", top: g.y + "px", width: g.w + "px", height: g.h + "px" });

      const head = document.createElement("div");
      head.className = "group-head";
      if (g.kind === "not") {
        head.innerHTML = `<span class="group-grip" title="drag to move the box">⠿</span>` +
          `<span class="group-kind">not</span><span class="group-desc" title="the molecule must not contain any match of the pattern in this box">no match in the molecule</span>`;
      } else {
        const labels = { "=": "exactly", ">=": "at least", "<=": "at most", ">": "more than", "<": "fewer than", between: "between" };
        const opts = COUNT_OPS.map((o) => `<option value="${escapeHtml(o)}"${o === g.op ? " selected" : ""}>${labels[o]}</option>`).join("");
        head.innerHTML = `<span class="group-grip" title="drag to move the box">⠿</span>` +
          `<span class="group-kind">count</span><select class="group-op">${opts}</select>` +
          `<input class="group-n" type="number" min="0" value="${escapeHtml(g.n)}">` +
          (g.op === "between" ? `<span class="group-desc">and</span><input class="group-n2" type="number" min="0" value="${escapeHtml(g.n2 != null ? g.n2 : g.n)}">` : "") +
          `<span class="group-desc" title="the number of different combinations of the atoms marked # that match this pattern">matches</span>`;
        head.querySelector(".group-op").addEventListener("change", (e) => {
          g.op = e.target.value;
          if (g.op === "between" && g.n2 == null) g.n2 = (parseInt(g.n, 10) || 0) + 1;
          this.renderCanvas(); this.changed();
        });
        head.querySelector(".group-n").addEventListener("input", (e) => { g.n = parseInt(e.target.value, 10) || 0; this.changed(); });
        const n2 = head.querySelector(".group-n2");
        if (n2) n2.addEventListener("input", (e) => { g.n2 = parseInt(e.target.value, 10) || 0; this.changed(); });
      }
      (g.molChips || []).forEach((ch, idx) => head.appendChild(this.chipEl(ch.pred, () => { g.molChips.splice(idx, 1); this.renderCanvas(); this.changed(); }, null, ci)));
      const rm = document.createElement("button");
      rm.className = "mini-btn x"; rm.textContent = "×";
      rm.title = "remove the box (its atoms stay, as part of the main pattern)";
      rm.onclick = (e) => { e.stopPropagation(); this.removeGroup(cl, g); };
      head.appendChild(rm);
      f.appendChild(head);
      if (!this.members(cl, g).length) {
        // A count box counts its atoms: without one it is left out of the rule (with
        // its molecule properties), so say so rather than drop them silently.
        const idle = g.kind === "count" && (g.molChips || []).length;
        f.insertAdjacentHTML("beforeend", idle
          ? `<div class="area-hint group-hint warn">not part of the rule until it has an atom to count: drag atoms here, or drop atom properties</div>`
          : `<div class="area-hint group-hint">drag atoms here, or drop atom properties</div>`);
      }
      const resize = document.createElement("div");
      resize.className = "group-resize"; resize.title = "drag to resize";
      f.appendChild(resize);

      f.addEventListener("click", (e) => {
        if (!e.target.closest(".chip, .mini-btn, select, input, .group-resize")) this.select({ ci, kind: "group", gid: g.id });
      });
      this.wireDrop(f, ["atom", "molecule"], (pred, e, scope) => {
        if (scope === "molecule") { this.addChip(g.molChips, pred); }
        else {
          const rect = f.parentElement.getBoundingClientRect();
          cl.atoms.push({ id: newId(), chips: [{ pred }], group: g.id,
            counted: g.kind === "count" && !this.members(cl, g).some((x) => x.counted),
            x: Math.max(g.x + 6, e.clientX - rect.left - 60), y: Math.max(g.y + 34, e.clientY - rect.top - 20) });
        }
        this.renderCanvas(); this.changed();
      }, true);
      this.wireFrameDrag(head.querySelector(".group-grip"), f, cl, ci, g);
      this.wireFrameResize(resize, f, cl, ci, g);
      return f;
    },

    wireFrameDrag(grip, f, cl, ci, g) {
      grip.addEventListener("pointerdown", (e) => {
        e.preventDefault();
        const canvas = f.parentElement;
        const sx = e.clientX, sy = e.clientY, gx = g.x, gy = g.y;
        const mem = this.members(cl, g).map((a) => [a, a.x, a.y]);
        const move = (ev) => {
          const dx = Math.max(-gx, ev.clientX - sx), dy = Math.max(-gy, ev.clientY - sy);
          g.x = gx + dx; g.y = gy + dy;
          this.styleFrame(canvas, g);
          for (const [a, ax, ay] of mem) {
            a.x = ax + dx; a.y = ay + dy;
            const box = canvas.querySelector(`.atom-box[data-aid="${a.id}"]`);
            if (box) { box.style.left = a.x + "px"; box.style.top = a.y + "px"; }
          }
          this.drawBonds(ci);
        };
        const up = () => {
          window.removeEventListener("pointermove", move);
          window.removeEventListener("pointerup", up);
          this.fitCanvas(ci); this.drawBonds(ci); this.changed();
        };
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", up);
      });
    },

    wireFrameResize(handle, f, cl, ci, g) {
      handle.addEventListener("pointerdown", (e) => {
        e.preventDefault(); e.stopPropagation();
        const sx = e.clientX, sy = e.clientY, w = g.w, h = g.h;
        const move = (ev) => {
          g.w = Math.max(200, w + ev.clientX - sx); g.h = Math.max(90, h + ev.clientY - sy);
          this.styleFrame(f.parentElement, g);
        };
        const up = () => {
          window.removeEventListener("pointermove", move);
          window.removeEventListener("pointerup", up);
          this.fitFrames(cl, ci); this.fitCanvas(ci); this.drawBonds(ci);
        };
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", up);
      });
    },

    atomBox(cl, ci, a) {
      const box = document.createElement("div");
      box.className = "atom-box dropzone";
      box.dataset.ci = ci; box.dataset.aid = a.id;
      box.style.left = (a.x || 0) + "px";
      box.style.top = (a.y || 0) + "px";
      if (this.selected && this.selected.ci === ci && this.selected.kind === "atom" && this.selected.atomId === a.id) box.classList.add("selected");

      const head = document.createElement("div");
      head.className = "atom-head";
      head.innerHTML = `<span class="atom-grip" title="drag to move (into or out of a box)">⠿ atom</span>`;
      const g = (cl.groups || []).find((x) => x.id === a.group && !x.inMol);
      if (g && g.kind === "count") {
        const cnt = document.createElement("button");
        cnt.className = "atom-count" + (a.counted ? " on" : "");
        cnt.textContent = "#";
        cnt.title = a.counted
          ? "counted: the box counts the different atoms (combinations) marked #. Click to only require this atom."
          : "not counted: this atom only has to exist for each counted match. Click to count it.";
        cnt.onclick = (e) => { e.stopPropagation(); a.counted = !a.counted; this.renderCanvas(); this.changed(); };
        head.appendChild(cnt);
      }
      if (g) box.classList.add("in-" + g.kind);
      const bondH = document.createElement("button");
      bondH.className = "atom-bond-handle"; bondH.title = "drag to another atom to bond"; bondH.textContent = "🔗";
      const rm = document.createElement("button");
      rm.className = "mini-btn x"; rm.title = "remove atom"; rm.textContent = "×";
      rm.onclick = (e) => {
        e.stopPropagation();
        cl.atoms = cl.atoms.filter((x) => x.id !== a.id);
        cl.bonds = (cl.bonds || []).filter((bd) => bd.a !== a.id && bd.b !== a.id);
        this.renderCanvas(); this.changed();
      };
      head.appendChild(bondH); head.appendChild(rm);
      box.appendChild(head);

      const chips = document.createElement("div");
      chips.className = "atom-chips";
      (a.chips || []).forEach((ch, idx) => chips.appendChild(this.chipEl(ch.pred,
        () => { a.chips.splice(idx, 1); this.renderCanvas(); this.changed(); },
        () => { ch.pred = ch.pred.startsWith("not ") ? ch.pred.slice(4) : "not " + ch.pred; this.renderCanvas(); this.changed(); },
        ci)));
      if (!(a.chips || []).length) chips.innerHTML = `<span class="area-hint">drop atom properties</span>`;
      box.appendChild(chips);

      box.addEventListener("click", (e) => { if (!e.target.closest(".chip, .mini-btn, .atom-bond-handle")) this.select({ ci, kind: "atom", atomId: a.id }); });
      this.wireDrop(box, "atom", (pred) => { this.addChip(a.chips, pred); this.renderCanvas(); this.changed(); });
      this.wireAtomDrag(box, cl, ci, a);
      this.wireBondHandle(bondH, cl, ci, a);
      return box;
    },

    // A property chip; `onNegate` (atom chips) adds a "¬" toggle between p and not p.
    // A generated predicate's chip in clause `ci` gets an "unfold" button.
    chipEl(pred, onRemove, onNegate, ci) {
      const chip = document.createElement("span");
      chip.className = "chip" + (pred.startsWith("not ") ? " neg" : "");
      chip.innerHTML = `<span class="chip-label">${escapeHtml(labelFor(pred))}</span>`;
      const base = pred.replace(/^not /, "");
      // Not on a negated atom chip: its definition would constrain that atom from
      // inside a not box, which the editor can't draw.
      const negAtom = onNegate && pred.startsWith("not ");
      if (ci != null && this.unfoldCb && base.startsWith("aux_") && !negAtom) {
        chip.title = base;
        const u = document.createElement("button");
        u.className = "chip-unfold"; u.textContent = "⊞";
        u.title = "unfold: replace this generated predicate by its definition (atoms and bonds)";
        u.onclick = (e) => { e.stopPropagation(); this.unfoldPred(ci, base, u); };
        chip.appendChild(u);
      }
      if (onNegate) {
        const n = document.createElement("button");
        n.className = "chip-not"; n.textContent = "¬";
        n.title = pred.startsWith("not ") ? "drop the negation" : "negate: the atom must NOT have this property";
        n.onclick = (e) => { e.stopPropagation(); onNegate(); };
        chip.appendChild(n);
      }
      const x = document.createElement("button");
      x.className = "chip-x"; x.textContent = "×"; x.title = "remove";
      x.onclick = (e) => { e.stopPropagation(); onRemove(); };
      chip.appendChild(x);
      return chip;
    },

    // Replace generated predicate `pred` in clause `ci` by its definition: the server
    // unfolds the clause (only that predicate, and the helpers it uses), and the result
    // — one clause per alternative of the definition — takes the clause's place.
    // unfoldCb(clauseModel, pred) → {model?, error?}.
    async unfoldPred(ci, pred, btn) {
      const cl = this.model.clauses[ci];
      if (!cl) return;
      const sent = JSON.stringify(cl);
      if (btn) btn.disabled = true;
      let data;
      try { data = await this.unfoldCb(JSON.parse(sent), pred); } catch (e) { if (btn) btn.disabled = false; return; }
      // The clause was edited (or the rule reloaded) meanwhile: the result is stale.
      if (this.model.clauses[ci] !== cl || JSON.stringify(cl) !== sent) return;
      if (btn) btn.disabled = false;
      if (data && data.error) { if (this.notifyCb) this.notifyCb(data.error); return; }
      const clauses = data && data.model ? data.model.clauses || [] : [];
      // Server ids restart at a1 each parse: renumber past the ones in use.
      clauses.forEach((c) => renumber(c));
      if (!clauses.length) return;
      this.model.clauses.splice(ci, 1, ...clauses);
      this.selected = null;
      this.renderCanvas(); this.changed();
    },

    // ── selection (click-to-add) ──────────────────────────────────────────────
    select(sel) { this.selected = sel; this.renderCanvas(); },
    onCanvasClick(e) {
      if (e.target === this.canvasEl) { this.selected = null; this.renderCanvas(); }
    },
    addToSelected(pred, scope) {
      const s = this.selected;
      // An "any"-scope block goes wherever the user has selected (an atom if one is
      // selected, otherwise the molecule area).
      if (s && s.kind === "group") {
        const cl = this.model.clauses[s.ci];
        const g = cl && (cl.groups || []).find((x) => x.id === s.gid);
        if (!g) return;
        if (scope === "any") scope = g.inMol ? "molecule" : "atom";
        if (scope === "molecule") this.addChip(g.molChips, pred);
        else if (scope === "atom" && !g.inMol) {
          const n = this.members(cl, g).length;
          cl.atoms.push({ id: newId(), chips: [{ pred }], group: g.id,
            counted: g.kind === "count" && !this.members(cl, g).some((x) => x.counted),
            x: g.x + 12 + (n % 2) * 150, y: g.y + 44 + Math.floor(n / 2) * 96 });
        } else return;
        this.renderCanvas(); this.changed();
        return;
      }
      if (scope === "any") scope = (s && s.kind === "atom") ? "atom" : "molecule";
      if (scope === "molecule") {
        const ci = s ? s.ci : 0;  // the selected atom's clause, too
        const cl = this.model.clauses[ci]; if (!cl || cl.rawClause) return;
        this.addChip(cl.molChips, pred);
      } else if (scope === "atom") {
        if (s && s.kind === "atom") {
          const cl = this.model.clauses[s.ci];
          const a = cl.atoms.find((x) => x.id === s.atomId);
          if (a) this.addChip(a.chips, pred);
        } else {
          const ci = s ? s.ci : 0;
          const cl = this.model.clauses[ci] || this.model.clauses[0];
          if (!cl || cl.rawClause) return;
          cl.atoms.push({ id: newId(), chips: [{ pred }], x: 24 + (cl.atoms.length % 4) * 172, y: 24 });
        }
      }
      this.renderCanvas(); this.changed();
    },

    // ── drag/drop of palette blocks onto a zone ───────────────────────────────
    // `scope` is one scope or a list; with a list, an "any" block counts as the first.
    // `add(pred, event | undefined, scope)`.
    wireDrop(zone, scope, add, passEvent) {
      // An "any"-scope block (an arity-1 generated predicate whose atom-vs-molecule
      // role is unknown) is accepted by both the molecule area and atom boxes.
      const scopes = Array.isArray(scope) ? scope : [scope];
      const accepts = (ds) => scopes.includes(ds) || ds === "any";
      zone.addEventListener("dragover", (e) => {
        if (accepts(Editor._dragScope)) { e.preventDefault(); zone.classList.add("drop-hover"); }
      });
      zone.addEventListener("dragleave", () => zone.classList.remove("drop-hover"));
      zone.addEventListener("drop", (e) => {
        zone.classList.remove("drop-hover");
        let payload; try { payload = JSON.parse(e.dataTransfer.getData("text/plain")); } catch (_) { return; }
        if (!payload || !accepts(payload.scope)) return;
        e.preventDefault(); e.stopPropagation();
        add(payload.pred, passEvent ? e : undefined, payload.scope === "any" ? scopes[0] : payload.scope);
      });
    },

    // ── freeform atom drag (reposition) ───────────────────────────────────────
    wireAtomDrag(box, cl, ci, a) {
      const grip = box.querySelector(".atom-grip");
      grip.addEventListener("pointerdown", (e) => {
        e.preventDefault();
        const canvas = box.parentElement;
        const rect = canvas.getBoundingClientRect();
        const offX = e.clientX - box.offsetLeft, offY = e.clientY - box.offsetTop;
        const startX = a.x, startY = a.y;
        const move = (ev) => {
          // Below the last row the canvas grows (fitCanvas), so a box can be dragged down.
          let x = Math.max(0, Math.min(ev.clientX - offX, rect.width - box.offsetWidth));
          let y = Math.max(0, ev.clientY - offY);
          box.style.left = x + "px"; box.style.top = y + "px";
          a.x = x; a.y = y; this.drawBonds(ci);
          const over = this.frameAt(cl, x + box.offsetWidth / 2, y + box.offsetHeight / 2);
          canvas.querySelectorAll(".group-frame").forEach((f) =>
            f.classList.toggle("drop-hover", !!over && f.dataset.gid === over.id));
        };
        const up = () => {
          window.removeEventListener("pointermove", move);
          window.removeEventListener("pointerup", up);
          canvas.querySelectorAll(".group-frame").forEach((f) => f.classList.remove("drop-hover"));
          // Dropped inside a box's frame → the atom belongs to that box; outside → main pattern.
          const g = this.frameAt(cl, a.x + box.offsetWidth / 2, a.y + box.offsetHeight / 2);
          if ((g ? g.id : null) !== (a.group || null) && !this.moveToGroup(cl, a, g)) {
            a.x = startX; a.y = startY;  // would leave a bond between two boxes
            box.classList.add("refused");
            setTimeout(() => box.classList.remove("refused"), 600);
          }
          this.renderCanvas();
          this.changed();
        };
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", up);
      });
    },

    // ── bond drawing from an atom's handle ────────────────────────────────────
    wireBondHandle(handle, cl, ci, a) {
      handle.addEventListener("pointerdown", (e) => {
        e.preventDefault(); e.stopPropagation();
        const canvas = handle.closest(".atom-canvas");
        const svg = canvas.querySelector(".bond-layer");
        const rect = canvas.getBoundingClientRect();
        const start = this.atomCenter(canvas, a.id);
        const temp = document.createElementNS("http://www.w3.org/2000/svg", "line");
        temp.setAttribute("class", "bond-temp");
        temp.setAttribute("x1", start.x); temp.setAttribute("y1", start.y);
        temp.setAttribute("x2", start.x); temp.setAttribute("y2", start.y);
        svg.appendChild(temp);
        const move = (ev) => { temp.setAttribute("x2", ev.clientX - rect.left); temp.setAttribute("y2", ev.clientY - rect.top); };
        const up = (ev) => {
          window.removeEventListener("pointermove", move);
          window.removeEventListener("pointerup", up);
          temp.remove();
          const target = document.elementFromPoint(ev.clientX, ev.clientY);
          const tbox = target && target.closest(".atom-box");
          const other = tbox && cl.atoms.find((x) => x.id === tbox.dataset.aid);
          // Atoms of two different boxes can't be bonded: each box's atoms exist only in it.
          if (other && a.group && other.group && a.group !== other.group) {
            tbox.classList.add("refused");
            setTimeout(() => tbox.classList.remove("refused"), 600);
          } else if (tbox && tbox.dataset.aid && tbox.dataset.aid !== a.id) {
            cl.bonds = cl.bonds || [];
            cl.bonds.push({ a: a.id, b: tbox.dataset.aid, pred: "has_bond_to" });
            cl._needsLayout = true;  // reflow so the new bond isn't hidden behind an atom
            this.renderCanvas(); this.changed();
          }
        };
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", up);
      });
    },

    atomCenter(canvas, aid) {
      const box = canvas.querySelector(`.atom-box[data-aid="${aid}"]`);
      if (!box) return { x: 0, y: 0 };
      return { x: box.offsetLeft + box.offsetWidth / 2, y: box.offsetTop + box.offsetHeight / 2 };
    },

    drawBonds(ci) {
      const canvas = this.canvasEl.querySelector(`.atom-canvas[data-ci="${ci}"]`);
      if (!canvas) return;
      const svg = canvas.querySelector(".bond-layer");
      const cl = this.model.clauses[ci];
      svg.setAttribute("width", canvas.clientWidth);
      svg.setAttribute("height", canvas.clientHeight);
      // Clear existing (keep any temp line).
      svg.querySelectorAll(".bond-group").forEach((n) => n.remove());
      (cl.bonds || []).forEach((b, idx) => {
        const p1 = this.atomCenter(canvas, b.a), p2 = this.atomCenter(canvas, b.b);
        const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
        g.setAttribute("class", "bond-group");
        const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
        line.setAttribute("x1", p1.x); line.setAttribute("y1", p1.y);
        line.setAttribute("x2", p2.x); line.setAttribute("y2", p2.y);
        line.setAttribute("class", "bond-line" + ((b.pred === NEQ || b.pred === LT || b.pred.startsWith("not ")) ? " pseudo" : ""));
        g.appendChild(line);
        // Type label / control at the midpoint.
        const mx = (p1.x + p2.x) / 2, my = (p1.y + p2.y) / 2;
        const fo = document.createElementNS("http://www.w3.org/2000/svg", "foreignObject");
        fo.setAttribute("x", mx - 40); fo.setAttribute("y", my - 14);
        fo.setAttribute("width", 80); fo.setAttribute("height", 28);
        const wrap = document.createElement("div");
        wrap.className = "bond-ctrl";
        wrap.innerHTML = this.bondSelect(b.pred) + `<button class="bond-x" title="remove bond">×</button>`;
        wrap.querySelector("select").addEventListener("change", (e) => { b.pred = e.target.value; this.changed(); });
        wrap.querySelector(".bond-x").addEventListener("click", () => { cl.bonds.splice(idx, 1); this.renderCanvas(); this.changed(); });
        fo.appendChild(wrap);
        g.appendChild(fo);
        svg.appendChild(g);
      });
    },

    bondSelect(pred) {
      const opts = [
        ["has_bond_to", "any"], ["bSINGLE", "single"], ["bDOUBLE", "double"],
        ["bTRIPLE", "triple"], ["bAROMATIC", "aromatic"],
        ["bSTEREOE", "stereo E"], ["bSTEREOZ", "stereo Z"],
        ["bSTEREOCIS", "stereo cis"], ["bSTEREOTRANS", "stereo trans"],
        [NEQ, "≠ different"], [LT, "< order"],
      ];
      if (!opts.some(([p]) => p === pred)) opts.push([pred, labelFor(pred)]);
      return `<select>` + opts.map(([p, l]) => `<option value="${escapeHtml(p)}"${p === pred ? " selected" : ""}>${escapeHtml(l)}</option>`).join("") + `</select>`;
    },
  };

  function escapeHtml(s) {
    return (s == null ? "" : String(s)).replace(/[&<>"]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }
  // Public API.
  global.Blocks = {
    init: (o) => Editor.init(o),
    setCatalog: (c, a) => Editor.setCatalog(c, a),
    load: (m) => Editor.load(m),
    getModel: () => Editor.getModel(),
    _pure: { describe, groupOf, forceLayout, renumber, emptyModel },
  };

  if (typeof module !== "undefined" && module.exports) module.exports = global.Blocks._pure;

})(typeof window !== "undefined" ? window : globalThis);
