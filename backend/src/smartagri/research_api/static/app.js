// SmartAgri research client. Plain JavaScript, no build step. Talks to the research API under /api.
"use strict";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
async function api(path, opts = {}) {
  const r = await fetch("api" + path, {headers: {"Content-Type": "application/json"}, ...opts});
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof body.detail === "string" ? body.detail : r.statusText || "Request failed");
  return body;
}

// ------------------------------------------------------------------ English names of codes returned by the API.
// Texts produced by the decision model (summaries, sources, follow-up questions) stay in the corpus language.
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
const SR = 'lang="sr-Latn"';

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

async function loadParcels() {
  const list = $("parcel-list");
  if (!parcelsCache.length) list.innerHTML = `<div class="skeleton"></div><div class="skeleton"></div>`;
  let rows;
  try { rows = await api("/parcels"); }
  catch (e) { list.innerHTML = `<p class="error">${esc(e.message)}</p>`; return; }
  parcelsCache = rows;
  if (!rows.length) {
    list.innerHTML = `<div class="empty card"><h2>No parcels yet</h2><p>Draw a maize field on the map, or paste its boundary as GeoJSON. Then fetch its data and ask a question.</p><a class="button primary" href="#/new">Draw your first parcel</a></div>`;
    return;
  }
  list.innerHTML = rows.map((p) => {
    const sow = (p.agronomic || {}).sowing_date;
    return `<a class="parcel-card" href="#/parcel/${encodeURIComponent(p.id)}">${thumb(p.geometry)}
      <span><span class="name">${esc(p.name)}</span><br><span class="facts">${esc(fmtHa(p.area_ha))}${sow ? " · sown " + esc(fmtDate(sow)) : ""}</span></span>
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
    parcelsCache = [];
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

function answerCard(run) {
  const a = run.answer, act = a.action || {};
  const data = (a.data_used || []).map((d) => `<li>${esc(inputName(d.input, d.label))}: <span ${SR}>${esc(valueText(d.value_text))}</span> · ${esc(RELIABILITY[d.reliability] || d.reliability_label)}${d.age_days != null ? " · " + esc(d.age_days) + " d" : ""}</li>`).join("");
  const src = (a.sources || []).map((s) => `<li><span ${SR}>${s.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)}</a>` : esc(s.title)}</span> <span class="src-status">π: ${esc(APPLICABILITY[s.applicability] || s.applicability_label)}${s.conditions && s.conditions.length ? `; <span ${SR}>${esc(s.conditions.join("; "))}</span>` : ""}</span></li>`).join("");
  const why = (a.rationale || []).map((r) => `<li>${esc(r)}</li>`).join("");
  const calc = (a.calculations || []).map((c) => `<li>${esc(typeof c === "string" ? c : c.text || c.label || JSON.stringify(c))}</li>`).join("");
  const nq = a.next_question;
  const opts = nq ? nq.options.map((o) => `<button type="button" class="chip accent" data-input="${esc(nq.input)}" data-value="${esc(o.value)}">${esc(o.label)}</button>`).join("") : "";
  return `<article class="answer act-${esc(a.act)}">
    <header><span class="act-badge">${esc(ACTS[a.act] || a.act_label)}</span><span class="meta">${esc(run.variant)} · ${esc(ADVICE[run.advice_type] || "advice type not yet known")} · generator ${esc(a.generator)}</span></header>
    <p class="summary" ${SR}>${esc(a.summary)}</p>
    ${act.what || act.quantity ? `<dl class="kv">${act.what ? `<dt>Action</dt><dd ${SR}>${esc(act.what)}</dd><dt>When / condition</dt><dd ${SR}>${esc(act.when_or_condition)}</dd>` : ""}${act.quantity ? `<dt>Quantity</dt><dd ${SR}>${esc(act.quantity)}</dd>` : ""}</dl>` : ""}
    ${why ? `<h3>Reasoning</h3><ul ${SR}>${why}</ul>` : ""}
    ${calc ? `<h3>Calculations (code, FAO-56)</h3><ul ${SR}>${calc}</ul>` : ""}
    ${a.basis && a.basis.text ? `<h3>Based on</h3><p ${SR}>${esc(a.basis.text)}</p>` : ""}
    ${data ? `<h3>Data used (reliability, age)</h3><ul>${data}</ul>` : ""}
    ${src ? `<h3>Sources and π status</h3><ul>${src}</ul>` : ""}
    ${a.referral ? `<h3>Referral</h3><p ${SR}>${esc(typeof a.referral === "string" ? a.referral : a.referral.text || JSON.stringify(a.referral))}</p>` : ""}
    ${(a.limitations || []).length ? `<div class="limits" ${SR}>${a.limitations.map(esc).join("<br>")}</div>` : ""}
    ${nq ? `<div class="nextq"><p ${SR}>${esc(nq.text)}${nq.how_to_obtain ? `<br><span class="how">${esc(nq.how_to_obtain)}</span>` : ""}</p><div class="options" ${SR}>${opts}</div></div>` : ""}
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
    $("c-out").insertAdjacentHTML("beforeend", `<div class="bubble" ${SR}>${esc(run.question)}</div>` + answerCard(run));
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
    $("a-out").insertAdjacentHTML("beforeend", `<div class="bubble">${esc(run.question)}</div><article class="answer"><p class="ai-text">${esc(run.answer.text)}</p>
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
  $("s-tiles").placeholder = document.querySelector('meta[name="smartagri-tile-url"]').content || "none";
  $("settings").showModal();
};
document.querySelectorAll('input[name="theme"]').forEach((r) => r.onchange = () => applyTheme(r.value));
$("s-reset").onclick = () => { $("s-tiles").value = ""; $("s-attr").value = ""; applyTheme("auto");
  document.querySelectorAll('input[name="theme"]').forEach((r) => { r.checked = r.value === "auto"; }); };
$("settings-form").onsubmit = () => {
  const before = JSON.stringify(SmartMap.tileSettings());
  SmartMap.saveTileSettings($("s-tiles").value.trim(), $("s-attr").value.trim());
  if (JSON.stringify(SmartMap.tileSettings()) !== before) location.reload();   // maps are rebuilt with the new tiles
};

init().catch((e) => { $("health").textContent = "The research API is not reachable: " + e.message; });
