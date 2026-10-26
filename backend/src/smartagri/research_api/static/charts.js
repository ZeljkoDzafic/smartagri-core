// Small hand-written SVG charts of the research client (no library, no build step). Every chart is an SVG with
// role="img", <title> and <desc>, a legend for two or more series, one y axis, a native tooltip on every mark and a
// table fallback written by the caller. The chart is drawn at the width of its container and redrawn on resize, so
// text stays readable at 360 px. Colours come from CSS classes (light and dark themes in app.css).
"use strict";

(function () {
  const NS = "http://www.w3.org/2000/svg";
  const DAY = 86400000;
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const time = (d) => Date.parse(String(d).slice(0, 10) + "T00:00:00Z");
  const tr = (key) => (window.SmartI18n ? SmartI18n.t(key) : key);
  const intl = () => (window.SmartI18n ? SmartI18n.intl() : "en-GB");
  const dayLabel = (t) => new Date(t).toLocaleDateString(intl(), {day: "numeric", month: "short", timeZone: "UTC"});
  let uid = 0;
  const drawn = new Set();

  function niceStep(span, count) {
    const raw = span / Math.max(1, count);
    const mag = Math.pow(10, Math.floor(Math.log10(raw || 1)));
    const n = raw / mag;
    return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * mag;
  }
  function fmtNum(x, digits) {
    if (x == null || Number.isNaN(x)) return "–";
    return Number(x).toLocaleString(intl(), {maximumFractionDigits: digits == null ? 1 : digits});
  }

  // opts: {title, desc, unit, rows, x, series: [{key, kind: "bar"|"line"|"dot", cls, label, lo, hi, hollow(row)}],
  //        yMin, yMax, forecast: "is_forecast", refs: [{value, label}], digits, height}
  function draw(el, opts) {
    const id = "ch" + (++uid);
    const width = Math.max(280, Math.floor(el.clientWidth || 600));
    const phone = width < 480;
    const height = opts.height || (phone ? 190 : 220);
    const m = {top: 14, right: 12, bottom: 26, left: phone ? 38 : 44};
    const rows = (opts.rows || []).filter((r) => r[opts.x]);
    const ts = rows.map((r) => time(r[opts.x]));
    if (!rows.length) { el.innerHTML = ""; return; }
    const t0 = Math.min(...ts) - DAY / 2, t1 = Math.max(...ts) + DAY / 2;
    const vals = [];
    for (const s of opts.series) for (const r of rows) for (const k of [s.key, s.lo, s.hi]) if (k && r[k] != null) vals.push(Number(r[k]));
    for (const ref of opts.refs || []) if (ref.value != null) vals.push(Number(ref.value));
    let lo = opts.yMin != null ? opts.yMin : Math.min(0, ...vals), hi = opts.yMax != null ? opts.yMax : Math.max(...vals, lo + 1);
    const step = niceStep(hi - lo, phone ? 3 : 4);
    if (opts.yMin == null) lo = Math.floor(lo / step) * step;
    if (opts.yMax == null) hi = Math.ceil(hi / step) * step;
    if (hi <= lo) hi = lo + step;
    const W = width - m.left - m.right, H = height - m.top - m.bottom;
    const X = (t) => m.left + (t - t0) / (t1 - t0) * W;
    const Y = (v) => m.top + (1 - (v - lo) / (hi - lo)) * H;
    const parts = [];
    // forecast band
    if (opts.forecast) {
      const f = rows.findIndex((r) => r[opts.forecast]);
      if (f >= 0) {
        const fx = X(ts[f] - DAY / 2);
        parts.push(`<rect class="ch-forecast" x="${fx.toFixed(1)}" y="${m.top}" width="${(m.left + W - fx).toFixed(1)}" height="${H}"/>`);
        parts.push(`<text class="ch-note" x="${(fx + 4).toFixed(1)}" y="${m.top + 11}">${esc(tr("Forecast"))}</text>`);
      }
    }
    // grid and y axis
    for (let v = lo; v <= hi + step / 1000; v += step) {
      const y = Y(v).toFixed(1);
      parts.push(`<line class="ch-grid" x1="${m.left}" x2="${m.left + W}" y1="${y}" y2="${y}"/>`);
      parts.push(`<text class="ch-tick" x="${m.left - 6}" y="${y}" dy="0.32em" text-anchor="end">${esc(fmtNum(v, step < 1 ? 1 : 0))}</text>`);
    }
    // x ticks: about one per 70 px, on whole days
    const days = Math.round((t1 - t0) / DAY);
    const every = Math.max(1, Math.ceil(days / Math.max(2, Math.floor(W / (phone ? 64 : 76)))));
    const first = Math.ceil((t0 + DAY / 2) / DAY) * DAY;
    for (let t = first; t <= t1; t += every * DAY) {
      parts.push(`<text class="ch-tick" x="${X(t).toFixed(1)}" y="${m.top + H + 17}" text-anchor="middle">${esc(dayLabel(t))}</text>`);
    }
    parts.push(`<line class="ch-axis" x1="${m.left}" x2="${m.left + W}" y1="${Y(Math.max(lo, 0)).toFixed(1)}" y2="${Y(Math.max(lo, 0)).toFixed(1)}"/>`);
    // reference lines
    for (const ref of opts.refs || []) {
      if (ref.value == null) continue;
      const y = Y(ref.value).toFixed(1);
      parts.push(`<line class="ch-ref" x1="${m.left}" x2="${m.left + W}" y1="${y}" y2="${y}"><title>${esc(ref.label)}</title></line>`);
      parts.push(`<text class="ch-note" x="${m.left + W - 4}" y="${(Number(y) - 4).toFixed(1)}" text-anchor="end">${esc(ref.label)}</text>`);
    }
    // marks
    const bw = Math.max(2, W / Math.max(1, days) - 2);
    const unit = opts.unit ? " " + opts.unit : "";
    for (const s of opts.series) {
      const tip = (r, v) => `${dayLabel(time(r[opts.x]))}${r[opts.forecast] ? " (" + tr("forecast") + ")" : ""}: ${s.label} ${fmtNum(v, opts.digits)}${unit}`;
      if (s.kind === "bar") {
        rows.forEach((r, i) => {
          if (r[s.key] == null) return;
          const v = Number(r[s.key]), y0 = Y(Math.max(lo, 0)), y = Y(v);
          const h = Math.max(v > 0 ? 1 : 0, Math.abs(y0 - y));
          parts.push(`<rect class="ch-bar ${s.cls}" x="${(X(ts[i]) - bw / 2).toFixed(1)}" y="${Math.min(y, y0).toFixed(1)}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}" rx="${Math.min(2, bw / 2).toFixed(1)}"><title>${esc(tip(r, v))}</title></rect>`);
        });
      } else if (s.kind === "line") {
        let path = "", open = false;
        rows.forEach((r, i) => {
          if (r[s.key] == null) { open = false; return; }
          path += `${open ? "L" : "M"}${X(ts[i]).toFixed(1)} ${Y(Number(r[s.key])).toFixed(1)}`;
          open = true;
        });
        parts.push(`<path class="ch-line ${s.cls}" d="${path}"/>`);
        rows.forEach((r, i) => {          // invisible hit targets with the value, larger than the line
          if (r[s.key] == null) return;
          parts.push(`<circle class="ch-hit" cx="${X(ts[i]).toFixed(1)}" cy="${Y(Number(r[s.key])).toFixed(1)}" r="7"><title>${esc(tip(r, Number(r[s.key])))}</title></circle>`);
        });
      } else if (s.kind === "dot") {
        rows.forEach((r, i) => {
          if (r[s.key] == null) return;
          const x = X(ts[i]).toFixed(1);
          if (s.lo && s.hi && r[s.lo] != null && r[s.hi] != null) {
            parts.push(`<line class="ch-whisker ${s.cls}" x1="${x}" x2="${x}" y1="${Y(Number(r[s.lo])).toFixed(1)}" y2="${Y(Number(r[s.hi])).toFixed(1)}"/>`);
          }
          const hollow = s.hollow && s.hollow(r);
          const extra = s.note ? s.note(r) : "";
          parts.push(`<circle class="ch-dot ${s.cls}${hollow ? " hollow" : ""}" cx="${x}" cy="${Y(Number(r[s.key])).toFixed(1)}" r="5"><title>${esc(tip(r, Number(r[s.key])) + extra)}</title></circle>`);
        });
      }
    }
    const legend = opts.series.length + (opts.legendExtra || []).length >= 2
      ? `<ul class="ch-legend">${opts.series.map((s) => `<li><span class="sw ${s.kind} ${s.cls}" aria-hidden="true"></span>${esc(s.label)}</li>`).join("")}${(opts.legendExtra || []).map((x) => `<li><span class="sw ${esc(x.kind)} ${esc(x.cls)}" aria-hidden="true"></span>${esc(x.label)}</li>`).join("")}</ul>` : "";
    el.innerHTML = `<figure class="chart"><figcaption class="ch-title">${esc(opts.title)}</figcaption>${legend}
      <svg xmlns="${NS}" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="${id}-t ${id}-d">
        <title id="${id}-t">${esc(opts.title)}</title><desc id="${id}-d">${esc(opts.desc)}</desc>${parts.join("")}</svg></figure>`;
  }

  function chart(el, opts) {
    el._chart = opts;
    drawn.add(el);
    draw(el, opts);
  }
  let timer = null, lastWidth = window.innerWidth;
  window.addEventListener("resize", () => {
    if (window.innerWidth === lastWidth) return;
    lastWidth = window.innerWidth;
    clearTimeout(timer);
    timer = setTimeout(() => {
      for (const el of Array.from(drawn)) {
        if (!el.isConnected) { drawn.delete(el); continue; }
        if (el.offsetParent !== null) draw(el, el._chart);
      }
    }, 120);
  });
  // a chart drawn while hidden (zero width) is drawn again once visible
  function refresh(root) {
    for (const el of Array.from(drawn)) if (el.isConnected && (!root || root.contains(el))) draw(el, el._chart);
  }
  window.SmartCharts = {chart, refresh, fmtNum};
})();
