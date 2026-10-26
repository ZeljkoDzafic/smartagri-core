// SmartAgri research client. Plain JavaScript, no build step. Talks to the research API under /api.
"use strict";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
// Answer language: the server default (SMARTAGRI_LOCALE, English unless set) until the user chooses one in Settings;
// the choice is sent with every request as X-SmartAgri-Lang. Blind rating always runs in the default locale.
function storedLang() { try { return localStorage.getItem("smartagri.lang") || ""; } catch (e) { return ""; } }
let answerLang = "en";
// With accounts on (SMARTAGRI_ACCOUNTS=optional) every state-changing request carries the CSRF token of the sa_csrf
// cookie (double submit); the session and browser cookies are HttpOnly and sent by the browser itself.
function csrfToken() {
  const m = document.cookie.match(/(?:^|;\s*)sa_csrf=([^;]*)/);
  return m ? decodeURIComponent(m[1]) : "";
}
async function api(path, opts = {}) {
  const headers = {"Content-Type": "application/json"};
  if (storedLang()) headers["X-SmartAgri-Lang"] = storedLang();
  if (opts.method && opts.method !== "GET" && csrfToken()) headers["X-CSRF-Token"] = csrfToken();
  const r = await fetch("api" + path, {...opts, headers, credentials: "same-origin"});
  const lang = r.headers.get("Content-Language");
  if (lang && !path.startsWith("/eval/")) answerLang = lang;
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof body.detail === "string" ? body.detail : r.statusText || "Request failed");
  return body;
}

// ------------------------------------------------------------------ English names of codes returned by the API.
// Texts produced by the decision model come in the answer language; sources are quoted in the corpus language.
const ACTS = {recommend: "Recommendation", conditional: "Conditional recommendation", ask: "Follow-up question",
              abstain: "No recommendation", refer: "Referral to an expert"};
const ADVICE = {irrigation_timing: "Irrigation: timing", irrigation_amount: "Irrigation: amount",
                fertilization_plan: "Top-dressing: plan and rate", fertilization_timing: "Top-dressing: timing",
                field_ops_window: "Weather window for field work", scouting: "Crop condition and field scouting",
                out_of_scope: "Outside the system's scope"};
const INPUTS = {
  phenophase: "Growth stage (BBCH)", sowing_date: "Sowing date", ndvi_latest: "NDVI, latest observation",
  ndvi_spatial_contrast: "NDVI, differences within the parcel", ndvi_trend: "NDVI, change over 14 days",
  precip_past_7d: "Rainfall, past 7 days", et0_past_7d: "Reference evapotranspiration, past 7 days",
  precip_forecast_3d: "Rainfall forecast, 3 days", precip_forecast_7d: "Rainfall forecast, 7 days",
  temp_forecast: "Temperature forecast, 7 days", wind_forecast: "Wind forecast, 7 days",
  soil_water_status: "Soil water status", soil_moisture_sensor: "Soil moisture sensor",
  soil_awc: "Soil water-holding capacity", soil_analysis: "Soil analysis", irrigation_available: "Irrigation possible",
  irrigation_efficiency: "Irrigation system efficiency", previous_fertilization: "Fertiliser applied so far",
  yield_target: "Target yield", operation: "Planned work", advice_type: "Type of advice",
  irrigation_capacity: "Irrigation system capacity", previous_crop: "Previous crop", manure: "Manure (last 12 months)",
  hybrid_fao: "Hybrid maturity group (FAO)", plant_density: "Plant density", field_observation: "Field observations (last 7 days)",
};
const RELIABILITY = {high: "high", medium: "medium", low: "low", missing: "missing"};
const ORIGIN = {measured: "measured", user_reported: "reported by the user", modeled: "model value", derived: "estimate", unknown: "unknown origin"};
const APPLICABILITY = {applicable: "applicable", conditional: "conditionally applicable", not_applicable: "not applicable"};
const VALUES = {"nema podatka": "no data", "da": "yes", "ne": "no", "nepoznato": "unknown"};
const inputName = (key, fallback) => INPUTS[key] || fallback || key;
const valueText = (v) => VALUES[String(v ?? "").trim()] || v;
const LANG = () => `lang="${esc(answerLang)}"`;
const CORPUS = 'lang="sr-Latn"';            // passages and their titles are quoted in the corpus language

let meta = null, parcel = null, conv = null, aiConv = null, pending = null, parcelsCache = [];
let drawer = null, viewer = null;

// ------------------------------------------------------------------ routing
const VIEWS = ["parcels", "new", "parcel", "rate"];
function show(view) {
  for (const v of VIEWS) $("v-" + v).hidden = v !== view;
  for (const a of document.querySelectorAll("[data-nav]")) {
    if (a.dataset.nav === view || (view === "parcel" && a.dataset.nav === "parcels")) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
}
async function route() {
  const parts = (location.hash || "#/parcels").replace(/^#\/?/, "").split("/");
  const view = parts[0] || "parcels";
  if ((view === "verify" || view === "reset") && parts[1]) { accountLink(view, decodeURIComponent(parts[1])); return; }
  if (view === "parcel" && parts[1]) { show("parcel"); await openParcel(decodeURIComponent(parts[1])); }
  else if (view === "new") { show("new"); ensureDrawer(); }
  else if (view === "rate") show("rate");
  else { show("parcels"); await loadParcels(); }
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", () => { route().then(focusView); });
function focusView() {
  const visible = VIEWS.map((v) => $("v-" + v)).find((el) => !el.hidden);
  const heading = visible && visible.querySelector("h1, h2");
  if (heading) { heading.setAttribute("tabindex", "-1"); heading.focus({preventScroll: true}); }
}

// ------------------------------------------------------------------ start
async function init() {
  const h = await api("/health");
  const chips = [["Version", h.version], ["Generator", h.llm], ["Satellite", h.satellite], ["Offline", h.offline ? "yes" : "no"],
                 ["Database", h.database], ["Retrieval", h.retrieval]];
  $("health").innerHTML = chips.map(([k, v]) => `<span class="chip-static">${esc(k)} <b>${esc(v)}</b></span>`).join("");
  meta = await api("/meta");
  $("c-variant").innerHTML = meta.variants.map((v) => `<option ${v === meta.default_variant ? "selected" : ""}>${esc(v)}</option>`).join("");
  $("c-type").innerHTML += meta.advice_types.map((t) => `<option value="${esc(t.value)}">${esc(ADVICE[t.value] || t.label)}</option>`).join("");
  if (meta.accounts && meta.accounts.enabled) await initAccount();
  await route();
}

// ------------------------------------------------------------------ parcels
function thumb(geometry) {
  const ring = geometry && geometry.type === "Polygon" && geometry.coordinates && geometry.coordinates[0];
  if (!ring || ring.length < 3) return `<svg viewBox="0 0 64 64" aria-hidden="true"></svg>`;
  const lat0 = ring.reduce((s, c) => s + c[1], 0) / ring.length, k = Math.cos(lat0 * Math.PI / 180);
  const xs = ring.map((c) => c[0] * k), ys = ring.map((c) => -c[1]);
  const minX = Math.min(...xs), minY = Math.min(...ys), span = Math.max(Math.max(...xs) - minX, Math.max(...ys) - minY) || 1;
  const pts = xs.map((x, i) => `${(10 + (x - minX) / span * 44).toFixed(1)},${(10 + (ys[i] - minY) / span * 44).toFixed(1)}`);
  return `<svg viewBox="0 0 64 64" aria-hidden="true"><path d="M${pts.join("L")}Z"/></svg>`;
}
const fmtHa = (x) => (x == null ? "–" : Number(x).toLocaleString("en", {maximumFractionDigits: 2}) + " ha");
function fmtDate(s) {
  if (!s) return "";
  const d = new Date(String(s).length === 10 ? s + "T00:00:00" : s);
  return isNaN(d) ? String(s) : d.toLocaleDateString("en-GB", {day: "numeric", month: "short", year: "numeric"});
}

const EMPTY_ART = `<svg class="empty-art" viewBox="0 0 160 110" aria-hidden="true">
  <defs><linearGradient id="ea" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="currentColor" stop-opacity=".28"/><stop offset="1" stop-color="currentColor" stop-opacity=".06"/></linearGradient></defs>
  <path d="M18 78 52 22l62 10 30 50-58 18z" fill="url(#ea)" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round" stroke-dasharray="7 6"/>
  <g fill="currentColor"><circle cx="18" cy="78" r="5"/><circle cx="52" cy="22" r="5"/><circle cx="114" cy="32" r="5"/><circle cx="144" cy="82" r="5"/><circle cx="86" cy="100" r="5"/></g>
</svg>`;

async function loadParcels() {
  const list = $("parcel-list");
  if (!parcelsCache.length) list.innerHTML = `<div class="skeleton"></div><div class="skeleton"></div>`;
  let rows;
  try { rows = await api("/parcels"); }
  catch (e) { list.innerHTML = `<p class="error">${esc(e.message)}</p>`; return; }
  parcelsCache = rows;
  showBanner();
  if (!rows.length) {
    list.innerHTML = `<div class="empty card">${EMPTY_ART}<h2>No parcels yet</h2><p>Draw a maize field on the map or paste its boundary as GeoJSON. Then fetch its data and ask a question.</p><a class="button primary" href="#/new">Draw your first parcel</a></div>`;
    return;
  }
  list.innerHTML = rows.map((p) => {
    const sow = (p.agronomic || {}).sowing_date;
    return `<a class="parcel-card" href="#/parcel/${encodeURIComponent(p.id)}">${thumb(p.geometry)}
      <span><span class="name">${esc(p.name)}</span>${unsaved() ? ` <span class="pill unsaved">Not saved</span>` : ""}<br><span class="facts">${esc(fmtHa(p.area_ha))}${sow ? " · sown " + esc(fmtDate(sow)) : ""}</span></span>
      <span class="chev" aria-hidden="true">›</span></a>`;
  }).join("");
}

// ------------------------------------------------------------------ new parcel
const EXAMPLE = {type: "Polygon", coordinates: [[[19.700, 45.320], [19.710, 45.320], [19.710, 45.326], [19.700, 45.326], [19.700, 45.320]]]};

function tileProblem(kind) {
  const note = $("map-note");
  note.textContent = kind === "off" ? "Map tiles are turned off in Settings. You can still draw on the empty grid or paste GeoJSON."
                                    : "Map tiles could not be loaded. You can still draw on the empty grid or paste GeoJSON.";
  note.hidden = false;
}
function ensureDrawer() {
  if (!window.SmartMap || !SmartMap.available()) {
    $("d-status").textContent = "The map library could not be loaded. Use the GeoJSON tab.";
    return;
  }
  if (drawer) { setTimeout(() => drawer.invalidate(), 0); return; }
  drawer = new SmartMap.Drawer($("n-map"), {onTileProblem: tileProblem, onChange: onDraw});
  setTimeout(() => drawer.invalidate(), 0);
  onDraw(drawer.state(), false);
}
function onDraw(st, fromLoad) {
  const wrap = $("n-map").parentElement;
  wrap.classList.toggle("drawing", st.drawing);
  $("d-draw").setAttribute("aria-pressed", String(st.drawing));
  $("d-draw").textContent = st.closed ? "Redraw" : st.drawing ? "Drawing…" : "Draw";
  $("d-undo").disabled = !st.count;
  $("d-finish").disabled = !(st.drawing && st.count >= 3);
  $("d-clear").disabled = !st.count;
  $("d-status").textContent = st.closed ? `Boundary closed: ${st.count} corners. Drag a corner to adjust it.`
    : st.drawing ? (st.count < 3 ? `Click the corners of the field (${st.count} of at least 3). Keyboard: pan with the arrow keys, then “Add centre point”.`
                                 : `${st.count} corners. Click the first corner, double click, or press Finish.`)
    : "No boundary yet. Press Draw to start.";
  $("n-area").textContent = st.area_ha != null ? `≈ ${fmtHa(st.area_ha)}` : "No boundary yet";
  $("n-area-hint").hidden = !(st.area_ha != null && (st.area_ha < 0.05 || st.area_ha > 200));
  if (st.geojson && !fromLoad) $("n-geom").value = JSON.stringify(st.geojson);
  if (!st.count && !fromLoad && !st.drawing) $("n-geom").value = "";
}
$("d-draw").onclick = () => { if (drawer) { drawer.start(); $("n-map").focus(); } };
$("d-point").onclick = () => drawer && drawer.addCentre();
$("d-undo").onclick = () => drawer && drawer.undo();
$("d-finish").onclick = () => drawer && drawer.finish();
$("d-clear").onclick = () => drawer && drawer.clear();

function parseGeom() {
  const text = $("n-geom").value.trim();
  if (!text) throw new Error("Draw the boundary on the map or paste GeoJSON first.");
  let g;
  try { g = JSON.parse(text); } catch (e) { throw new Error("The boundary is not valid JSON."); }
  if (g && g.type === "FeatureCollection" && g.features && g.features.length) g = g.features[0];
  if (g && g.type === "Feature") g = g.geometry;
  return g;
}
function showGeomOnMap() {
  $("g-msg").textContent = "";
  try {
    const g = parseGeom();
    selectTab($("tab-draw"));
    ensureDrawer();
    if (drawer && !drawer.load(g)) $("g-msg").textContent = "Only a Polygon (or a Feature with a Polygon) can be shown on the map.";
    else if (drawer) $("n-area").textContent = `≈ ${fmtHa(drawer.state().area_ha)}`;
  } catch (e) { $("g-msg").textContent = e.message; }
}
$("n-show").onclick = showGeomOnMap;
$("n-example").onclick = () => { $("n-geom").value = JSON.stringify(EXAMPLE); $("g-msg").textContent = ""; };
$("n-file").onchange = async (e) => {
  const file = e.target.files && e.target.files[0];
  if (!file) return;
  $("n-geom").value = await file.text();
  e.target.value = "";
  showGeomOnMap();
};

// tabs (arrow keys move between tabs)
const tabs = [$("tab-draw"), $("tab-geojson")];
function selectTab(tab) {
  for (const t of tabs) {
    const on = t === tab;
    t.setAttribute("aria-selected", String(on)); t.tabIndex = on ? 0 : -1;
    $(t.getAttribute("aria-controls")).hidden = !on;
  }
  if (tab === tabs[0] && drawer) setTimeout(() => drawer.invalidate(), 0);
}
tabs.forEach((t, i) => {
  t.onclick = () => selectTab(t);
  t.onkeydown = (e) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
    selectTab(next); next.focus();
  };
});

$("n-form").onsubmit = async (e) => {
  e.preventDefault();
  $("n-msg").textContent = "";
  const btn = $("n-save");
  try {
    if (!$("n-name").value.trim()) throw new Error("Enter a name for the parcel.");
    const body = {name: $("n-name").value, sowing_date: $("n-sowing").value || null, irrigation_available: $("n-irr").value,
                  geometry: parseGeom()};
    if ($("n-pinned").value) body.pinned_as_of = $("n-pinned").value;
    btn.setAttribute("aria-busy", "true");
    const p = await api("/parcels", {method: "POST", body: JSON.stringify(body)});
    parcelsCache = [p].concat(parcelsCache.filter((x) => x.id !== p.id));
    location.hash = "#/parcel/" + encodeURIComponent(p.id);
  } catch (err) { $("n-msg").textContent = err.message; }
  finally { btn.removeAttribute("aria-busy"); }
};

// ------------------------------------------------------------------ parcel
function qualityList(rows) {
  if (!rows || !rows.length) return `<p class="hint">No data yet.</p>`;
  const present = rows.filter((r) => r.reliability !== "missing"), missing = rows.filter((r) => r.reliability === "missing");
  const absent = missing.length ? `<details class="raw missing"><summary>Missing inputs (${missing.length})</summary>
    <p class="hint">${missing.map((r) => esc(inputName(r.input, r.label))).join(" · ")}</p></details>` : "";
  if (!present.length) return `<p class="hint">No input is available yet.</p>` + absent;
  return `<ul class="qlist">` + present.map((r) => {
    const age = r.age_days != null ? `${Number(r.age_days).toLocaleString("en", {maximumFractionDigits: 1})} d old` : "";
    return `<li><span class="q-label">${esc(inputName(r.input, r.label))}</span><span class="q-value">${esc(valueText(r.value_text))}</span>
      <span class="q-meta"><span class="pill rel-${esc(r.reliability)}">${esc(RELIABILITY[r.reliability] || r.reliability_label)}</span>
      <span>${esc(ORIGIN[r.origin] || r.origin_label)}</span>${age ? `<span>· ${esc(age)}</span>` : ""}</span></li>`;
  }).join("") + `</ul>` + absent;
}

async function openParcel(id) {
  try { parcel = await api("/parcels/" + encodeURIComponent(id)); }
  catch (e) { $("p-title").textContent = "Parcel not found"; $("p-meta").textContent = e.message; $("p-quality").innerHTML = ""; return; }
  conv = null; aiConv = null; pending = null;
  $("p-temp").hidden = !unsaved();
  const ag = parcel.agronomic || {};
  $("p-title").textContent = parcel.name;
  $("p-meta").textContent = [fmtHa(parcel.area_ha), ag.sowing_date ? "sown " + fmtDate(ag.sowing_date) : "sowing date unknown",
                             parcel.pinned_as_of ? "decision date " + fmtDate(parcel.pinned_as_of) : ""].filter(Boolean).join(" · ");
  $("c-out").innerHTML = ""; $("a-out").innerHTML = "";
  if (window.SmartMap && SmartMap.available()) {
    if (!viewer) viewer = new SmartMap.Viewer($("p-map"), {});
    setTimeout(() => viewer.show(parcel.geometry), 0);
  }
  $("p-quality").innerHTML = `<div class="skeleton"></div>`;
  try { $("p-quality").innerHTML = qualityList((await api(`/parcels/${parcel.id}/profile`)).quality); }
  catch (e) { $("p-quality").innerHTML = `<p class="hint">${esc(e.message)} Press “Refresh data” to fetch weather and Sentinel-2 for this parcel.</p>`; }
}
$("p-refresh").onclick = async () => {
  const btn = $("p-refresh");
  btn.setAttribute("aria-busy", "true");
  try { $("p-quality").innerHTML = qualityList((await api(`/parcels/${parcel.id}/profile/refresh`, {method: "POST"})).quality); }
  catch (e) { $("p-quality").innerHTML = `<p class="error">${esc(e.message)}</p>`; }
  finally { btn.removeAttribute("aria-busy"); }
};

// ------------------------------------------------------------------ answer card
const short = (h) => (h ? String(h).slice(0, 12) + "…" : "–");
function whyPanel(run) {
  const d = run.decisions || {}, p = run.provenance || {};
  const pol = d.policy || {}, suf = d.sufficiency, q = d.question, gr = d.grounding || {};
  const appl = (d.applicability || []).reduce((acc, a) => { acc[a.status] = (acc[a.status] || 0) + 1; return acc; }, {});
  const qual = Object.values(d.quality || {}).reduce((acc, x) => { acc[x.reliability] = (acc[x.reliability] || 0) + 1; return acc; }, {});
  const missing = suf && suf.missing ? suf.missing.map((m) => (typeof m === "string" ? inputName(m) : "one of " + (m.one_of || []).map((x) => inputName(x)).join(" / "))) : [];
  const layer = (sym, name, body) => `<div class="layer"><b>${sym} · ${name}</b>${body}</div>`;
  const counts = (obj, names) => Object.keys(obj).length ? Object.entries(obj).map(([k, n]) => `${n} ${esc(names[k] || k)}`).join(", ") : "none";
  return `<details class="why"><summary>Why?</summary>
    <p class="hint">The deterministic layers decided this before any text was written.</p>
    <div class="layers">
      ${layer("δ", "Decision", `${esc(ACTS[pol.act] || pol.act || "–")}<br><span class="hint">${esc(pol.reason_code || "")}${pol.allow_quantity ? " · quantity allowed" : " · no quantity"}</span>`)}
      ${layer("σ", "Sufficiency", suf ? `${esc(suf.status)}${missing.length ? `<br><span class="hint">missing: ${esc(missing.join("; "))}</span>` : ""}` : "not evaluated")}
      ${layer("α", "Next question", q && q.input ? esc(inputName(q.input)) : "none")}
      ${layer("q", "Input quality", esc(counts(qual, RELIABILITY)))}
      ${layer("π", "Applicability", `${esc(counts(appl, APPLICABILITY))}<br><span class="hint">${(d.passage_budget || []).length} passages used</span>`)}
      ${layer("γ", "Grounding", `${esc(gr.action || "–")}<br><span class="hint">${(gr.unsupported_numbers || []).length} unsupported numbers</span>`)}
    </div>
    <div class="layers">
      ${layer("", "As of", esc(p.as_of ? fmtDate(p.as_of) + " " + String(p.as_of).slice(11, 16) : "–"))}
      ${layer("", "Corpus hash", `<code>${esc(short(p.corpus_hash))}</code>`)}
      ${layer("", "Model / prompt", `${esc(p.model || "–")} · <code>${esc(short(p.prompt_hash))}</code>`)}
      ${layer("", "Weather forecast issued", esc(p.forecast_issued_at || "–"))}
    </div>
    <details class="raw"><summary>Decisions and provenance (JSON)</summary><pre>${esc(JSON.stringify({decisions: run.decisions, provenance: run.provenance}, null, 2))}</pre></details>
  </details>`;
}

function section(title, inner, extra = "") {
  return inner ? `<section class="sheet-group"${extra}><h3>${title}</h3>${inner}</section>` : "";
}
const ACT_ICON = {recommend: "M5 12.5l4.2 4.2L19 7", conditional: "M12 7v6M12 16.5v.5", ask: "M9.2 9a2.9 2.9 0 1 1 3.9 2.7c-.7.3-1.1.9-1.1 1.6v.4M12 17v.3",
                  abstain: "M7 12h10", refer: "M7 12h10M13 7l5 5-5 5"};
function answerCard(run) {
  const a = run.answer, act = a.action || {}, L = LANG();
  const data = (a.data_used || []).map((d) => `<li><span>${esc(inputName(d.input, d.label))}</span><span class="v"><span ${L}>${esc(valueText(d.value_text))}</span> <span class="pill rel-${esc(d.reliability)}">${esc(RELIABILITY[d.reliability] || d.reliability_label)}</span>${d.age_days != null ? `<span class="age">${esc(d.age_days)} d</span>` : ""}</span></li>`).join("");
  const src = (a.sources || []).map((s) => `<li><span class="src-title" ${CORPUS}>${s.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)}</a>` : esc(s.title)}</span> <span class="src-status">π: ${esc(APPLICABILITY[s.applicability] || s.applicability_label)}${s.conditions && s.conditions.length ? `; <span ${L}>${esc(s.conditions.join("; "))}</span>` : ""}</span></li>`).join("");
  const why = (a.rationale || []).map((r) => `<li>${esc(r)}</li>`).join("");
  const calc = (a.calculations || []).map((c) => `<li>${esc(typeof c === "string" ? c : c.text || c.label || JSON.stringify(c))}</li>`).join("");
  const nq = a.next_question;
  const opts = nq ? nq.options.map((o) => `<button type="button" class="chip accent" data-input="${esc(nq.input)}" data-value="${esc(o.value)}">${esc(o.label)}</button>`).join("") : "";
  const kv = act.what || act.quantity ? `<dl class="kv">${act.what ? `<dt>Action</dt><dd ${L}>${esc(act.what)}</dd><dt>When / condition</dt><dd ${L}>${esc(act.when_or_condition)}</dd>` : ""}${act.quantity ? `<dt>Quantity</dt><dd ${L}>${esc(act.quantity)}</dd>` : ""}</dl>` : "";
  return `<article class="answer act-${esc(a.act)}">
    <span class="grabber" aria-hidden="true"></span>
    <header><span class="act-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="${ACT_ICON[a.act] || ACT_ICON.abstain}"/></svg></span>
      <span class="act-head"><span class="act-badge">${esc(ACTS[a.act] || a.act_label)}</span><span class="meta">${esc(run.variant)} · ${esc(ADVICE[run.advice_type] || "advice type not yet known")} · ${esc(a.generator)} generator</span></span></header>
    <p class="summary" ${L}>${esc(a.summary)}</p>
    ${kv}
    ${nq ? `<div class="nextq"><p ${L}>${esc(nq.text)}${nq.how_to_obtain ? `<span class="how">${esc(nq.how_to_obtain)}</span>` : ""}</p><div class="options" ${L}>${opts}</div></div>` : ""}
    ${section("Reasoning", why ? `<ul ${L}>${why}</ul>` : "")}
    ${section("Calculations <span class=\"hint-inline\">in code, FAO-56</span>", calc ? `<ul ${L}>${calc}</ul>` : "")}
    ${section("Based on", a.basis && a.basis.text ? `<p ${L}>${esc(a.basis.text)}</p>` : "")}
    ${section("Data used <span class=\"hint-inline\">reliability, age</span>", data ? `<ul class="rows">${data}</ul>` : "")}
    ${section("Sources and π status", src ? `<ul class="rows src">${src}</ul>` : "")}
    ${section("Referral", a.referral ? `<p ${L}>${esc(typeof a.referral === "string" ? a.referral : a.referral.text || JSON.stringify(a.referral))}</p>` : "")}
    ${(a.limitations || []).length ? `<div class="limits" ${L}>${a.limitations.map(esc).join("<br>")}</div>` : ""}
    ${whyPanel(run)}
  </article>`;
}

async function sendChat(body) {
  const btn = $("c-send");
  btn.setAttribute("aria-busy", "true");
  try {
    const run = await api(`/parcels/${parcel.id}/chat`, {method: "POST", body: JSON.stringify(
      {...body, variant: $("c-variant").value, conversation_id: conv})});
    conv = run.conversation_id; pending = run.answer.next_question;
    $("c-out").insertAdjacentHTML("beforeend", `<div class="bubble">${esc(run.question)}</div>` + answerCard(run));
    $("c-out").querySelectorAll("button[data-input]").forEach((b) => b.onclick = () => sendChat({reply: {input: b.dataset.input, value: b.dataset.value}}));
    const cards = $("c-out").querySelectorAll(".answer");
    const last = cards[cards.length - 1];
    if (last && last.scrollIntoView) last.scrollIntoView({block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"});
  } catch (e) { $("c-out").insertAdjacentHTML("beforeend", `<p class="error">${esc(e.message)}</p>`); }
  finally { btn.removeAttribute("aria-busy"); }
}
$("c-form").onsubmit = (e) => {
  e.preventDefault();
  if (!$("c-text").value.trim()) { $("c-text").focus(); return; }
  conv = pending ? conv : null;
  sendChat({text: $("c-text").value, advice_type: $("c-type").value || null});
  $("c-text").value = "";
};
document.querySelectorAll(".suggestions .chip").forEach((b) => b.onclick = () => { $("c-text").value = b.dataset.q; $("c-text").focus(); });

$("a-form").onsubmit = async (e) => {
  e.preventDefault();
  if (!$("a-text").value.trim()) { $("a-text").focus(); return; }
  const btn = $("a-send");
  btn.setAttribute("aria-busy", "true");
  try {
    const run = await api(`/parcels/${parcel.id}/ai-chat`, {method: "POST", body: JSON.stringify(
      {message: $("a-text").value, mode: $("a-mode").value, conversation_id: aiConv})});
    aiConv = run.conversation_id;
    $("a-text").value = "";
    const shownLang = run.answer.language ? (run.answer.translation && run.answer.translation.shown === "local" ? "sr-Latn" : run.answer.language.detected) : "sr-Latn";
    $("a-out").insertAdjacentHTML("beforeend", `<div class="bubble">${esc(run.question)}</div><article class="answer act-ai"><p class="ai-text" lang="${esc(shownLang)}">${esc(run.answer.text)}</p>
      <details class="raw"><summary>Provenance</summary><pre>${esc(JSON.stringify(run.provenance, null, 2))}</pre></details></article>`);
  } catch (err) { $("a-out").insertAdjacentHTML("beforeend", `<p class="error">${esc(err.message)}</p>`); }
  finally { btn.removeAttribute("aria-busy"); }
};

// ------------------------------------------------------------------ blind rating (unchanged protocol screen)
$("r-next").onclick = async () => {
  const rater = $("r-rater").value.trim();
  if (!rater) return;
  const [item, rubric] = await Promise.all([api("/eval/rating/next?rater=" + encodeURIComponent(rater)), api("/eval/rubric")]);
  if (!item.item_id) { $("r-item").innerHTML = "<p>Nema više stavki za ocenjivanje.</p>"; return; }
  $("r-item").innerHTML = `<p class="muted">Preostalo: ${esc(item.remaining)}</p><pre>${esc(JSON.stringify(item, null, 2))}</pre>
    <p class="muted">Rubrika:</p><pre>${esc(JSON.stringify(rubric, null, 2))}</pre>
    <textarea id="r-json" rows="6" cols="70">{"item_id": "${esc(item.item_id)}", "rater": "${esc(rater)}", "r1": 0, "r2": 0, "r3": 0, "r4": 0, "r5": 0, "critical": [], "comment": ""}</textarea><br>
    <button class="primary" id="r-save">Sačuvaj ocenu</button> <span id="r-msg"></span>`;
  $("r-save").onclick = async () => {
    try { await api("/eval/rating", {method: "POST", body: $("r-json").value}); $("r-next").click(); }
    catch (e) { $("r-msg").textContent = e.message; }
  };
};

// ------------------------------------------------------------------ account (only when the server has accounts on)
let account = {enabled: false, user: null, email: false};
let accMode = "signin";
const ACC_PANES = ["acc-auth", "acc-forgot-form", "acc-reset-form", "acc-menu", "acc-notice"];
const initial = (email) => (email || "?").trim().charAt(0).toUpperCase();

async function initAccount() {
  account.enabled = true;
  account.email = !!meta.accounts.email;
  try { const me = await api("/auth/me"); account.user = me.user; account.email = !!me.email; }
  catch (e) { account.user = null; }
  renderAccount();
}
function renderAccount() {
  const u = account.user;
  $("account").hidden = !account.enabled;
  $("account-icon").hidden = !account.enabled;
  $("account-name").textContent = u ? u.email : "Sign in";
  $("account-sub").textContent = u ? "Signed in" : "Parcels are not saved";
  $("account-avatar").textContent = u ? initial(u.email) : "";
  $("account-avatar").classList.toggle("anon", !u);
  $("account-open").setAttribute("aria-label", u ? `Account: ${u.email}` : "Account: sign in or create an account");
  $("account-icon").setAttribute("aria-label", u ? `Account: ${u.email}` : "Account: sign in");
  $("account-icon").classList.toggle("signed-in", !!u);
  showBanner();
}
// Anonymous work is temporary: kept for this browser session (and removed by the server after a period without
// activity) until the user creates an account or signs in, which saves it.
function unsaved() { return account.enabled && !account.user; }
function showBanner() {
  const n = parcelsCache.length;
  $("anon-banner").hidden = !(unsaved() && n);
  $("anon-banner-text").textContent = n === 1
    ? "Temporary — this parcel is kept only for this browser session. Create an account to save it."
    : "Temporary — these parcels are kept only for this browser session. Create an account to save them.";
  $("banner-signup").textContent = n === 1 ? "Save parcel" : "Save parcels";
  if (parcel) $("p-temp").hidden = !unsaved();
}
function accPane(id) {
  for (const p of ACC_PANES) $(p).hidden = p !== id;
  const titles = {"acc-auth": "Account", "acc-forgot-form": "Reset password", "acc-reset-form": "New password",
                  "acc-menu": "Account", "acc-notice": "Account"};
  $("acc-title").textContent = titles[id];
}
function accSet(mode) {
  accMode = mode;
  const up = mode === "signup";
  $("acc-tab-in").setAttribute("aria-selected", String(!up)); $("acc-tab-in").tabIndex = up ? -1 : 0;
  $("acc-tab-up").setAttribute("aria-selected", String(up)); $("acc-tab-up").tabIndex = up ? 0 : -1;
  $("acc-form").setAttribute("aria-labelledby", up ? "acc-tab-up" : "acc-tab-in");
  $("acc-submit").textContent = up ? "Create account" : "Sign in";
  $("acc-password").autocomplete = up ? "new-password" : "current-password";
  $("acc-pw-hint").hidden = !up;
  $("acc-claim").textContent = "Your parcels from this browser session are saved to your account.";
  $("acc-claim").hidden = !(parcelsCache.length);
  $("acc-forgot").hidden = up || !account.email;
  $("acc-msg").textContent = "";
}
function openAccount(mode) {
  if (account.user) {
    accPane("acc-menu");
    $("acc-email-shown").textContent = account.user.email;
    $("acc-avatar").textContent = initial(account.user.email);
    $("acc-delete-form").hidden = true; $("acc-delete").setAttribute("aria-expanded", "false");
    $("acc-delete-password").value = ""; $("acc-delete-msg").textContent = "";
  } else {
    accPane("acc-auth");
    accSet(mode || "signin");
  }
  if (!$("account-sheet").open) $("account-sheet").showModal();
}
function notice(text) {
  accPane("acc-notice");
  $("acc-notice-text").textContent = text;
  if (!$("account-sheet").open) $("account-sheet").showModal();
}
async function afterAuth(user) {
  account.user = user;
  if (user === null) parcelsCache = [];
  renderAccount();
  if (!$("v-parcels").hidden) { parcelsCache = []; await loadParcels(); }
  else if (!$("v-parcel").hidden && user === null) location.hash = "#/parcels";
}
$("account-open").onclick = () => openAccount();
$("account-icon").onclick = () => openAccount();
$("banner-signup").onclick = () => openAccount("signup");
$("p-save").onclick = () => openAccount("signup");
// Leaving the page with parcels that are not saved: the browser's own confirmation (no custom text is possible).
window.addEventListener("beforeunload", (e) => {
  if (unsaved() && parcelsCache.length) { e.preventDefault(); e.returnValue = ""; }
});
$("acc-close").onclick = () => $("account-sheet").close();
$("acc-notice-ok").onclick = () => $("account-sheet").close();
$("acc-tab-in").onclick = () => accSet("signin");
$("acc-tab-up").onclick = () => accSet("signup");
[$("acc-tab-in"), $("acc-tab-up")].forEach((t) => t.onkeydown = (e) => {
  if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
  e.preventDefault();
  const next = accMode === "signin" ? "signup" : "signin";
  accSet(next); $(next === "signup" ? "acc-tab-up" : "acc-tab-in").focus();
});
$("acc-forgot").onclick = () => {
  accPane("acc-forgot-form");
  $("acc-forgot-email").value = $("acc-email").value; $("acc-forgot-msg").textContent = "";
  $("acc-forgot-email").focus();
};
$("acc-back").onclick = () => { accPane("acc-auth"); accSet("signin"); };
$("acc-form").onsubmit = async (e) => {
  e.preventDefault();
  const btn = $("acc-submit"), email = $("acc-email").value.trim(), password = $("acc-password").value;
  $("acc-msg").textContent = "";
  if (!email || !password) { $("acc-msg").textContent = "Enter your email and password."; return; }
  if (accMode === "signup" && password.length < 10) { $("acc-msg").textContent = "Use a password of at least 10 characters."; return; }
  btn.setAttribute("aria-busy", "true");
  try {
    const r = await api(accMode === "signup" ? "/auth/signup" : "/auth/signin", {method: "POST", body: JSON.stringify({email, password})});
    $("acc-password").value = "";
    if (r.verify_sent) { notice(`We have sent a confirmation link to ${email}. Open it, then sign in. Until then your parcels are kept only for this browser session.`); return; }
    $("account-sheet").close();
    await afterAuth(r.user);
  } catch (err) { $("acc-msg").textContent = err.message; }
  finally { btn.removeAttribute("aria-busy"); }
};
$("acc-forgot-form").onsubmit = async (e) => {
  e.preventDefault();
  const email = $("acc-forgot-email").value.trim();
  if (!email) { $("acc-forgot-msg").textContent = "Enter your email."; return; }
  $("acc-forgot-send").setAttribute("aria-busy", "true");
  try {
    await api("/auth/password/forgot", {method: "POST", body: JSON.stringify({email})});
    notice(`If an account exists for ${email}, a link to choose a new password is on its way. It is valid for one hour.`);
  } catch (err) { $("acc-forgot-msg").textContent = err.message; }
  finally { $("acc-forgot-send").removeAttribute("aria-busy"); }
};
let resetToken = "";
$("acc-reset-form").onsubmit = async (e) => {
  e.preventDefault();
  const password = $("acc-reset-password").value;
  if (password.length < 10) { $("acc-reset-msg").textContent = "Use a password of at least 10 characters."; return; }
  $("acc-reset-save").setAttribute("aria-busy", "true");
  try {
    const r = await api("/auth/password/reset", {method: "POST", body: JSON.stringify({token: resetToken, password})});
    $("acc-reset-password").value = "";
    await afterAuth(r.user);
    notice("Your password has been changed and you are signed in.");
  } catch (err) { $("acc-reset-msg").textContent = err.message; }
  finally { $("acc-reset-save").removeAttribute("aria-busy"); }
};
$("acc-signout").onclick = async () => {
  try { await api("/auth/signout", {method: "POST"}); $("account-sheet").close(); await afterAuth(null); }
  catch (err) { notice(err.message); }
};
$("acc-delete").onclick = () => {
  const open = $("acc-delete-form").hidden;
  $("acc-delete-form").hidden = !open;
  $("acc-delete").setAttribute("aria-expanded", String(open));
  if (open) $("acc-delete-password").focus();
};
$("acc-delete-form").onsubmit = async (e) => {
  e.preventDefault();
  const password = $("acc-delete-password").value;
  if (!password) { $("acc-delete-msg").textContent = "Enter your password to confirm."; return; }
  $("acc-delete-confirm").setAttribute("aria-busy", "true");
  try {
    await api("/auth/account/delete", {method: "POST", body: JSON.stringify({password})});
    await afterAuth(null);
    notice("Your account and its data have been deleted.");
  } catch (err) { $("acc-delete-msg").textContent = err.message; }
  finally { $("acc-delete-confirm").removeAttribute("aria-busy"); }
};
// Links from e-mails: #/verify/<token> and #/reset/<token>. The token stays in the fragment (never sent to a server log).
async function accountLink(kind, token) {
  history.replaceState(null, "", location.pathname + location.search + "#/parcels");
  show("parcels"); loadParcels();
  if (!account.enabled) return;
  if (kind === "reset") {
    resetToken = token;
    accPane("acc-reset-form"); $("acc-reset-msg").textContent = ""; $("acc-reset-password").value = "";
    $("account-sheet").showModal(); $("acc-reset-password").focus();
    return;
  }
  try { await api("/auth/verify", {method: "POST", body: JSON.stringify({token})}); openAccount("signin");
        $("acc-msg").textContent = ""; $("acc-claim").hidden = false;
        $("acc-claim").textContent = "Your email is confirmed. Sign in to continue."; }
  catch (err) { notice(err.message); }
}

// ------------------------------------------------------------------ settings
function storedTheme() { try { return localStorage.getItem("smartagri.theme") || "auto"; } catch (e) { return "auto"; } }
function applyTheme(theme) {
  try { localStorage.setItem("smartagri.theme", theme); } catch (e) { /* not stored */ }
  if (theme === "light" || theme === "dark") document.documentElement.setAttribute("data-theme", theme);
  else document.documentElement.removeAttribute("data-theme");
}
$("settings-open").onclick = () => {
  const theme = storedTheme();
  document.querySelectorAll('input[name="theme"]').forEach((r) => { r.checked = r.value === theme; });
  let url = "", attr = "";
  try { url = localStorage.getItem("smartagri.tileUrl") || ""; attr = localStorage.getItem("smartagri.tileAttribution") || ""; } catch (e) { /* none */ }
  $("s-tiles").value = url; $("s-attr").value = attr;
  const lang = storedLang() || (meta && meta.locale) || "en";
  document.querySelectorAll('input[name="lang"]').forEach((r) => { r.checked = r.value === lang; });
  $("s-tiles").placeholder = document.querySelector('meta[name="smartagri-tile-url"]').content || "none";
  $("settings").showModal();
};
document.querySelectorAll('input[name="theme"]').forEach((r) => r.onchange = () => applyTheme(r.value));
document.querySelectorAll('input[name="lang"]').forEach((r) => r.onchange = () => {
  try { localStorage.setItem("smartagri.lang", r.value); } catch (e) { /* not stored */ }
  langChanged = true;
});
let langChanged = false;
$("s-reset").onclick = () => { $("s-tiles").value = ""; $("s-attr").value = ""; applyTheme("auto");
  try { localStorage.removeItem("smartagri.lang"); } catch (e) { /* none */ }
  langChanged = true;
  document.querySelectorAll('input[name="lang"]').forEach((r) => { r.checked = r.value === ((meta && meta.locale) || "en"); });
  document.querySelectorAll('input[name="theme"]').forEach((r) => { r.checked = r.value === "auto"; }); };
$("settings-form").onsubmit = () => {
  const before = JSON.stringify(SmartMap.tileSettings());
  SmartMap.saveTileSettings($("s-tiles").value.trim(), $("s-attr").value.trim());
  if (JSON.stringify(SmartMap.tileSettings()) !== before || langChanged) location.reload();   // maps and texts are rebuilt
};

init().catch((e) => { $("health").classList.add("down"); $("health").textContent = "The research API is not reachable: " + e.message; });
