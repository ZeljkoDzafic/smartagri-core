// SmartAgri research client. Plain JavaScript, no build step. Talks to the research API under /api.
"use strict";

const $ = (id) => document.getElementById(id);
// Interface language (static/i18n.js): follows the answer language; English unless the server or the browser chose
// the local language. The blind rating screen is never translated.
const t = (key, vars) => (window.SmartI18n ? SmartI18n.t(key, vars) : key);
const intl = () => (window.SmartI18n ? SmartI18n.intl() : "en-GB");
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
  if (!r.ok) {
    const err = new Error(typeof body.detail === "string" ? body.detail : r.statusText || t("Request failed"));
    err.status = r.status; err.body = body;            // the settings form reads the per-parameter errors of a 400
    throw err;
  }
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
  crop_identity: "Declared crop (checked)", field_state: "Field state (bare soil, harvest)",
};
const RELIABILITY = {high: "high", medium: "medium", low: "low", missing: "missing", ungraded: "not graded"};
const ORIGIN = {measured: "measured", user_reported: "reported by the user", modeled: "model value", derived: "estimate", unknown: "unknown origin"};
const APPLICABILITY = {applicable: "applicable", conditional: "conditionally applicable", not_applicable: "not applicable"};
const VALUES = {"nema podatka": "no data", "da": "yes", "ne": "no", "nepoznato": "unknown"};
const tr = (map, key, fallback) => (map[key] ? t(map[key]) : (fallback || key));
const inputName = (key, fallback) => tr(INPUTS, key, fallback);
// Values come formatted in the answer language; local-language words are mapped only for the English interface.
const valueText = (v) => (answerLang === "en" ? VALUES[String(v ?? "").trim()] || v : v);
// Soil texture classes of the core AWC table, labelled in the answer language (GET /meta).
const textureName = (v) => ((meta && meta.soil_textures) || []).reduce((acc, x) => (x.value === v ? x.label : acc), v);
const LANG = () => `lang="${esc(answerLang)}"`;
const CORPUS = 'lang="sr-Latn"';            // passages and their titles are quoted in the corpus language

let meta = null, parcel = null, conv = null, aiConv = null, pending = null, parcelsCache = [];
let drawer = null, viewer = null;

// ------------------------------------------------------------------ routing
const VIEWS = ["parcels", "new", "parcel", "eval", "settings", "rate"];
function show(view) {
  for (const v of VIEWS) $("v-" + v).hidden = v !== view;
  for (const a of document.querySelectorAll("[data-nav]")) {
    if (a.dataset.nav === view || (view === "parcel" && a.dataset.nav === "parcels")) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
  // The evaluation overview is never offered on the blind rating screen (raters must not see results while rating).
  const evalLink = document.querySelector('[data-nav="eval"]');
  if (evalLink) evalLink.hidden = view === "rate";
}
async function route() {
  const parts = (location.hash || "#/parcels").replace(/^#\/?/, "").split("/");
  const view = parts[0] || "parcels";
  if ((view === "verify" || view === "reset") && parts[1]) { accountLink(view, decodeURIComponent(parts[1])); return; }
  if (view === "parcel" && parts[1]) { show("parcel"); await openParcel(decodeURIComponent(parts[1])); }
  else if (view === "new") { show("new"); ensureDrawer(); }
  else if (view === "eval") { show("eval"); await loadEval(); }
  else if (view === "settings") { show("settings"); if (window.SmartSettings) SmartSettings.open(); }
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
  meta = await api("/meta");
  if (window.SmartI18n) { SmartI18n.setLang(storedLang() || meta.locale); SmartI18n.apply(document.body); }
  const h = await api("/health");
  const chips = [[t("Version"), h.version], [t("Generator"), h.llm], [t("Satellite"), t(h.satellite)], [t("Offline"), h.offline ? t("yes") : t("no")],
                 [t("Database"), h.database], [t("Retrieval"), h.retrieval]];
  $("health").innerHTML = chips.map(([k, v]) => `<span class="chip-static">${esc(k)} <b>${esc(v)}</b></span>`).join("");
  $("c-variant").innerHTML = meta.variants.map((v) => `<option ${v === meta.default_variant ? "selected" : ""}>${esc(v)}</option>`).join("");
  $("c-type").innerHTML += meta.advice_types.map((x) => `<option value="${esc(x.value)}">${esc(tr(ADVICE, x.value, x.label))}</option>`).join("");
  $("n-texture").innerHTML = `<option value="">${esc(t("Unknown"))}</option>` + (meta.soil_textures || []).map((x) =>
    `<option value="${esc(x.value)}">${esc(x.label)} (${esc(t("AWC {v} mm/m", {v: x.awc_mm_m}))})</option>`).join("");
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
const fmtHa = (x) => (x == null ? "–" : Number(x).toLocaleString(intl(), {maximumFractionDigits: 2}) + " ha");
function fmtDate(s) {
  if (!s) return "";
  const d = new Date(String(s).length === 10 ? s + "T00:00:00" : s);
  return isNaN(d) ? String(s) : d.toLocaleDateString(intl(), {day: "numeric", month: "short", year: "numeric"});
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
    list.innerHTML = `<div class="empty card">${EMPTY_ART}<h2>${esc(t("No parcels yet"))}</h2><p>${esc(t("Draw a maize field on the map or paste its boundary as GeoJSON. Then fetch its data and ask a question."))}</p><a class="button primary" href="#/new">${esc(t("Draw your first parcel"))}</a></div>`;
    return;
  }
  list.innerHTML = rows.map((p) => {
    const sow = (p.agronomic || {}).sowing_date;
    return `<a class="parcel-card" href="#/parcel/${encodeURIComponent(p.id)}">${thumb(p.geometry)}
      <span><span class="name">${esc(p.name)}</span>${unsaved() ? ` <span class="pill unsaved">${esc(t("Not saved"))}</span>` : ""}<br><span class="facts">${esc(fmtHa(p.area_ha))}${sow ? " · " + esc(t("sown {date}", {date: fmtDate(sow)})) : ""}</span></span>
      <span class="chev" aria-hidden="true">›</span></a>`;
  }).join("");
}

// ------------------------------------------------------------------ new parcel
const EXAMPLE = {type: "Polygon", coordinates: [[[19.700, 45.320], [19.710, 45.320], [19.710, 45.326], [19.700, 45.326], [19.700, 45.320]]]};

function tileProblem(kind) {
  const note = $("map-note");
  note.textContent = kind === "off" ? t("Map tiles are turned off in Settings. You can still draw on the empty grid or paste GeoJSON.")
                                    : t("Map tiles could not be loaded. You can still draw on the empty grid or paste GeoJSON.");
  note.hidden = false;
}
function ensureDrawer() {
  if (!window.SmartMap || !SmartMap.available()) {
    $("d-status").textContent = t("The map library could not be loaded. Use the GeoJSON tab.");
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
  $("d-draw").textContent = st.closed ? t("Redraw") : st.drawing ? t("Drawing…") : t("Draw");
  $("d-undo").disabled = !st.count;
  $("d-finish").disabled = !(st.drawing && st.count >= 3);
  $("d-clear").disabled = !st.count;
  $("d-status").textContent = st.closed ? t("Boundary closed: {n} corners. Drag a corner to adjust it.", {n: st.count})
    : st.drawing ? (st.count < 3 ? t("Click the corners of the field ({n} of at least 3). Keyboard: pan with the arrow keys, then “Add centre point”.", {n: st.count})
                                 : t("{n} corners. Click the first corner, double click, or press Finish.", {n: st.count}))
    : t("No boundary yet. Press Draw to start.");
  $("n-area").textContent = st.area_ha != null ? `≈ ${fmtHa(st.area_ha)}` : t("No boundary yet");
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
  if (!text) throw new Error(t("Draw the boundary on the map or paste GeoJSON first."));
  let g;
  try { g = JSON.parse(text); } catch (e) { throw new Error(t("The boundary is not valid JSON.")); }
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
    if (drawer && !drawer.load(g)) $("g-msg").textContent = t("Only a Polygon (or a Feature with a Polygon) can be shown on the map.");
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
    if (!$("n-name").value.trim()) throw new Error(t("Enter a name for the parcel."));
    const body = {name: $("n-name").value, sowing_date: $("n-sowing").value || null, irrigation_available: $("n-irr").value,
                  geometry: parseGeom()};
    if ($("n-pinned").value) body.pinned_as_of = $("n-pinned").value;
    if ($("n-texture").value) body.soil_texture = $("n-texture").value;
    btn.setAttribute("aria-busy", "true");
    const p = await api("/parcels", {method: "POST", body: JSON.stringify(body)});
    parcelsCache = [p].concat(parcelsCache.filter((x) => x.id !== p.id));
    location.hash = "#/parcel/" + encodeURIComponent(p.id);
  } catch (err) { $("n-msg").textContent = err.message; }
  finally { btn.removeAttribute("aria-busy"); }
};

// ------------------------------------------------------------------ parcel
// Notices about the quality rules of the parcel features (docs/parcel-features.md): a conflict between two sources of
// one input (the reliability is capped, never raised) and the NDVI mask fields behind a lowered grade. Built from the
// structured `detail` of a quality row, so they follow the interface language.
function conflictNotice(c) {
  if (c.rule === "stage_conflict") {
    const s = c.satellite || {}, u = c.in_use || {};
    return t("Stage conflict: the growth stage in use (BBCH {bbch}, {origin}) lies outside the satellite estimate (BBCH {lo}–{hi}, tolerance ±{tol}). Stage reliability is capped at low until the stage is confirmed.",
      {bbch: u.bbch, origin: tr(ORIGIN, u.origin, u.origin), lo: s.bbch_min, hi: s.bbch_max, tol: c.tolerance_bbch});
  }
  if (c.rule === "field_markers") {
    return c.field_state === "harvested"
      ? t("Field marker conflict: a harvest is detected, but the advice assumes a standing crop. Stage reliability is capped at low.")
      : t("Field marker conflict: bare soil is detected now, but the stage in use is BBCH {bbch}. Stage reliability is capped at low.", {bbch: (c.in_use || {}).bbch});
  }
  if (c.rule === "crop_plausibility") {
    return t("Crop check: the producer's classifier disagrees with the declared crop (probability of maize {p}). Crop reliability is capped at low.", {p: num(c.p_maize, 2)});
  }
  return "";
}
function ndviChips(d) {
  const pct = (x) => num(x * 100, 0), out = [];
  if (d.cloud_flag) out.push(t("cloud or shadow on the parcel"));
  if (d.cloud_px_share != null || d.shadow_px_share != null) out.push(t("cloud and shadow {pct} %", {pct: pct((d.cloud_px_share || 0) + (d.shadow_px_share || 0))}));
  if (d.n_px_interior != null) out.push(t("{n} interior pixels", {n: d.n_px_interior}));
  if (d.mixed_px_share != null) out.push(t("{pct} % boundary (mixed) pixels", {pct: pct(d.mixed_px_share)}));
  if (d.interior_buffer_m != null) out.push(t("buffer {m} m", {m: num(d.interior_buffer_m, 0)}));
  if (d.outliers_excluded && d.outliers_excluded.length) out.push(t("outliers left out: {dates}", {dates: d.outliers_excluded.map(fmtDate).join(", ")}));
  return out;
}
function qualityList(rows) {
  if (!rows || !rows.length) return `<p class="hint">${esc(t("No data yet."))}</p>`;
  const conflicts = rows.flatMap((r) => ((r.detail || {}).conflicts || []));
  const alert = conflicts.length ? `<div class="q-notice" role="status">${conflicts.map((c) => `<p>${esc(conflictNotice(c))}</p>`).join("")}</div>` : "";
  const present = rows.filter((r) => r.reliability !== "missing"), missing = rows.filter((r) => r.reliability === "missing");
  const absent = missing.length ? `<details class="raw missing"><summary>${esc(t("Missing inputs ({n})", {n: missing.length}))}</summary>
    <p class="hint">${missing.map((r) => esc(inputName(r.input, r.label))).join(" · ")}</p></details>` : "";
  if (!present.length) return alert + `<p class="hint">${esc(t("No input is available yet."))}</p>` + absent;
  return alert + `<ul class="qlist">` + present.map((r) => {
    const age = r.age_days != null ? t("{n} d old", {n: Number(r.age_days).toLocaleString(intl(), {maximumFractionDigits: 1})}) : "";
    const chips = (r.input || "").startsWith("ndvi") && r.detail ? ndviChips(r.detail) : [];
    const lowered = r.detail && r.detail.capped_by && r.detail.capped_by.length ? t("Grade lowered by the quality thresholds (development defaults)") : "";
    const extra = chips.length || lowered ? `<span class="q-meta q-chips">${chips.map((c) => `<span>${esc(c)}</span>`).join("")}${lowered ? `<span class="q-lowered">${esc(lowered)}</span>` : ""}</span>` : "";
    return `<li><span class="q-label">${esc(inputName(r.input, r.label))}</span><span class="q-value">${esc(valueText(r.value_text))}</span>
      <span class="q-meta"><span class="pill rel-${esc(r.reliability)}">${esc(tr(RELIABILITY, r.reliability, r.reliability_label))}</span>
      <span>${esc(tr(ORIGIN, r.origin, r.origin_label))}</span>${age ? `<span>· ${esc(age)}</span>` : ""}</span>${extra}</li>`;
  }).join("") + `</ul>` + absent;
}

async function openParcel(id) {
  try { parcel = await api("/parcels/" + encodeURIComponent(id)); }
  catch (e) { $("p-title").textContent = t("Parcel not found"); $("p-meta").textContent = e.message; $("p-quality").innerHTML = ""; return; }
  conv = null; aiConv = null; pending = null;
  $("p-temp").hidden = !unsaved();
  const ag = parcel.agronomic || {};
  $("p-title").textContent = parcel.name;
  $("p-meta").textContent = [fmtHa(parcel.area_ha), ag.sowing_date ? t("sown {date}", {date: fmtDate(ag.sowing_date)}) : t("sowing date unknown"),
                             parcel.pinned_as_of ? t("decision date {date}", {date: fmtDate(parcel.pinned_as_of)}) : "",
                             ag.soil_texture ? t("soil: {texture}", {texture: textureName(ag.soil_texture)}) : ""].filter(Boolean).join(" · ");
  $("c-out").innerHTML = ""; $("a-out").innerHTML = "";
  $("p-set").textContent = ""; $("p-set-card").open = false; $("p-set-card").dataset.loaded = "";
  if (window.SmartMap && SmartMap.available()) {
    if (!viewer) viewer = new SmartMap.Viewer($("p-map"), {});
    setTimeout(() => viewer.show(parcel.geometry), 0);
  }
  $("p-quality").innerHTML = `<div class="skeleton"></div>`;
  try { $("p-quality").innerHTML = qualityList((await api(`/parcels/${parcel.id}/profile`)).quality); }
  catch (e) { $("p-quality").innerHTML = `<p class="hint">${esc(e.message)} ${esc(t("Press “Refresh data” to fetch weather and Sentinel-2 for this parcel."))}</p>`; }
  await loadContext();
}
$("p-set-card").addEventListener("toggle", () => {
  const card = $("p-set-card");
  if (!card.open || card.dataset.loaded === parcel.id || !window.SmartSettings) return;
  card.dataset.loaded = parcel.id;
  SmartSettings.mountParcel($("p-set"), parcel).catch((e) => { $("p-set").innerHTML = `<p class="error">${esc(e.message)}</p>`; });
});
$("p-refresh").onclick = async () => {
  const btn = $("p-refresh");
  btn.setAttribute("aria-busy", "true");
  try { $("p-quality").innerHTML = qualityList((await api(`/parcels/${parcel.id}/profile/refresh`, {method: "POST"})).quality); }
  catch (e) { $("p-quality").innerHTML = `<p class="error">${esc(e.message)}</p>`; }
  finally { btn.removeAttribute("aria-busy"); }
  await loadContext();
};

// ------------------------------------------------------------------ answer card
const short = (h) => (h ? String(h).slice(0, 12) + "…" : "–");
// The settings an answer was computed with (provenance.settings): version, hash and the overrides with their level.
// "Custom settings applied": on every answer that was computed with a value that differs from the files, so nobody reads
// an answer from changed settings as the default one. It also says how many of the values are outside the recommended range.
function customSettingsNotice(s, inWhy) {
  if (!s || !s.n_overrides) return "";
  const out = new Set((s.outside_recommended || []).map((w) => w.key)).size;
  return `<p class="custom-settings" role="note"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2.2"/><circle cx="9" cy="17" r="2.2"/></svg>
    <span><b>${esc(t("Custom settings applied"))}</b> ${esc(t("This answer was computed with {n} settings that differ from the file defaults.", {n: s.n_overrides}))}${out ? " " + esc(t("{n} of them are outside the recommended range.", {n: out})) : ""}${inWhy ? "" : " " + esc(t("The list is under “Why?”."))}</span></p>`;
}
function settingsUsed(s) {
  if (!s) return "";
  const flagged = new Set((s.outside_recommended || []).map((w) => w.key));
  const rows = Object.entries(s.snapshot || {}).map(([k, v]) => `<li><code>${esc(k)}</code> = <code>${esc(JSON.stringify(v.value))}</code> <span class="hint">(${esc(t(v.layer === "global" ? "global" : v.layer === "user" ? "user" : "parcel"))})</span>${flagged.has(k) ? ` <span class="warn-inline">${esc(t("outside the recommended range"))}</span>` : ""}</li>`).join("");
  return `<div class="layers"><div class="layer"><b>${esc(t("Settings used"))}</b>${s.n_overrides ? esc(t("{n} values differ from the files", {n: s.n_overrides})) : esc(t("the configuration files only"))}
    <br><span class="hint">${esc(t("version"))} <code>${esc(s.version || "–")}</code> · <code>${esc(short(s.hash))}</code></span>${rows ? `<ul class="set-used">${rows}</ul>` : ""}</div></div>`;
}
function whyPanel(run) {
  const d = run.decisions || {}, p = run.provenance || {};
  const pol = d.policy || {}, suf = d.sufficiency, q = d.question, gr = d.grounding || {};
  const appl = (d.applicability || []).reduce((acc, a) => { acc[a.status] = (acc[a.status] || 0) + 1; return acc; }, {});
  const qual = Object.values(d.quality || {}).reduce((acc, x) => { acc[x.reliability] = (acc[x.reliability] || 0) + 1; return acc; }, {});
  const missing = suf && suf.missing ? suf.missing.map((m) => (typeof m === "string" ? inputName(m) : t("one of {list}", {list: (m.one_of || []).map((x) => inputName(x)).join(" / ")}))) : [];
  const layer = (sym, name, body) => `<div class="layer"><b>${sym} · ${esc(t(name))}</b>${body}</div>`;
  const counts = (obj, names) => Object.keys(obj).length ? Object.entries(obj).map(([k, n]) => `${n} ${esc(tr(names, k))}`).join(", ") : t("none");
  const code = (x) => (x ? `<code>${esc(x)}</code>` : "");
  return `<details class="why"><summary>${esc(t("Why?"))}</summary>
    ${customSettingsNotice(p.settings, true)}
    <p class="hint">${esc(t("The deterministic layers decided this before any text was written."))}</p>
    <div class="layers">
      ${layer("δ", "Decision", `${esc(tr(ACTS, pol.act, pol.act || "–"))}<br><span class="hint">${code(pol.reason_code)} · ${esc(pol.allow_quantity ? t("quantity allowed") : t("no quantity"))}</span>`)}
      ${layer("σ", "Sufficiency", suf ? `${esc(t(suf.status))}${missing.length ? `<br><span class="hint">${esc(t("missing: {list}", {list: missing.join("; ")}))}</span>` : ""}` : esc(t("not evaluated")))}
      ${layer("α", "Next question", q && q.input ? esc(inputName(q.input)) : esc(t("none")))}
      ${layer("q", "Input quality", esc(counts(qual, RELIABILITY)))}
      ${layer("π", "Applicability", `${esc(counts(appl, APPLICABILITY))}<br><span class="hint">${esc(t("{n} passages used", {n: (d.passage_budget || []).length}))}</span>`)}
      ${layer("γ", "Grounding", `${gr.action ? code(gr.action) : "–"}<br><span class="hint">${esc(t("{n} unsupported numbers", {n: (gr.unsupported_numbers || []).length}))}</span>`)}
    </div>
    <div class="layers">
      ${layer("", "As of", esc(p.as_of ? fmtDate(p.as_of) + " " + String(p.as_of).slice(11, 16) : "–"))}
      ${layer("", "Corpus hash", `<code>${esc(short(p.corpus_hash))}</code>`)}
      ${layer("", "Model / prompt", `${esc(p.model === "none" ? t("none") : (p.model || "–"))} · <code>${esc(short(p.prompt_hash))}</code>`)}
      ${layer("", "Weather forecast issued", esc(p.forecast_issued_at || "–"))}
    </div>
    ${settingsUsed(p.settings)}
    <p class="row"><button type="button" class="button secondary small prov-dl" data-run="${esc(run.id)}">${esc(t("Download provenance (JSON)"))}</button>
      <span class="hint">${esc(t("The answer with every decision (π, q, σ, α, δ, γ), its sources, the inputs with age and reliability, and the hashes."))}</span></p>
    <details class="raw"><summary>${esc(t("Decisions and provenance (JSON)"))}</summary><pre>${esc(JSON.stringify({decisions: run.decisions, provenance: run.provenance}, null, 2))}</pre></details>
  </details>`;
}

function section(title, inner, extra = "", note = "") {
  return inner ? `<section class="sheet-group"${extra}><h3>${esc(t(title))}${note ? ` <span class="hint-inline">${esc(t(note))}</span>` : ""}</h3>${inner}</section>` : "";
}
const ACT_ICON = {recommend: "M5 12.5l4.2 4.2L19 7", conditional: "M12 7v6M12 16.5v.5", ask: "M9.2 9a2.9 2.9 0 1 1 3.9 2.7c-.7.3-1.1.9-1.1 1.6v.4M12 17v.3",
                  abstain: "M7 12h10", refer: "M7 12h10M13 7l5 5-5 5"};
function answerCard(run) {
  const a = run.answer, act = a.action || {}, L = LANG();
  const data = (a.data_used || []).map((d) => `<li><span>${esc(inputName(d.input, d.label))}</span><span class="v"><span ${L}>${esc(valueText(d.value_text))}</span>${d.reliability === "ungraded" ? "" : ` <span class="pill rel-${esc(d.reliability)}">${esc(tr(RELIABILITY, d.reliability, d.reliability_label))}</span>`}${d.age_days != null ? `<span class="age">${esc(t("{n} d", {n: d.age_days}))}</span>` : ""}</span></li>`).join("");
  const src = (a.sources || []).map((s) => `<li><span class="src-title" ${CORPUS}>${s.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)}</a>` : esc(s.title)}</span> <span class="src-status">π: ${esc(tr(APPLICABILITY, s.applicability, s.applicability_label))}${s.conditions && s.conditions.length ? `; <span ${L}>${esc(s.conditions.join("; "))}</span>` : ""}</span></li>`).join("");
  const why = (a.rationale || []).map((r) => `<li>${esc(r)}</li>`).join("");
  const calc = (a.calculations || []).map((c) => `<li>${esc(typeof c === "string" ? c : c.text || c.label || JSON.stringify(c))}</li>`).join("");
  const nq = a.next_question;
  const opts = nq ? nq.options.map((o) => `<button type="button" class="chip accent" data-input="${esc(nq.input)}" data-value="${esc(o.value)}">${esc(o.label)}</button>`).join("") : "";
  const kv = act.what || act.quantity ? `<dl class="kv">${act.what ? `<dt>${esc(t("Action"))}</dt><dd ${L}>${esc(act.what)}</dd><dt>${esc(t("When / condition"))}</dt><dd ${L}>${esc(act.when_or_condition)}</dd>` : ""}${act.quantity ? `<dt>${esc(t("Quantity"))}</dt><dd ${L}>${esc(act.quantity)}</dd>` : ""}</dl>` : "";
  return `<article class="answer act-${esc(a.act)}">
    <span class="grabber" aria-hidden="true"></span>
    <header><span class="act-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="${ACT_ICON[a.act] || ACT_ICON.abstain}"/></svg></span>
      <span class="act-head"><span class="act-badge">${esc(tr(ACTS, a.act, a.act_label))}</span><span class="meta">${esc(run.variant)} · ${esc(tr(ADVICE, run.advice_type, t("advice type not yet known")))} · ${esc(t("{name} generator", {name: a.generator}))}${a.baseline_label ? ` · ${esc(t("template, not a baseline"))}` : ""}</span></span></header>
    ${customSettingsNotice((run.provenance || {}).settings, false)}
    <p class="summary" ${L}>${esc(a.summary)}</p>
    ${kv}
    ${nq ? `<div class="nextq"><p ${L}>${esc(nq.text)}${nq.how_to_obtain ? `<span class="how">${esc(nq.how_to_obtain)}</span>` : ""}</p><div class="options" ${L}>${opts}</div></div>` : ""}
    ${section("Reasoning", why ? `<ul ${L}>${why}</ul>` : "")}
    ${section("Calculations", calc ? `<ul ${L}>${calc}</ul>` : "", "", "in code, FAO-56")}
    ${section("Based on", a.basis && a.basis.text ? `<p ${L}>${esc(a.basis.text)}</p>` : "")}
    ${section("Data used", data ? `<ul class="rows">${data}</ul>` : "", "", "reliability, age")}
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
document.querySelectorAll(".suggestions .chip").forEach((b) => b.onclick = () => { $("c-text").value = t(b.dataset.q); $("c-text").focus(); });

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
    $("a-out").insertAdjacentHTML("beforeend", `<div class="bubble">${esc(run.question)}</div><article class="answer act-ai">${run.provenance && run.provenance.mode === "app" ? customSettingsNotice(run.provenance.settings, false) : ""}<p class="ai-text" lang="${esc(shownLang)}">${esc(run.answer.text)}</p>
      <details class="raw"><summary>${esc(t("Provenance"))}</summary><pre>${esc(JSON.stringify(run.provenance, null, 2))}</pre></details></article>`);
  } catch (err) { $("a-out").insertAdjacentHTML("beforeend", `<p class="error">${esc(err.message)}</p>`); }
  finally { btn.removeAttribute("aria-busy"); }
};

// ------------------------------------------------------------------ parcel context: weather, NDVI, water balance
// Read-only views of the stored parcel data (GET /series, /water-balance). The client draws and formats only; every
// value comes from the server, and a missing series is shown as missing.
const num = (x, d = 1) => (window.SmartCharts ? SmartCharts.fmtNum(x, d) : (x == null ? "–" : String(x)));
function fmtStamp(s) {
  if (!s) return "–";
  const d = new Date(s);
  return isNaN(d) ? String(s) : d.toLocaleString(intl(), {day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit"});
}
function fmtAge(hours) {
  if (hours == null) return "";
  if (hours < 1) return t("under 1 h ago");
  if (hours < 48) return t("{n} h ago", {n: num(hours, 0)});
  return t("{n} d ago", {n: num(hours / 24, 0)});
}
function emptyState(title, text) {
  return `<div class="ctx-empty" role="note"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.5"/><path d="M8.5 12h7"/></svg><div><strong>${esc(t(title))}</strong><p>${esc(text)}</p></div></div>`;
}
function metaList(pairs) {
  return `<dl class="ctx-meta">${pairs.filter(([, v]) => v).map(([k, v]) => `<dt>${esc(t(k))}</dt><dd>${v}</dd>`).join("")}</dl>`;
}
function dataTable(caption, head, rows) {
  return `<details class="raw tbl"><summary>${esc(t("Show as table"))}</summary><div class="table-wrap" tabindex="0" role="region" aria-label="${esc(t(caption))}">
    <table><caption>${esc(t(caption))}</caption><thead><tr>${head.map((h) => `<th scope="col">${esc(t(h))}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((r) => `<tr>${r.map((c, i) => (i ? `<td>${c}</td>` : `<th scope="row">${c}</th>`)).join("")}</tr>`).join("")}</tbody></table></div></details>`;
}
const NO_PROFILE = "No data have been fetched for this parcel yet. Press “Refresh data” to fetch the weather and Sentinel-2 series.";
// A profile for an earlier decision date is assembled afterwards; its forecast days are the runs issued before it.
const RECONSTRUCTED = "Reconstructed after the fact: past days from the Open-Meteo historical-forecast archive, forecast days from the runs issued before the decision moment (Previous Runs API).";

function renderSeries(s) {
  const w = s.weather, n = s.ndvi;
  let html = `<h3 class="ctx-sub">${esc(t("Weather"))} <span class="hint-inline">${esc(w.source)}</span></h3>`;
  if (w.status !== "ok" || !w.rows.length) {
    html += emptyState("No weather series", w.message === "no_profile" ? t(NO_PROFILE) : (w.message || t("The weather provider returned no data.")));
  } else {
    const hist = w.rows.filter((r) => !r.is_forecast).length, fc = w.rows.length - hist;
    html += metaList([
      ["Endpoint", w.retrospective_constructed ? `<code>${esc(w.endpoint)}</code> ${esc(t("(archived forecast, assembled afterwards)"))}` : (w.endpoint ? `<code>${esc(w.endpoint)}</code>` : "–")],
      ["Retrieved", `${esc(fmtStamp(w.fetched_at))} <span class="hint">${esc(fmtAge(w.age_hours))}</span>`],
      ["Forecast issued", esc(fmtStamp(w.forecast_issued_at))],
      ["Window", esc(t("{hist} days of history, {fc} forecast days", {hist, fc}))],
      ["Decision moment", esc(fmtStamp(s.as_of))],
    ]);
    if (w.retrospective_constructed) html += `<p class="hint reconstructed">${esc(t(RECONSTRUCTED))}</p>`;
    html += `<div class="ch-host" id="ch-temp"></div><div class="ch-host" id="ch-rain"></div>`;
    html += dataTable("Daily weather of the parcel (Open-Meteo)", ["Date", "T min (°C)", "T max (°C)", "Rain (mm)", "ET0 (mm)", "Kind"],
      w.rows.map((r) => [esc(fmtDate(r.date)), num(r.tmin_c), num(r.tmax_c), num(r.precip_mm), num(r.et0_mm), esc(r.is_forecast ? t("forecast") : t("history"))]));
  }
  html += `<h3 class="ctx-sub">NDVI <span class="hint-inline">${esc(n.source)}</span></h3>`;
  if (n.status !== "ok" || !n.rows.length) {
    html += emptyState("No NDVI series", n.message === "no_profile" ? t(NO_PROFILE) : (n.message || t("No usable Sentinel-2 observation.")));
  } else {
    html += metaList([
      ["Retrieved", `${esc(fmtStamp(n.fetched_at))} <span class="hint">${esc(fmtAge(n.age_hours))}</span>`],
      ["Latest obs_date", `${esc(fmtDate(n.latest_obs_date))} <span class="hint">${esc(n.latest_age_days != null ? t("{n} d before the decision moment", {n: n.latest_age_days}) : "")}</span>`],
      ["Cloud mask", esc(t("SCL per pixel (cloud, shadow, cirrus, snow excluded); valid_px_ratio = usable pixels / all pixels"))],
      ["cloud_flag", esc(n.cloud_flag === true ? t("yes") : n.cloud_flag === false ? t("no") : t("not reported for this observation"))],
      ["Trend", esc(t("observations with valid_px_ratio ≥ {share} (core NDVI tool); hollow points are below it", {share: n.trend_min_share}))],
    ]);
    const pf = s.parcel_features;
    if (pf) {
      const se = pf.stage_estimate, pr = pf.producer || {};
      html += metaList([
        ["Parcel features", esc(pf.status === "ok" ? t("accepted") : pf.status === "rejected" ? `${t("rejected")}: ${pf.message}` : t("no document for this parcel and day"))],
        ["Producer", pr.name ? esc([pr.name, pr.version].filter(Boolean).join(" ")) : ""],
        ["Document sha256", pf.document_sha256 ? `<code>${esc(String(pf.document_sha256).slice(0, 16))}…</code>` : ""],
        ["Satellite stage estimate", se ? esc(se.bbch_min != null ? t("BBCH {lo}–{hi} ({method}), {n} clear observations", {lo: se.bbch_min, hi: se.bbch_max, method: se.method, n: se.n_clear_obs ?? "–"}) : t("no estimate ({status})", {status: se.status})) : ""],
      ]);
    }
    html += `<div class="ch-host" id="ch-ndvi"></div>`;
    const dash = (v, f) => (v == null ? "–" : f(v));
    html += dataTable("Sentinel-2 L2A NDVI observations of the parcel", ["obs_date", "Median", "p10", "p90", "valid_px_ratio", "Used for trend", "cloud_flag", "Cloud and shadow share", "Interior pixels", "Mixed-pixel share", "Outlier"],
      n.rows.map((r) => [esc(r.obs_date), num(r.median, 3), num(r.p10, 3), num(r.p90, 3), num(r.valid_px_ratio, 3), r.meets_trend_share ? t("yes") : t("no"),
        dash(r.cloud_flag, (v) => (v ? t("yes") : t("no"))),
        r.cloud_px_share == null && r.shadow_px_share == null ? "–" : num((r.cloud_px_share || 0) + (r.shadow_px_share || 0), 2),
        dash(r.n_px_interior, (v) => String(v)), dash(r.mixed_px_share, (v) => num(v, 2)), dash(r.temporal_outlier, (v) => (v ? t("yes") : t("no")))]));
  }
  $("p-series").innerHTML = html;
  if (w.status === "ok" && w.rows.length && window.SmartCharts) {
    SmartCharts.chart($("ch-temp"), {title: t("Daily temperature (°C)"), unit: "°C", x: "date", forecast: "is_forecast", rows: w.rows,
      desc: t("Daily minimum and maximum air temperature from {source}, {n} days including the forecast.", {source: w.source, n: w.rows.length}),
      series: [{key: "tmax_c", kind: "line", cls: "s-evap", label: "T max"}, {key: "tmin_c", kind: "line", cls: "s-rain", label: "T min"}]});
    SmartCharts.chart($("ch-rain"), {title: t("Rainfall and reference evapotranspiration ET0 (mm/day)"), unit: "mm", x: "date", forecast: "is_forecast", rows: w.rows,
      desc: t("Daily rainfall as bars and FAO-56 reference evapotranspiration ET0 as a line, from {source}.", {source: w.source}),
      series: [{key: "precip_mm", kind: "bar", cls: "s-rain", label: t("Rain")}, {key: "et0_mm", kind: "line", cls: "s-evap", label: "ET0"}]});
  }
  if (n.status === "ok" && n.rows.length && window.SmartCharts) {
    SmartCharts.chart($("ch-ndvi"), {title: t("NDVI median per observation, p10–p90 range"), x: "obs_date", rows: n.rows, yMin: 0, yMax: 1, digits: 3,
      desc: t("Sentinel-2 L2A NDVI of the parcel, {n} observations; whiskers show the 10th to 90th percentile within the parcel.", {n: n.rows.length}),
      series: [{key: "median", lo: "p10", hi: "p90", kind: "dot", cls: "s-ndvi", label: t("NDVI median"), hollow: (r) => r.meets_trend_share === false,
                note: (r) => `; valid_px_ratio ${num(r.valid_px_ratio, 2)}`}],
      legendExtra: [{kind: "dot hollow", cls: "s-ndvi", label: t("valid_px_ratio below {share}", {share: n.trend_min_share})}]});
  }
}

const ASSUMPTIONS = {
  stage_from_days_since_sowing: "Growth stage of each day estimated from the days since sowing (core phenology tool).",
  stage_constant: "No sowing date: the growth stage of the decision date is used for every day.",
  no_stage: "No sowing date and no growth stage: Kc, ETc and the deficit cannot be computed.",
  deficit_starts_at_zero: "The deficit starts at 0 mm on the first day (root zone assumed full): an assumption, not a measurement.",
  no_taw_cap: "Soil water-holding capacity unknown: the deficit is not capped at TAW.",
  taw_cap: "The deficit is capped at the total available water TAW = AWC × Zr (AWC from the soil texture, Zr from the growth stage).",
};
function renderWater(b) {
  let html = "";
  if (b.status === "missing") {
    $("p-water").innerHTML = emptyState("No water balance", b.message === "no_profile" ? t(NO_PROFILE)
      : (b.message === "no_weather" ? t("There is no weather series to balance.") : b.message));
    return;
  }
  const tot = b.totals || {}, last = b.deficit_last_observed;
  html += `<div class="tiles">
    <div class="tile"><span>${esc(t("ET0, {n} observed days", {n: tot.observed_days}))}</span><strong>${num(tot.et0_observed_mm)} mm</strong></div>
    <div class="tile"><span>ETc = Kc × ET0</span><strong>${num(tot.etc_observed_mm)} mm</strong></div>
    <div class="tile"><span>${esc(t("Rainfall"))}</span><strong>${num(tot.rain_observed_mm)} mm</strong></div>
    <div class="tile"><span>${esc(t("Deficit"))}${last ? ", " + esc(fmtDate(last.date)) : ""}</span><strong>${last ? num(last.deficit_mm) + " mm" : "–"}</strong>${b.taw_mm != null ? `<small>${esc(t("of TAW {v} mm", {v: num(b.taw_mm)}))}</small>` : ""}</div>
  </div>`;
  if (b.status === "ok" && b.weather_retrospective_constructed) html += `<p class="hint reconstructed">${esc(t(RECONSTRUCTED))}</p>`;
  if (b.status === "ok") html += `<div class="ch-host" id="ch-deficit"></div><div class="ch-host" id="ch-etc"></div>`;
  html += `<ul class="assumptions">${(b.assumptions || []).map((a) => `<li>${esc(tr(ASSUMPTIONS, a))}</li>`).join("")}</ul>`;
  html += `<p class="formula"><code>${esc(b.formula_etc)}</code> <span class="hint">${esc(t(b.source_etc))}; ${esc(t("Kc by BBCH from"))} <code>config/kc_maize.yaml</code></span><br>
    <code>${esc(b.formula_deficit)}</code> <span class="hint">${esc(t(b.source_deficit))}</span></p>`;
  html += dataTable("Daily FAO-56 water balance of the parcel", ["Date", "BBCH", "ET0 (mm)", "Kc", "ETc (mm)", "Rain (mm)", "Deficit (mm)", "TAW (mm)"],
    b.rows.map((r) => [esc(fmtDate(r.date)) + (r.is_forecast ? ` <span class="hint">${esc(t("forecast"))}</span>` : ""), r.bbch == null ? "–" : esc(r.bbch),
      num(r.et0_mm), num(r.kc, 2), num(r.etc_mm), num(r.rain_mm), num(r.deficit_mm), num(r.taw_mm)]));
  $("p-water").innerHTML = html;
  if (b.status === "ok" && window.SmartCharts) {
    SmartCharts.chart($("ch-deficit"), {title: t("Root-zone deficit (mm)"), unit: "mm", x: "date", forecast: "is_forecast", rows: b.rows, yMin: 0,
      desc: t("Daily root-zone depletion from the FAO-56 balance, starting at 0 mm on the first day; the dashed line is the total available water TAW."),
      series: [{key: "deficit_mm", kind: "line", cls: "s-evap", label: t("Deficit")}],
      refs: b.taw_mm != null ? [{value: b.taw_mm, label: `TAW ${num(b.taw_mm)} mm`}] : []});
    SmartCharts.chart($("ch-etc"), {title: t("Crop evapotranspiration ETc and rainfall (mm/day)"), unit: "mm", x: "date", forecast: "is_forecast", rows: b.rows,
      desc: t("Daily rainfall as bars and crop evapotranspiration ETc = Kc × ET0 as a line."),
      series: [{key: "rain_mm", kind: "bar", cls: "s-rain", label: t("Rain")}, {key: "etc_mm", kind: "line", cls: "s-evap", label: "ETc"}]});
  }
}

async function loadContext() {
  if (!parcel) return;
  const id = parcel.id;
  $("p-series").innerHTML = `<div class="skeleton"></div>`;
  $("p-water").innerHTML = `<div class="skeleton"></div>`;
  try {
    const [s, b] = await Promise.all([api(`/parcels/${id}/series`), api(`/parcels/${id}/water-balance`)]);
    if (!parcel || parcel.id !== id) return;
    renderSeries(s);
    renderWater(b);
  } catch (e) {
    $("p-series").innerHTML = `<p class="error">${esc(e.message)}</p>`;
    $("p-water").innerHTML = "";
  }
}

// ------------------------------------------------------------------ provenance export (answer "Why?" panel)
document.addEventListener("click", async (e) => {
  const btn = e.target.closest && e.target.closest(".prov-dl");
  if (!btn) return;
  btn.setAttribute("aria-busy", "true");
  try {
    const doc = await api(`/runs/${encodeURIComponent(btn.dataset.run)}/provenance`);
    const url = URL.createObjectURL(new Blob([JSON.stringify(doc, null, 2) + "\n"], {type: "application/json"}));
    const a = document.createElement("a");
    a.href = url; a.download = `provenance-${btn.dataset.run}.json`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (err) { btn.insertAdjacentHTML("afterend", ` <span class="error">${esc(err.message)}</span>`); }
  finally { btn.removeAttribute("aria-busy"); }
});

// ------------------------------------------------------------------ evaluation overview (read-only, from evalkit)
// Not linked from the blind rating screen. Every number is passed through from evalkit; the client only formats.
const pct = (x) => (x == null ? "–" : num(x, 3));
const ci = (c) => (c && c.length === 2 ? `[${num(c[0], 3)}; ${num(c[1], 3)}]` : "–");
function evalSet(s) {
  const dev = !s.experiment_result;
  const badge = dev ? `<span class="pill set-dev">${esc(t("Development set · not experiment results"))}</span>` : `<span class="pill set-test">${esc(t("Test set"))}</span>`;
  const runs = s.batches.map((b) => [`<code>${esc(String(b.batch_id).slice(0, 8))}</code>`, esc(b.variant), esc(fmtStamp(b.created_at)), esc(b.n)]);
  const auto = s.ladder.concat(s.variants.filter((v) => !s.ladder.includes(v))).map((v) => {
    const a = s.automatic[v];
    if (!a) return [esc(v), "–", "–", "–", "–", "–", "–", "–", "–", "–"];
    const tag = a.baseline_label ? ` <span class="pill set-dev">${esc(t("template, not a baseline"))}</span>` : "";
    return [esc(v) + tag, esc(a.n), `${pct(a.act_accuracy)} <span class="hint">n=${esc(a.act_accuracy_n)}</span>`, pct(a.question_target_accuracy),
            pct(a.coverage), pct(a.first_ask_share), pct(a.recall_at_k), pct(a.citation_coverage), pct(a.support_rate), esc(a.failed)];
  });
  const steps = s.steps.map((st) => {
    const p = st.paired;
    return [`${esc(st.a)} − ${esc(st.b)}`, esc(st.comparison || "–"), p ? esc(p.n) : "–", p ? pct(p.b) : "–", p ? pct(p.a) : "–",
            p ? pct(p.diff) : "–", p ? ci(p.ci95) : "–", p ? esc(`${p.wins} / ${p.ties} / ${p.losses}`) : "–"];
  });
  const raters = Object.keys(s.raters || {});
  let rated = `<p class="hint">${esc(t("No ratings for this set yet: rubric scores, their paired differences with bootstrap intervals and rater agreement appear after blind rating."))}</p>`;
  if (raters.length) {
    rated = raters.map((r) => {
      const x = s.raters[r];
      const rows = Object.entries(x.rated).map(([v, m]) => [esc(v), esc(m.n_scenarios), pct(m.rubric_total), pct(m.critical_rate), pct(m.k4_rate)]);
      const st = x.steps.map((q) => [`${esc(q.a)} − ${esc(q.b)}`, q.paired ? esc(q.paired.n_scenarios) : "–", q.paired ? `${pct(q.paired.rubric_diff)} ${ci(q.paired.rubric_ci95)}` : "–",
                                     q.paired ? `${pct(q.paired.critical_rate_diff)} ${ci(q.paired.critical_ci95)}` : "–", q.paired ? esc(q.paired.bootstrap) : "–"]);
      return `<h4>${esc(t("Rater {name}", {name: r}))}</h4>${table(["Variant", "Scenarios", "Rubric total (0–10)", "Critical error rate", "K4 rate"], rows)}
        ${table(["Step", "n", "Rubric difference [95% CI]", "Critical rate difference [95% CI]", "Bootstrap"], st)}`;
    }).join("");
  }
  let agree = "";
  if (s.agreement && s.agreement.status === "mixed_sets") agree = `<p class="hint">${esc(t("Rater agreement is not shown: the two raters also rated items of another set."))}</p>`;
  else if (s.agreement) {
    agree = table(["Criterion", "Weighted κ (quadratic)", "Percent agreement"],
      ["r1", "r2", "r3", "r4", "r5"].map((c) => [c, pct(s.agreement[c].kappa_quadratic), pct(s.agreement[c].percent_agreement)])
        .concat([["critical (any)", pct(s.agreement.critical_any.kappa), pct(s.agreement.critical_any.percent_agreement)]]));
    agree = `<h4>${esc(t("Agreement, {raters} (n = {n})", {raters: s.agreement.raters.join(" / "), n: s.agreement.n_items}))}</h4>` + agree;
  }
  return `<section class="card eval-set ${dev ? "is-dev" : ""}" aria-labelledby="es-${esc(s.set)}">
    <div class="eval-head"><h2 id="es-${esc(s.set)}">${esc(t(s.label.charAt(0).toUpperCase() + s.label.slice(1)))}</h2>${badge}</div>
    ${dev ? `<p class="dev-note">${esc(t("These runs use the development scenarios, which were used to build the system. They show that the pipeline and the measures work; they are not results of the experiment and support no conclusion about the planned comparisons."))}</p>` : ""}
    <p class="hint">${esc(t("{n} answers in {runs} runs; {rated} rated.", {n: s.n_items, runs: s.batches.length, rated: s.n_rated_items}))}</p>
    <h3 class="ctx-sub">${esc(t("Runs"))}</h3>${table(["Run", "Variant", "Created", "Answers"], runs)}
    <h3 class="ctx-sub">${esc(t("Ladder V0–V5"))} <span class="hint-inline">${esc(t("automatic measures"))}</span></h3>
    ${(s.template_variants || []).length ? `<p class="dev-note" role="note">${esc(t("Variants {list} were produced by the template generator, which always recommends. They are a fallback for checking the development set, not a baseline result of those rungs.", {list: s.template_variants.join(", ")}))}</p>` : ""}
    ${table(["Variant", "n", "Act accuracy", "Question target", "Coverage", "First ask share", "Recall@k", "Citation coverage", "Support rate", "Failed"], auto)}
    <h3 class="ctx-sub">${esc(t("Steps of the ladder"))} <span class="hint-inline">${esc(t("act correctness, paired by scenario"))}</span></h3>
    ${table(["Step", "Comparison", "n", "Lower rung", "Upper rung", "Difference", "95% CI (bootstrap)", "Wins / ties / losses"], steps)}
    <p class="hint">${esc(t("Percentile bootstrap of the mean paired difference, 10 000 resamples, seed 7; clusters of scenarios that share a parcel are resampled together (evalkit.report)."))}</p>
    <h3 class="ctx-sub">${esc(t("Rated measures and rater agreement"))}</h3>${rated}${agree}
    <details class="raw"><summary>${esc(t("Report tables as printed by"))} <code>evalkit report --format md</code></summary><pre lang="sr-Latn">${esc(s.report_md)}</pre></details>
  </section>`;
}
function table(head, rows) {
  if (!rows.length) return `<p class="hint">${esc(t("None."))}</p>`;
  return `<div class="table-wrap" tabindex="0" role="region" aria-label="${esc(head.map((h) => t(h)).join(", "))}"><table><thead><tr>${head.map((h) => `<th scope="col">${esc(t(h))}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((r) => `<tr>${r.map((c, i) => (i ? `<td>${c}</td>` : `<th scope="row">${c}</th>`)).join("")}</tr>`).join("")}</tbody></table></div>`;
}
const GUARD = {clean: "clean", hits: "overlap found", absent: "no scenarios in this folder"};
const LOCK_CHECK = {matches: "The current files match the lock.", differs: "{n} file(s) differ from the lock.", not_verifiable: "Cannot be verified here."};
async function loadEval() {
  const out = $("e-out");
  out.innerHTML = `<div class="skeleton"></div>`;
  let o;
  try { o = await api("/evaluation/overview"); }
  catch (e) { out.innerHTML = `<p class="error">${esc(e.message)}</p>`; return; }
  const lock = o.lock || {};
  const lockText = lock.status === "locked"
    ? `${esc(lock.tag)} · ${esc(t("set {name}", {name: lock.set}))} · ${esc(fmtStamp(lock.created_at))}<br><code class="hash">${esc(lock.combined_sha256)}</code><br><span class="hint">${esc(LOCK_CHECK[lock.check] ? t(LOCK_CHECK[lock.check], {n: lock.n_differences}) : "")}</span>`
    : lock.status === "not_locked" ? esc(t("Not locked yet: there is no protocol lock file. The test set runs only after the lock.")) : esc(lock.message || lock.status);
  const guard = (o.guard || []).map((g) => [esc(g.set), esc(tr(GUARD, g.status)), g.n_fields != null ? esc(g.n_fields) : "–",
    g.n_hits != null ? esc(g.n_hits) : "–", g.n_corpus_passages != null ? esc(g.n_corpus_passages) : "–"]);
  const sets = o.sets.length ? o.sets.map(evalSet).join("")
    : `<div class="card">${emptyState("No evaluation runs in this database", t("Run the development set with python -m smartagri.evalkit run --set dev. The test set runs only under the locked protocol; until then no experiment results exist."))}</div>`;
  out.innerHTML = `${o.has_test_results ? "" : `<div class="banner eval-banner" role="note"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5v5M12 16v.5"/></svg><p>${esc(t("No test-set results yet. Nothing on this page is a result of the experiment."))}</p></div>`}
    <div class="eval-grid">
      <section class="card" aria-labelledby="lock-title"><h2 id="lock-title">${esc(t("Protocol lock"))}</h2><p>${lockText}</p><p class="hint"><code>${esc(o.commands.lock_check)}</code></p></section>
      <section class="card" aria-labelledby="guard-title"><h2 id="guard-title">${esc(t("Leakage guard"))}</h2>
        ${table(["Set", "Result", "Text fields", "Overlaps", "Corpus passages"], guard)}
        <p class="hint">${esc(t("Word 8-gram overlap of scenario texts with the corpus (and, for the test set, with the development scenarios); counts only, no scenario text is shown. The git-isolation checks run with"))} <code>${esc(o.commands.guard)}</code>.</p></section>
    </div>
    ${sets}`;
}

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
  $("account-name").textContent = u ? u.email : t("Sign in");
  $("account-sub").textContent = u ? t("Signed in") : t("Parcels are not saved");
  $("account-avatar").textContent = u ? initial(u.email) : "";
  $("account-avatar").classList.toggle("anon", !u);
  $("account-open").setAttribute("aria-label", u ? t("Account: {email}", {email: u.email}) : t("Account: sign in or create an account"));
  $("account-icon").setAttribute("aria-label", u ? t("Account: {email}", {email: u.email}) : t("Account: sign in"));
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
    ? t("Temporary — this parcel is kept only for this browser session. Create an account to save it.")
    : t("Temporary — these parcels are kept only for this browser session. Create an account to save them.");
  $("banner-signup").textContent = n === 1 ? t("Save parcel") : t("Save parcels");
  if (parcel) $("p-temp").hidden = !unsaved();
}
function accPane(id) {
  for (const p of ACC_PANES) $(p).hidden = p !== id;
  const titles = {"acc-auth": "Account", "acc-forgot-form": "Reset password", "acc-reset-form": "New password",
                  "acc-menu": "Account", "acc-notice": "Account"};
  $("acc-title").textContent = t(titles[id]);
}
function accSet(mode) {
  accMode = mode;
  const up = mode === "signup";
  $("acc-tab-in").setAttribute("aria-selected", String(!up)); $("acc-tab-in").tabIndex = up ? -1 : 0;
  $("acc-tab-up").setAttribute("aria-selected", String(up)); $("acc-tab-up").tabIndex = up ? 0 : -1;
  $("acc-form").setAttribute("aria-labelledby", up ? "acc-tab-up" : "acc-tab-in");
  $("acc-submit").textContent = up ? t("Create account") : t("Sign in");
  $("acc-password").autocomplete = up ? "new-password" : "current-password";
  $("acc-pw-hint").hidden = !up;
  $("acc-claim").textContent = t("Your parcels from this browser session are saved to your account.");
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
  if (!email || !password) { $("acc-msg").textContent = t("Enter your email and password."); return; }
  if (accMode === "signup" && password.length < 10) { $("acc-msg").textContent = t("Use a password of at least 10 characters."); return; }
  btn.setAttribute("aria-busy", "true");
  try {
    const r = await api(accMode === "signup" ? "/auth/signup" : "/auth/signin", {method: "POST", body: JSON.stringify({email, password})});
    $("acc-password").value = "";
    if (r.verify_sent) { notice(t("We have sent a confirmation link to {email}. Open it, then sign in. Until then your parcels are kept only for this browser session.", {email})); return; }
    $("account-sheet").close();
    await afterAuth(r.user);
  } catch (err) { $("acc-msg").textContent = err.message; }
  finally { btn.removeAttribute("aria-busy"); }
};
$("acc-forgot-form").onsubmit = async (e) => {
  e.preventDefault();
  const email = $("acc-forgot-email").value.trim();
  if (!email) { $("acc-forgot-msg").textContent = t("Enter your email."); return; }
  $("acc-forgot-send").setAttribute("aria-busy", "true");
  try {
    await api("/auth/password/forgot", {method: "POST", body: JSON.stringify({email})});
    notice(t("If an account exists for {email}, a link to choose a new password is on its way. It is valid for one hour.", {email}));
  } catch (err) { $("acc-forgot-msg").textContent = err.message; }
  finally { $("acc-forgot-send").removeAttribute("aria-busy"); }
};
let resetToken = "";
$("acc-reset-form").onsubmit = async (e) => {
  e.preventDefault();
  const password = $("acc-reset-password").value;
  if (password.length < 10) { $("acc-reset-msg").textContent = t("Use a password of at least 10 characters."); return; }
  $("acc-reset-save").setAttribute("aria-busy", "true");
  try {
    const r = await api("/auth/password/reset", {method: "POST", body: JSON.stringify({token: resetToken, password})});
    $("acc-reset-password").value = "";
    await afterAuth(r.user);
    notice(t("Your password has been changed and you are signed in."));
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
  if (!password) { $("acc-delete-msg").textContent = t("Enter your password to confirm."); return; }
  $("acc-delete-confirm").setAttribute("aria-busy", "true");
  try {
    await api("/auth/account/delete", {method: "POST", body: JSON.stringify({password})});
    await afterAuth(null);
    notice(t("Your account and its data have been deleted."));
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
        $("acc-claim").textContent = t("Your email is confirmed. Sign in to continue."); }
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

init().catch((e) => { $("health").classList.add("down"); $("health").textContent = t("The research API is not reachable: ") + e.message; });
