// Settings of the research client: every agronomic parameter of the configuration files that can be set through the web.
// Three levels (global by an administrator, user, parcel) over the file defaults; the form is generated from the registry
// that GET /api/settings returns (label, unit, type, default, range, recommended values, source, status). Loaded before
// app.js and used by it (#/settings view and the "Parcel settings" card); it relies on its globals ($, t, api, esc) at call
// time only. The blind rating screen never reads any of this.
"use strict";

(function () {
  const MESSAGES = {
    type: "Not a valid value of this type.", range: "Outside the allowed range ({min} to {max}).", choice: "Not one of the allowed choices.",
    shape: "The shape of the value is not allowed.", order: "Values must be in increasing order.", last_row: "The last row must reach {min}.",
    first_row: "The first row must start at {value}.", contiguous: "Ranges must follow each other without gaps.",
    range_order: "A range starts after it ends.", items: "The number of items must be between {min} and {max}.",
    duplicate: "Duplicate entries.", unknown_key: "Unknown parameter.", not_editable: "This parameter cannot be changed here.",
    not_editable_by_user: "The administrator did not allow users to change this parameter.",
    global_outside_limit: "The global value is outside this limit.", relation_masked: "The limit for high must not exceed the limit for medium.",
    relation_mixed: "The limit for high must not exceed the limit for medium.", relation_interior: "The pixel count for high must not be below the one for medium.",
    required: "A reason is required for this change.", too_long: "The text is too long.", generic: "The change was refused.",
  };
  const STATUS = {verified: "verified", partly: "partly verified", disputed: "disputed by the source", no_source: "no source", development: "development value"};
  const LAYER = {default: "file default", global: "global", user: "user", parcel: "parcel", admin_role: "administrator role"};
  const PARCEL_GROUPS = ["irrigation", "soil", "crop_coefficients", "phenology", "fertilization", "field_ops"];
  const lang = () => (window.SmartI18n ? SmartI18n.lang() : "en");
  const loc = (o) => (o ? (lang() === "en" ? o.en : (o.sr || o.en)) : "");
  const clone = (v) => JSON.parse(JSON.stringify(v === undefined ? null : v));
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const short = (v) => { const s = JSON.stringify(v); return s && s.length > 90 ? s.slice(0, 88) + "…" : (s || "–"); };

  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === false || v == null) continue;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (v === true) el.setAttribute(k, "");
      else el.setAttribute(k, v);
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    return el;
  }
  const msg = (code, params) => {
    const text = t(MESSAGES[code] || MESSAGES.generic, params || {});
    return text.replace(/\{(\w+)\}/g, "–");
  };
  const errText = (e) => msg(e.code, e.params);
  const fmtWhen = (s) => (s ? String(s).replace("T", " ").slice(0, 16) : "–");

  // ------------------------------------------------------------------ recommended-range warnings (same rule as the server)
  function recWarnings(entry, value) {
    const rec = entry.recommended, basis = entry.range_basis;
    if (!rec || value == null) return [];
    const out = [];
    const chk = (v, r, where, b) => { if (r && typeof v === "number" && (v < r[0] || v > r[1])) out.push({where, range: r, value: v, basis: b}); };
    if (entry.kind === "int" || entry.kind === "float") chk(value, rec, "", basis);
    else if (entry.kind === "pair") value.forEach((v, i) => chk(v, rec[i], String(i), basis[i]));
    else if (entry.kind === "map") Object.entries(value).forEach(([k, v]) => chk(v, rec[k], k, basis[k]));
    else if (entry.kind === "table") value.forEach((row, i) => Object.entries(rec).forEach(([c, r]) => { if (c in row) chk(row[c], r, `${i + 1}.${c}`, basis[c]); }));
    return out;
  }
  // The wording of a warning: a range of the cited source, or a development band around the file default (no source).
  function warnText(w, entry) {
    const params = {min: w.range[0], max: w.range[1]};
    const where = w.where ? " (" + w.where + ")" : "";
    if (w.basis === "source") return [t("Outside the recommended values ({min} to {max}) of the source.", params), where, entry.source ? [" ", t("Source: "), entry.source.text] : ""];
    return [t("Outside the recommended range ({min} to {max}), a development band around the file default; no source is claimed.", params), where];
  }

  // ------------------------------------------------------------------ value editors (DOM, no innerHTML)
  function numInput(col, value, bounds, onChange, label, step) {
    const el = h("input", {type: "number", step: step || "any", "aria-label": label, inputmode: "decimal",
                           min: bounds && bounds.min != null ? bounds.min : false, max: bounds && bounds.max != null ? bounds.max : false});
    el.value = value == null ? "" : value;
    el.addEventListener("input", () => onChange(el.value === "" ? null : Number(el.value)));
    return el;
  }
  function textList(value, choices, item, onChange, label) {
    const el = h("input", {type: "text", "aria-label": label, spellcheck: "false", autocomplete: "off"});
    el.value = (value || []).join(", ");
    el.addEventListener("input", () => {
      const parts = el.value.split(",").map((x) => x.trim()).filter(Boolean);
      onChange(parts.map((x) => (item === "scalar" && x !== "" && !isNaN(Number(x)) ? Number(x) : x)));
    });
    return el;
  }
  function cellEditor(col, value, bounds, onChange) {
    const cb = (bounds.columns || {})[col.name] || {};
    const label = loc(col.label);
    if (col.kind === "int" || col.kind === "float") return numInput(col, value, cb, onChange, label, col.kind === "int" ? "1" : "any");
    if (col.kind === "enum") {
      const sel = h("select", {"aria-label": label}, h("option", {value: ""}, "–"), (col.choices || []).map((c) => h("option", {value: c}, c)));
      sel.value = value == null ? "" : value;
      sel.addEventListener("change", () => onChange(sel.value === "" ? null : sel.value));
      return sel;
    }
    if (col.kind === "bool") {
      const cbx = h("input", {type: "checkbox", "aria-label": label});
      cbx.checked = !!value;
      cbx.addEventListener("change", () => onChange(cbx.checked));
      return cbx;
    }
    if (col.kind === "list") return textList(value, col.choices, "token", onChange, label);
    const el = h("input", {type: "text", "aria-label": label, maxlength: 80});
    el.value = value == null ? "" : value;
    el.addEventListener("input", () => onChange(el.value === "" ? null : el.value));
    return el;
  }
  function rowsEditor(entry, rows, bounds, onChange, disabled) {
    const cols = entry.shape.columns;
    const wrap = h("div", {class: "tbl-scroll"});
    const draw = () => {
      wrap.textContent = "";
      const maxItems = bounds.max_items, minItems = bounds.min_items || 0;
      const table = h("table", {class: "set-table"},
        h("thead", {}, h("tr", {}, cols.map((c) => h("th", {scope: "col"}, loc(c.label))), h("th", {}, h("span", {class: "visually-hidden"}, t("Row actions"))))),
        h("tbody", {}, rows.map((row, i) => h("tr", {},
          cols.map((c) => {
            const ed = cellEditor(c, row[c.name], bounds, (v) => { if (v == null) delete row[c.name]; else row[c.name] = v; onChange(rows); });
            if (disabled) ed.disabled = true;
            return h("td", {}, ed);
          }),
          h("td", {}, h("button", {type: "button", class: "button secondary small", disabled: disabled || rows.length <= minItems,
                                    "aria-label": t("Remove row {n}", {n: i + 1}), onclick: () => { rows.splice(i, 1); onChange(rows); draw(); }}, "×"))))));
      wrap.append(table, h("button", {type: "button", class: "button secondary small", disabled: disabled || (maxItems != null && rows.length >= maxItems),
                                      onclick: () => { rows.push(cols.reduce((o, c) => { if (!c.optional) { const cb = (bounds.columns || {})[c.name] || {}; o[c.name] = c.kind === "enum" ? c.choices[0] : (cb.min != null ? cb.min : (c.min != null ? c.min : 0)); } return o; }, {})); onChange(rows); draw(); }}, t("Add row")));
    };
    draw();
    return wrap;
  }
  function editor(entry, value, disabled, onChange) {
    const b = entry.bounds, k = entry.kind;
    const lab = loc(entry.label);
    let el;
    if (k === "bool") {
      el = h("label", {class: "switch"}, h("input", {type: "checkbox", disabled, checked: !!value, "aria-label": lab, onchange: (e) => onChange(e.target.checked)}), h("span", {}, value ? t("On") : t("Off")));
      el.querySelector("input").addEventListener("change", (e) => { el.querySelector("span").textContent = e.target.checked ? t("On") : t("Off"); });
    } else if (k === "int" || k === "float") {
      el = numInput(null, value, b, onChange, lab, k === "int" ? "1" : "any");
    } else if (k === "str") {
      el = entry.shape.max_len > 120 ? h("textarea", {rows: 3, maxlength: entry.shape.max_len, "aria-label": lab}) : h("input", {type: "text", maxlength: entry.shape.max_len, "aria-label": lab});
      el.value = value == null ? "" : value;
      el.addEventListener("input", () => onChange(el.value));
    } else if (k === "enum") {
      el = h("select", {"aria-label": lab}, entry.shape.choices.map((c) => h("option", {value: c}, c)));
      el.value = value;
      el.addEventListener("change", () => onChange(el.value));
    } else if (k === "pair") {
      const v = clone(value);
      const eb = b.elements || [b, b];
      el = h("span", {class: "pair"}, numInput(null, v[0], eb[0], (x) => { v[0] = x; onChange(clone(v)); }, lab + " – " + t("from")), h("span", {"aria-hidden": "true"}, "–"),
             numInput(null, v[1], eb[1], (x) => { v[1] = x; onChange(clone(v)); }, lab + " – " + t("to")));
    } else if (k === "list") {
      el = h("span", {class: "list-ed"}, textList(value, entry.shape.choices, entry.shape.item, onChange, lab),
             entry.shape.choices ? h("small", {class: "hint"}, t("Allowed: {list}", {list: entry.shape.choices.join(", ")})) : null);
    } else if (k === "map") {
      const v = clone(value);
      el = h("span", {class: "map-ed"}, entry.shape.keys.map((key) => h("label", {class: "map-cell"}, h("span", {}, key),
              numInput(null, v[key], (b.keys || {})[key] || b, (x) => { v[key] = x; onChange(clone(v)); }, `${lab} – ${key}`))));
    } else if (k === "table") {
      el = rowsEditor(entry, clone(value), b, (rows) => onChange(clone(rows)), disabled);
    } else if (k === "groups") {
      const groups = clone(value);
      const wrap = h("div", {class: "groups-ed"});
      const draw = () => {
        wrap.textContent = "";
        groups.forEach((rows, gi) => wrap.append(h("div", {class: "group-ed"}, h("p", {class: "hint"}, t("Group {n}", {n: gi + 1}),
          " ", h("button", {type: "button", class: "button secondary small", disabled, onclick: () => { groups.splice(gi, 1); onChange(clone(groups)); draw(); }}, t("Remove group"))),
          rowsEditor(entry, rows, b, () => onChange(clone(groups)), disabled))));
        wrap.append(h("button", {type: "button", class: "button secondary small", disabled: disabled || groups.length >= (b.max_items || 6),
                                 onclick: () => { groups.push([{input: entry.shape.columns[0].choices[0], min_reliability: "medium"}]); onChange(clone(groups)); draw(); }}, t("Add group")));
      };
      draw();
      el = wrap;
    }
    if (disabled) for (const n of el.matches && el.matches("input,select,textarea") ? [el] : el.querySelectorAll("input,select,textarea,button")) n.disabled = true;
    return el;
  }

  const fmtVal = (entry, v) => {
    if (v == null) return "–";
    if (entry.kind === "pair") return v.join(" – ");
    if (entry.kind === "list") return v.join(", ") || "–";
    if (entry.kind === "bool") return v ? t("On") : t("Off");
    if (entry.kind === "map") return Object.entries(v).map(([a, b]) => `${a} ${b}`).join(", ");
    if (entry.kind === "table" || entry.kind === "groups") return t("{n} rows", {n: entry.kind === "groups" ? v.reduce((s, g) => s + g.length, 0) : v.length});
    return String(v);
  };
  const rangeText = (entry) => {
    const b = entry.bounds, u = entry.unit ? " " + entry.unit : "";
    if (["int", "float", "pair", "map"].includes(entry.kind) && (b.min != null || b.max != null)) return t("Allowed: {min} to {max}", {min: b.min != null ? b.min : "–", max: b.max != null ? b.max + u : "–"});
    if (["list", "table", "groups"].includes(entry.kind)) return t("Allowed: {min} to {max} items", {min: b.min_items || 0, max: b.max_items});
    return "";
  };
  const recText = (entry) => {
    const r = entry.recommended, basis = entry.range_basis;
    if (!r) return "";
    const tag = (b) => (b === "source" ? "" : " · " + t("development band"));
    if (entry.kind === "int" || entry.kind === "float") return t("Recommended: {min} to {max}", {min: r[0], max: r[1]}) + tag(basis);
    if (entry.kind === "pair") return t("Recommended: {list}", {list: r.map((x, i) => `${x[0]}–${x[1]}${tag(basis[i])}`).join("; ")});
    return t("Recommended: {list}", {list: Object.entries(r).map(([k, x]) => `${k} ${x[0]}–${x[1]}${tag(basis[k])}`).join("; ")});
  };
  const physText = (entry) => {
    const b = entry.hard, u = entry.unit ? " " + entry.unit : "";
    if (["int", "float", "pair", "map"].includes(entry.kind) && (b.min != null || b.max != null)) return t("Physical bounds: {min} to {max}", {min: b.min != null ? b.min : "–", max: b.max != null ? b.max + u : "–"});
    if (["list", "table", "groups"].includes(entry.kind)) return t("Allowed: {min} to {max} items", {min: b.min_items || 0, max: b.max_items});
    return "";
  };
  const limitText = (entry) => {
    const l = entry.default_limit;
    if (!l) return "";
    const flat = entry.kind === "pair" ? l : (entry.kind === "int" || entry.kind === "float" ? [l] : Object.values(l));
    const lo = Math.min(...flat.map((x) => x[0])), hi = Math.max(...flat.map((x) => x[1]));
    return t("Default limit: {min} to {max}", {min: lo, max: hi});
  };
  const srcLine = (entry) => {
    const s = entry.source;
    const link = s && s.url ? h("a", {href: s.url, target: "_blank", rel: "noopener noreferrer"}, s.text) : (s ? s.text : null);
    return h("p", {class: "set-source"}, h("span", {class: "badge st-" + entry.status}, t(STATUS[entry.status])), " ", link ? [t("Source: "), link] : t("No source claimed."));
  };

  // ------------------------------------------------------------------ a parameter list editing one layer
  function createList(root, opts) {
    // opts: scope ("user" | "parcel" | "global"), parcelId, groups (filter), admin (bool), onSaved
    const st = {data: null, draft: {}, errors: {}, group: "", q: "", flash: "", busy: false};
    const scope = opts.scope;
    const path = () => (scope === "parcel" ? `/settings/parcels/${encodeURIComponent(opts.parcelId)}` : `/settings/${scope}`);
    const below = (e) => {
      const L = e.layers;
      if (scope === "global") return clone(e.default);
      if (scope === "user") return clone(L.global !== undefined ? L.global : e.default);
      return clone(L.user !== undefined ? L.user : (L.global !== undefined ? L.global : e.default));
    };
    const current = (e) => (e.layers[scope] !== undefined ? clone(e.layers[scope]) : below(e));
    const value = (e) => (e.key in st.draft ? st.draft[e.key] : current(e));
    const writable = () => {
      const c = st.data.capabilities;
      return c.can_write && (scope !== "global" || c.is_admin);
    };

    async function load() {
      const q = opts.parcelId ? `?parcel_id=${encodeURIComponent(opts.parcelId)}` : "";
      st.data = await api("/settings" + q);
      st.map = {}; for (const e of st.data.entries) st.map[e.key] = e;
      draw();
    }
    function visible(e) {
      if (opts.groups && !opts.groups.includes(e.group)) return false;
      if (st.group && e.group !== st.group) return false;
      if (st.q) {
        const hay = (loc(e.label) + " " + e.key + " " + (e.source ? e.source.text : "")).toLowerCase();
        if (!hay.includes(st.q.toLowerCase())) return false;
      }
      return true;
    }
    function layerBadge(e) {
      const l = e.layer;
      return h("span", {class: "badge ly-" + l, title: t("Where the effective value comes from")}, t(LAYER[l]));
    }
    function card(e) {
      const ro = e.readonly ? loc(e.readonly) : "";
      const userLocked = scope !== "global" && !e.user_editable && !ro;
      const disabled = !writable() || !!ro || userLocked;
      const dirty = e.key in st.draft && !same(st.draft[e.key], current(e));
      const changed = e.layers[scope] !== undefined;
      const val = value(e);
      const warn = h("div", {class: "set-warn", role: "status"});
      const err = h("p", {class: "error", role: "alert"});
      const refresh = () => {
        warn.textContent = "";
        for (const w of recWarnings(e, value(e))) {
          warn.append(h("p", {class: "warning"}, warnText(w, e)));
        }
        err.textContent = st.errors[e.key] || "";
        card.classList.toggle("is-dirty", e.key in st.draft && !same(st.draft[e.key], current(e)));
        const bar = root.querySelector(".set-savebar");
        if (bar) updateBar(bar);
      };
      const card = h("article", {class: "set-param" + (dirty ? " is-dirty" : ""), id: "sp-" + e.key.replace(/[^\w]/g, "-")},
        h("div", {class: "set-head"},
          h("h3", {}, loc(e.label)),
          h("span", {class: "set-badges"}, layerBadge(e), changed ? h("span", {class: "badge changed"}, t("changed")) : null)),
        h("p", {class: "set-key"}, h("code", {}, e.key), e.unit ? h("span", {class: "hint-inline"}, e.unit) : null),
        ro ? h("p", {class: "hint"}, t("Read only: "), ro) : (userLocked ? h("p", {class: "hint"}, t("Set by the administrator; users cannot change it.")) : null),
        h("div", {class: "set-edit"}, editor(e, val, disabled, (v) => { st.draft[e.key] = v; delete st.errors[e.key]; refresh(); })),
        h("p", {class: "hint set-default"}, t("File default: {v}", {v: fmtVal(e, e.default)}),
          e.layer !== "default" ? [" · ", t("Effective: {v}", {v: fmtVal(e, e.effective)})] : null),
        [rangeText(e), recText(e)].filter(Boolean).map((x) => h("p", {class: "hint"}, x)),
        warn, err,
        e.readonly && !e.source ? null : srcLine(e),
        loc(e.note) ? h("p", {class: "hint set-note"}, loc(e.note)) : null,
        loc(e.hint) ? h("p", {class: "hint set-note"}, loc(e.hint)) : null,
        e.ignored.length ? h("p", {class: "warning"}, t("An earlier value is ignored: {reason}", {reason: e.ignored.map((i) => errText({code: i.reason, params: {}}) + " (" + t(LAYER[i.layer]) + ")").join("; ")})) : null,
        writable() && !disabled && (changed || dirty) ? h("div", {class: "set-actions"},
          changed ? h("button", {type: "button", class: "button secondary small", onclick: () => reset([e.key])}, scope === "global" ? t("Reset to file default") : t("Reset to inherited value")) : null,
          dirty ? h("button", {type: "button", class: "button secondary small", onclick: () => { delete st.draft[e.key]; draw(); }}, t("Discard edit")) : null) : null);
      refresh();
      return card;
    }
    function updateBar(bar) {
      const n = Object.keys(st.draft).filter((k) => st.map[k] && !same(st.draft[k], current(st.map[k]))).length;
      bar.hidden = n === 0;                                   // shown while there is something to save
      bar.querySelector(".set-count").textContent = t("{n} unsaved changes", {n});
      bar.querySelector(".set-save").disabled = !n || st.busy;
      bar.querySelector(".set-discard").disabled = !n;
    }
    async function save(reasonInput) {
      const values = {};
      for (const [k, v] of Object.entries(st.draft)) if (st.map[k] && !same(v, current(st.map[k]))) values[k] = v;
      if (!Object.keys(values).length) return;
      st.busy = true; st.errors = {}; st.flash = "";
      try {
        const r = await api(path(), {method: "PUT", body: JSON.stringify({values, reason: reasonInput.value, base_version: st.data.versions[scope === "parcel" ? "parcel" : scope]})});
        st.draft = {}; st.busy = false;
        st.flash = r.warnings && r.warnings.length ? t("Saved. {n} values are outside the recommended range.", {n: r.warnings.length}) : t("Saved.");
        await load();
        if (opts.onSaved) opts.onSaved();
      } catch (ex) {
        const body = ex.body || null;
        const errs = (body && body.errors) || [];
        for (const er of errs) if (er.key !== "reason") st.errors[er.key] = errText(er);
        const general = errs.find((x) => x.key === "reason" || !st.map[x.key]);
        st.flash = !body ? ex.message : (general ? errText(general) : t("Some values were refused. Check the marked parameters."));
        st.busy = false;
        draw();
      } finally { st.busy = false; }
    }
    async function reset(keys, everything) {
      try {
        await api(path() + "/reset", {method: "POST", body: JSON.stringify(everything ? {all: true, reason: root.querySelector(".set-reason") ? root.querySelector(".set-reason").value : ""} : {keys, reason: root.querySelector(".set-reason") ? root.querySelector(".set-reason").value : ""})});
        for (const k of keys || []) delete st.draft[k];
        st.flash = t("Reset.");
        await load();
        if (opts.onSaved) opts.onSaved();
      } catch (ex) {
        const b = ex.body;
        st.flash = b && b.errors && b.errors.length ? errText(b.errors[0]) : ex.message;
        draw();
      }
    }
    function draw() {
      if (!st.data) return;
      const d = st.data, c = d.capabilities;
      root.textContent = "";
      if (!c.can_write) {
        root.append(h("div", {class: "banner", role: "note"}, h("p", {}, t("You are not signed in. You see the effective values read only; sign in or create an account to save your own settings.")),
          typeof openAccount === "function" ? h("button", {type: "button", class: "button primary small", onclick: () => openAccount("up")}, t("Create an account")) : null));
      } else if (scope === "global" && !c.is_admin) {
        root.append(h("p", {class: "hint"}, t("Only an administrator can change global values.")));
      }
      const groups = d.groups.filter((g) => !opts.groups || opts.groups.includes(g.id));
      const tools = h("div", {class: "set-tools"},
        h("label", {class: "field compact"}, h("span", {class: "visually-hidden"}, t("Search parameters")),
          h("input", {type: "search", placeholder: t("Search parameters"), "aria-label": t("Search parameters"), value: st.q, oninput: (ev) => { st.q = ev.target.value; list(); }})),
        h("div", {class: "chips", role: "group", "aria-label": t("Parameter groups")},
          h("button", {type: "button", class: "chip", "aria-pressed": st.group === "" ? "true" : "false", onclick: () => { st.group = ""; draw(); }}, t("All")),
          groups.map((g) => h("button", {type: "button", class: "chip", "aria-pressed": st.group === g.id ? "true" : "false", onclick: () => { st.group = g.id; draw(); }}, loc(g.label)))));
      root.append(tools);
      const listEl = h("div", {class: "set-list"});
      root.append(listEl);
      function list() {
        listEl.textContent = "";
        let n = 0;
        for (const g of groups) {
          const es = d.entries.filter((e) => e.group === g.id && visible(e));
          if (!es.length) continue;
          n += es.length;
          listEl.append(h("section", {class: "set-group", "aria-labelledby": "sg-" + g.id}, h("h2", {id: "sg-" + g.id}, loc(g.label), " ", h("span", {class: "hint-inline"}, String(es.length))), es.map(card)));
        }
        if (!n) listEl.append(h("p", {class: "hint"}, t("No parameters match.")));
      }
      list();
      if (writable()) {
        const reason = h("input", {type: "text", class: "set-reason", maxlength: 300, "aria-label": t("Reason for the change"), placeholder: scope === "global" ? t("Reason (required)") : t("Reason (optional)")});
        const bar = h("div", {class: "set-savebar glass", role: "region", "aria-label": t("Save changes")},
          h("span", {class: "set-count", role: "status"}, ""), reason,
          h("button", {type: "button", class: "button secondary set-discard", onclick: () => { st.draft = {}; st.errors = {}; draw(); }}, t("Discard")),
          h("button", {type: "button", class: "button primary set-save", onclick: () => save(reason)}, t("Save changes")));
        root.append(bar);
        root.append(h("p", {class: "set-flash", role: "status"}, st.flash));
        updateBar(bar);
        const mine = d.entries.filter((e) => e.layers[scope] !== undefined && (!opts.groups || opts.groups.includes(e.group))).length;
        if (mine) root.append(h("p", {}, resetAll(mine)));
      }
    }
    function resetAll(n) {
      const btn = h("button", {type: "button", class: "button secondary small", onclick: () => {
        if (btn.dataset.armed !== "1") { btn.dataset.armed = "1"; btn.textContent = t("Confirm: reset {n} parameters", {n}); return; }
        reset(null, true);
      }}, scope === "global" ? t("Reset all global values to the file defaults") : t("Reset all my values"));
      return btn;
    }
    return {load, draw, state: st};
  }

  // ------------------------------------------------------------------ history: versions with restore, audit log
  function versionsPanel(root, scope, parcelId, labelOf, onRestored) {
    const reason = h("input", {type: "text", maxlength: 300, class: "set-reason", "aria-label": t("Reason for the change"), placeholder: scope === "global" || scope === "limits" ? t("Reason (required)") : t("Reason (optional)")});
    const out = h("div", {});
    const status = h("p", {class: "set-flash", role: "status"});
    const q = () => `?scope=${scope}` + (parcelId ? `&parcel_id=${encodeURIComponent(parcelId)}` : "");
    async function restore(version, keys) {
      try {
        const r = await api("/settings/restore", {method: "POST", body: JSON.stringify({scope, parcel_id: parcelId || undefined, version, keys, reason: reason.value})});
        status.textContent = r.unchanged ? t("Nothing to change.") : t("Restored as version {n}.", {n: r.version});
        await load();
        if (onRestored) onRestored();
      } catch (ex) {
        const b = ex.body;
        status.textContent = b && b.errors && b.errors.length ? errText(b.errors[0]) : ex.message;
      }
    }
    async function load() {
      let rows = [];
      try { rows = (await api("/settings/versions" + q())).versions; } catch (ex) { out.textContent = ex.message; return; }
      out.textContent = "";
      out.append(h("p", {}, h("button", {type: "button", class: "button secondary small", onclick: () => restore("default")}, t("Restore to the file defaults (clears every override of this level)"))));
      if (!rows.length) { out.append(h("p", {class: "hint"}, t("No versions yet."))); return; }
      for (const v of rows) {
        out.append(h("details", {class: "set-version"},
          h("summary", {}, `v${v.n} · ${fmtWhen(v.at)} · ${v.actor || "–"} · ${t(v.action)}${v.reason ? " · " + v.reason : ""}`),
          h("p", {}, h("button", {type: "button", class: "button secondary small", onclick: () => restore(v.n)}, t("Restore this whole version"))),
          h("ul", {class: "set-changed"}, (v.changed || []).map((k) => h("li", {}, h("span", {}, labelOf(k) + ": "), h("code", {title: JSON.stringify(v.values[k])}, k in v.values ? short(v.values[k]) : t("file default")), " ",
            h("button", {type: "button", class: "button secondary small", "aria-label": t("Restore this parameter: {name}", {name: labelOf(k)}), onclick: () => restore(v.n, [k])}, t("Restore this parameter")))))));
      }
    }
    root.append(h("div", {}, h("label", {class: "field"}, h("span", {}, t("Reason for the change")), reason), status, out));
    return {load};
  }
  function auditPanel(root, opts) {
    const st = {offset: 0, total: 0};
    const f = {scope: h("select", {"aria-label": t("Level")}, ["", "global", "limits", "user", "parcel"].filter((x) => opts.admin || !["global", "limits"].includes(x)).map((x) => h("option", {value: x}, x ? t(LAYER[x] || "limits") : t("All levels")))),
               param: h("input", {type: "text", "aria-label": t("Parameter"), placeholder: t("Parameter"), maxlength: 120}),
               who: h("input", {type: "text", "aria-label": t("User id"), placeholder: t("User id"), maxlength: 64}),
               since: h("input", {type: "date", "aria-label": t("From")}), until: h("input", {type: "date", "aria-label": t("To")}),
               action: h("select", {"aria-label": t("Action")}, ["", "set", "reset", "restore", "limit"].map((x) => h("option", {value: x}, x ? t(x) : t("All actions"))))};
    if (!opts.admin) { f.scope.value = opts.parcelId ? "parcel" : "user"; f.scope.disabled = true; }
    const body = h("div", {class: "tbl-scroll"});
    const pager = h("p", {class: "row"});
    async function load() {
      const p = new URLSearchParams({limit: "25", offset: String(st.offset)});
      if (f.scope.value) p.set("scope", f.scope.value);
      if (opts.parcelId) p.set("parcel_id", opts.parcelId);
      for (const k of ["param", "who", "since", "until", "action"]) if (f[k].value) p.set(k, f[k].value);
      let r;
      try { r = await api("/settings/audit?" + p.toString()); } catch (ex) { body.textContent = ex.message; return; }
      st.total = r.total;
      body.textContent = "";
      if (!r.items.length) body.append(h("p", {class: "hint"}, t("No entries.")));
      else body.append(h("table", {class: "set-table"}, h("thead", {}, h("tr", {}, [t("When"), t("Who"), t("Level"), t("Parameter"), t("Old value"), t("New value"), t("Action"), t("Reason")].map((x) => h("th", {scope: "col"}, x)))),
        h("tbody", {}, r.items.map((i) => h("tr", {}, h("td", {}, fmtWhen(i.at)), h("td", {}, i.actor || "–"), h("td", {}, t(LAYER[i.scope] || "limits")), h("td", {}, h("code", {}, i.param)),
          h("td", {}, h("code", {title: JSON.stringify(i.old)}, short(i.old))), h("td", {}, h("code", {title: JSON.stringify(i.new)}, short(i.new))), h("td", {}, t(i.action)), h("td", {}, i.reason))))));
      pager.textContent = "";
      pager.append(h("span", {class: "hint"}, t("{n} entries", {n: r.total})),
        h("button", {type: "button", class: "button secondary small", disabled: st.offset === 0, onclick: () => { st.offset = Math.max(0, st.offset - 25); load(); }}, t("Previous")),
        h("button", {type: "button", class: "button secondary small", disabled: st.offset + 25 >= r.total, onclick: () => { st.offset += 25; load(); }}, t("Next")));
    }
    const filters = h("form", {class: "set-filters", onsubmit: (ev) => { ev.preventDefault(); st.offset = 0; load(); }},
      opts.admin ? [f.scope, f.who] : [], f.param, f.since, f.until, f.action, h("button", {type: "submit", class: "button secondary small"}, t("Filter")));
    root.append(filters, body, pager);
    return {load};
  }

  // ------------------------------------------------------------------ administrator limits
  function limitsPanel(root, onSaved) {
    const st = {data: null, draft: {}, group: "", q: ""};
    const reason = h("input", {type: "text", class: "set-reason", maxlength: 300, "aria-label": t("Reason for the change"), placeholder: t("Reason (required)")});
    const flash = h("p", {class: "set-flash", role: "status"});
    const listEl = h("div", {class: "set-list"});
    const num = (v) => (v === "" || v == null ? null : Number(v));
    async function load() {
      st.data = await api("/settings");
      st.map = {}; for (const e of st.data.entries) st.map[e.key] = e;
      draw();
    }
    function row(e) {
      const lim = clone(st.draft[e.key] || e.limit || {});
      const dirty = e.key in st.draft;
      const put = (patch) => { st.draft[e.key] = Object.assign(clone(st.draft[e.key] || e.limit || {}), patch); card.classList.add("is-dirty"); };
      const ue = h("input", {type: "checkbox", checked: lim.user_editable !== undefined ? lim.user_editable : e.user_editable_default, disabled: !!e.readonly,
        "aria-label": t("Users may change: {name}", {name: loc(e.label)}), onchange: (ev) => put({user_editable: ev.target.checked})});
      const inputs = [];
      const hb = e.hard;
      const dl = e.default_limit ? (e.kind === "pair" ? e.default_limit : (e.kind === "int" || e.kind === "float" ? [e.default_limit] : Object.values(e.default_limit))) : [];
      const dmin = dl.length ? Math.min(...dl.map((x) => x[0])) : null, dmax = dl.length ? Math.max(...dl.map((x) => x[1])) : null;
      if (["int", "float", "pair", "map"].includes(e.kind)) {
        inputs.push(h("label", {class: "map-cell"}, h("span", {}, t("Minimum")), h("input", {type: "number", step: "any", value: lim.min != null ? lim.min : "", placeholder: dmin != null ? String(dmin) : (hb.min != null ? String(hb.min) : ""), "aria-label": t("Minimum: {name}", {name: loc(e.label)}), oninput: (ev) => put({min: num(ev.target.value)})})),
                    h("label", {class: "map-cell"}, h("span", {}, t("Maximum")), h("input", {type: "number", step: "any", value: lim.max != null ? lim.max : "", placeholder: dmax != null ? String(dmax) : (hb.max != null ? String(hb.max) : ""), "aria-label": t("Maximum: {name}", {name: loc(e.label)}), oninput: (ev) => put({max: num(ev.target.value)})})));
      }
      if (["list", "table", "groups"].includes(e.kind)) {
        inputs.push(h("label", {class: "map-cell"}, h("span", {}, t("Fewest items")), h("input", {type: "number", step: "1", value: lim.min_items != null ? lim.min_items : "", placeholder: String(hb.min_items || 0), "aria-label": t("Fewest items: {name}", {name: loc(e.label)}), oninput: (ev) => put({min_items: num(ev.target.value)})})),
                    h("label", {class: "map-cell"}, h("span", {}, t("Most items")), h("input", {type: "number", step: "1", value: lim.max_items != null ? lim.max_items : "", placeholder: String(hb.max_items), "aria-label": t("Most items: {name}", {name: loc(e.label)}), oninput: (ev) => put({max_items: num(ev.target.value)})})));
      }
      if (["table", "groups"].includes(e.kind)) {
        for (const c of e.shape.columns.filter((x) => (x.kind === "int" || x.kind === "float"))) {
          const cl = ((lim.columns || {})[c.name]) || {};
          const setCol = (patch) => { const cur = clone((st.draft[e.key] || e.limit || {}).columns || {}); cur[c.name] = Object.assign(cur[c.name] || {}, patch); put({columns: cur}); };
          inputs.push(h("label", {class: "map-cell"}, h("span", {}, `${loc(c.label)} ${t("min")}`), h("input", {type: "number", step: "any", value: cl.min != null ? cl.min : "", placeholder: c.min != null ? String(c.min) : "", "aria-label": `${loc(e.label)} – ${loc(c.label)} ${t("min")}`, oninput: (ev) => setCol({min: num(ev.target.value)})})),
                      h("label", {class: "map-cell"}, h("span", {}, `${loc(c.label)} ${t("max")}`), h("input", {type: "number", step: "any", value: cl.max != null ? cl.max : "", placeholder: c.max != null ? String(c.max) : "", "aria-label": `${loc(e.label)} – ${loc(c.label)} ${t("max")}`, oninput: (ev) => setCol({max: num(ev.target.value)})})));
        }
      }
      const card = h("article", {class: "set-param" + (dirty ? " is-dirty" : "")},
        h("div", {class: "set-head"}, h("h3", {}, loc(e.label)), h("span", {class: "set-badges"}, h("span", {class: "badge st-" + e.status}, t(STATUS[e.status])))),
        h("p", {class: "set-key"}, h("code", {}, e.key)),
        h("label", {class: "switch"}, ue, h("span", {}, t("Users may change this"))),
        e.readonly ? h("p", {class: "hint"}, t("Read only: "), loc(e.readonly)) : h("div", {class: "limit-grid"}, inputs),
        physText(e) ? h("p", {class: "hint"}, physText(e)) : null,
        limitText(e) ? h("p", {class: "hint"}, limitText(e), " · ", t("empty fields keep the default limit")) : null,
        e.limit && Object.keys(e.limit).length ? h("p", {}, h("button", {type: "button", class: "button secondary small", onclick: () => { st.draft[e.key] = null; flash.textContent = t("Marked to be cleared; press Save limits."); card.classList.add("is-dirty"); }}, t("Clear the limit"))) : null);
      return card;
    }
    function draw() {
      if (!st.data) return;
      listEl.textContent = "";
      const groups = st.data.groups;
      const tools = h("div", {class: "set-tools"},
        h("label", {class: "field compact"}, h("span", {class: "visually-hidden"}, t("Search parameters")), h("input", {type: "search", placeholder: t("Search parameters"), "aria-label": t("Search parameters"), value: st.q, oninput: (ev) => { st.q = ev.target.value; fill(); }})),
        h("div", {class: "chips", role: "group", "aria-label": t("Parameter groups")}, h("button", {type: "button", class: "chip", "aria-pressed": st.group === "" ? "true" : "false", onclick: () => { st.group = ""; draw(); }}, t("All")),
          groups.map((g) => h("button", {type: "button", class: "chip", "aria-pressed": st.group === g.id ? "true" : "false", onclick: () => { st.group = g.id; draw(); }}, loc(g.label)))));
      const holder = h("div", {});
      function fill() {
        holder.textContent = "";
        for (const g of groups) {
          if (st.group && g.id !== st.group) continue;
          const es = st.data.entries.filter((e) => e.group === g.id && (!st.q || (loc(e.label) + " " + e.key).toLowerCase().includes(st.q.toLowerCase())));
          if (es.length) holder.append(h("section", {class: "set-group"}, h("h2", {}, loc(g.label)), es.map(row)));
        }
      }
      fill();
      listEl.append(tools, holder);
    }
    const bar = h("div", {class: "set-savebar is-static glass", role: "region", "aria-label": t("Save limits")}, reason,
      h("button", {type: "button", class: "button primary", onclick: async () => {
        const limits = {};
        for (const [k, v] of Object.entries(st.draft)) {
          if (v === null) { limits[k] = null; continue; }
          const o = {};
          for (const [a, b] of Object.entries(v)) { if (b != null && b !== "" && !(typeof b === "object" && !Object.keys(b).length)) o[a] = b; }
          limits[k] = o;
        }
        if (!Object.keys(limits).length) { flash.textContent = t("Nothing to save."); return; }
        try {
          await api("/settings/limits", {method: "PUT", body: JSON.stringify({limits, reason: reason.value})});
          st.draft = {}; flash.textContent = t("Limits saved.");
          await load(); if (onSaved) onSaved();
        } catch (ex) {
          const b = ex.body;
          flash.textContent = b && b.errors && b.errors.length ? b.errors.map((x) => (st.map[x.key] ? loc(st.map[x.key].label) + ": " : "") + errText(x)).join(" ") : ex.message;
        }
      }}, t("Save limits")));
    root.append(listEl, bar, flash);
    return {load};
  }

  // ------------------------------------------------------------------ the #/settings view
  const view = {tab: "mine", adminTab: "global", parcelId: "", root: null, caps: null, seq: 0};
  function tabs(items, current, onPick, label) {
    return h("div", {class: "tabs wrap", role: "tablist", "aria-label": label}, items.map(([id, text]) => h("button", {type: "button", role: "tab", id: "stab-" + id,
      "aria-selected": id === current ? "true" : "false", tabindex: id === current ? "0" : "-1", onclick: () => onPick(id),
      onkeydown: (ev) => {
        const ids = items.map((i) => i[0]), i = ids.indexOf(id);
        const next = ev.key === "ArrowRight" ? ids[(i + 1) % ids.length] : ev.key === "ArrowLeft" ? ids[(i + ids.length - 1) % ids.length] : null;
        if (next) { ev.preventDefault(); view.focusTab = next; onPick(next); }
      }}, text)));
  }
  async function protocolPane(root) {
    root.append(h("p", {class: "hint"}, t("These files define the experiment and are locked. They are shown here for reference and cannot be changed through the web; evaluation reads the files only, and settings saved here never reach it.")));
    let files = [];
    try { files = (await api("/settings/protocol")).files; } catch (ex) { root.append(h("p", {class: "error"}, ex.message)); return; }
    for (const f of files) root.append(h("details", {class: "card set-proto"}, h("summary", {}, h("code", {}, f.file), " ", h("span", {class: "badge st-no_source"}, t("locked"))), h("p", {class: "hint"}, loc(f.reason)), h("pre", {}, JSON.stringify(f.values, null, 2))));
  }
  async function parcelPane(root, rerender) {
    let list = [];
    try { list = await api("/parcels"); } catch (ex) { root.append(h("p", {class: "error"}, ex.message)); return; }
    if (!list.length) { root.append(h("p", {class: "hint"}, t("No parcels yet. Draw a parcel first."))); return; }
    if (!view.parcelId || !list.some((p) => p.id === view.parcelId)) view.parcelId = list[0].id;
    const sel = h("select", {"aria-label": t("Parcel"), onchange: (ev) => { view.parcelId = ev.target.value; rerender(); }}, list.map((p) => h("option", {value: p.id}, p.name)));
    sel.value = view.parcelId;
    root.append(h("label", {class: "field"}, h("span", {}, t("Parcel")), sel));
    const box = h("div", {});
    root.append(box);
    const lp = createList(box, {scope: "parcel", parcelId: view.parcelId});
    await lp.load();
    const hist = h("details", {class: "card"}, h("summary", {}, t("History of this parcel's settings")));
    root.append(hist);
    const labelOf = (k) => (lp.state.map && lp.state.map[k] ? loc(lp.state.map[k].label) : k);
    const changes = h("div", {});
    const vers = h("div", {});
    hist.append(h("h3", {}, t("Versions")), vers, h("h3", {}, t("Changes")), changes);
    let loaded = false;
    hist.addEventListener("toggle", async () => {
      if (!hist.open || loaded) return;
      loaded = true;
      const vp = versionsPanel(vers, "parcel", view.parcelId, labelOf, () => lp.load());
      await vp.load();
      const ap = auditPanel(changes, {admin: false, parcelId: view.parcelId});
      await ap.load();
    });
  }
  async function renderView() {
    // Built aside and swapped in at the end: a second render (hash change plus a tab click) must not append twice.
    const token = ++view.seq;
    const target = view.root;
    const root = h("div", {});
    let caps;
    try { caps = (await api("/settings")).capabilities; } catch (ex) { target.textContent = ""; target.append(h("p", {class: "error"}, ex.message)); return; }
    view.caps = caps;
    const items = [["mine", t("My settings")], ["parcel", t("Parcel settings")], ["protocol", t("Protocol (read only)")]];
    if (caps.is_admin) items.push(["admin", t("Admin")]);
    if (!items.some((i) => i[0] === view.tab)) view.tab = "mine";
    root.append(tabs(items, view.tab, (id) => { view.tab = id; renderView(); }, t("Settings sections")));
    const pane = h("div", {class: "set-pane", role: "tabpanel", "aria-labelledby": "stab-" + view.tab});
    root.append(pane);
    if (view.tab === "mine") {
      pane.append(h("p", {class: "hint"}, caps.accounts === "off" ? t("Local mode: you are the only user and also the administrator.") : t("Your values apply to all your parcels unless a parcel has its own value. Effective value: parcel, else yours, else global, else the file default.")));
      const box = h("div", {}); pane.append(box);
      const lp = createList(box, {scope: "user"}); await lp.load();
      const hist = h("details", {class: "card"}, h("summary", {}, t("History of my settings")));
      pane.append(hist);
      let loaded = false;
      hist.addEventListener("toggle", async () => {
        if (!hist.open || loaded || !caps.can_write) return;
        loaded = true;
        const labelOf = (k) => (lp.state.map && lp.state.map[k] ? loc(lp.state.map[k].label) : k);
        const vers = h("div", {}), aud = h("div", {});
        hist.append(h("h3", {}, t("Versions")), vers, h("h3", {}, t("Changes")), aud);
        await versionsPanel(vers, "user", "", labelOf, () => lp.load()).load();
        await auditPanel(aud, {admin: false}).load();
      });
    } else if (view.tab === "parcel") {
      if (!caps.can_write) pane.append(h("p", {class: "hint"}, t("Sign in to set values for a parcel.")));
      await parcelPane(pane, renderView);
    } else if (view.tab === "protocol") {
      await protocolPane(pane);
    } else if (view.tab === "admin") {
      const sub = [["global", t("Global values")], ["limits", t("Limits")], ["audit", t("Audit log")], ["versions", t("Versions")]];
      pane.append(tabs(sub, view.adminTab, (id) => { view.adminTab = id; renderView(); }, t("Admin sections")));
      const box = h("div", {class: "set-pane", role: "tabpanel", "aria-labelledby": "stab-" + view.adminTab}); pane.append(box);
      if (view.adminTab === "global") {
        box.append(h("p", {class: "hint"}, t("Global values apply to everyone who has not set their own value. A change here needs a reason and is recorded in the audit log.")));
        const holder = h("div", {}); box.append(holder);
        await createList(holder, {scope: "global"}).load();
      } else if (view.adminTab === "limits") {
        box.append(h("p", {class: "hint"}, t("For each parameter: whether users may change it, and the allowed range. Values outside the range are refused for everyone. An earlier user value that falls outside a new limit is ignored.")));
        await limitsPanel(box).load();
      } else if (view.adminTab === "audit") {
        await auditPanel(box, {admin: true}).load();
      } else {
        const scopeSel = h("select", {"aria-label": t("Level"), onchange: () => { draw(); }}, [["global", t("Global values")], ["limits", t("Limits")]].map(([v, x]) => h("option", {value: v}, x)));
        const holder = h("div", {});
        box.append(h("label", {class: "field"}, h("span", {}, t("Level")), scopeSel), holder);
        let all = {};
        try { (await api("/settings")).entries.forEach((e) => { all[e.key] = e; }); } catch (ex) { all = {}; }
        const draw = async () => { holder.textContent = ""; await versionsPanel(holder, scopeSel.value, "", (k) => (all[k] ? loc(all[k].label) : k), null).load(); };
        await draw();
      }
    }
    if (token === view.seq) {
      target.textContent = ""; target.append(root);
      if (view.focusTab) { const b = document.getElementById("stab-" + view.focusTab); if (b) b.focus(); view.focusTab = null; }
    }
  }
  function open() {
    view.root = document.getElementById("set-out");
    renderView();
  }
  function mountParcel(root, parcel) {
    root.textContent = "";
    const lp = createList(root, {scope: "parcel", parcelId: parcel.id, groups: PARCEL_GROUPS});
    return lp.load();
  }
  window.SmartSettings = {open, mountParcel, STATUS, LAYER};
})();
