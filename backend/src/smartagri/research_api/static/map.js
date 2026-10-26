// Map helpers of the research client: tile settings, a small polygon drawer and a read-only parcel map.
// Leaflet (vendor/leaflet, BSD-2-Clause) is the only map library; drawing is implemented here.
"use strict";

window.SmartMap = (function () {
  const DEFAULT_CENTER = [45.323, 19.705];
  const DEFAULT_ZOOM = 15;
  const KEY_TILES = "smartagri.tileUrl";
  const KEY_ATTR = "smartagri.tileAttribution";

  function meta(name) {
    const el = document.querySelector('meta[name="' + name + '"]');
    return el ? el.getAttribute("content") || "" : "";
  }
  function stored(key) {
    try { return localStorage.getItem(key) || ""; } catch (e) { return ""; }
  }

  // Tile settings: per-browser override (settings sheet), else the server default from the page.
  function tileSettings() {
    const url = (stored(KEY_TILES) || meta("smartagri-tile-url")).trim();
    const attribution = stored(KEY_ATTR) || meta("smartagri-tile-attribution");
    return { url: url, attribution: attribution, off: !url || url.toLowerCase() === "none" };
  }
  function saveTileSettings(url, attribution) {
    try {
      if (url) localStorage.setItem(KEY_TILES, url); else localStorage.removeItem(KEY_TILES);
      if (attribution) localStorage.setItem(KEY_ATTR, attribution); else localStorage.removeItem(KEY_ATTR);
    } catch (e) { /* storage unavailable: the server default stays in use */ }
  }

  // Approximate geodesic area of a ring (m²), spherical-excess formula; the server computes the exact area.
  function ringArea(latlngs) {
    const R = 6378137, rad = Math.PI / 180;
    let sum = 0;
    for (let i = 0; i < latlngs.length; i++) {
      const a = latlngs[i], b = latlngs[(i + 1) % latlngs.length];
      sum += (b.lng - a.lng) * rad * (2 + Math.sin(a.lat * rad) + Math.sin(b.lat * rad));
    }
    return Math.abs(sum * R * R / 2);
  }

  function toGeoJSON(latlngs) {
    const ring = latlngs.map(function (p) { return [round(p.lng), round(p.lat)]; });
    ring.push(ring[0].slice());
    return { type: "Polygon", coordinates: [ring] };
  }
  function round(x) { return Math.round(x * 1e6) / 1e6; }

  // The outer ring of a GeoJSON Polygon, Feature or FeatureCollection, as Leaflet latlngs (without the closing point).
  function ringFrom(value) {
    let g = value;
    if (g && g.type === "FeatureCollection" && g.features && g.features.length) g = g.features[0];
    if (g && g.type === "Feature") g = g.geometry;
    if (!g || g.type !== "Polygon" || !Array.isArray(g.coordinates) || !Array.isArray(g.coordinates[0])) return null;
    const ring = g.coordinates[0].map(function (c) { return L.latLng(c[1], c[0]); });
    if (ring.length > 1 && ring[0].equals(ring[ring.length - 1])) ring.pop();
    return ring.length >= 3 ? ring : null;
  }

  function baseMap(el, onTileProblem) {
    const map = L.map(el, { zoomControl: true, attributionControl: true, keyboard: true, worldCopyJump: true })
      .setView(DEFAULT_CENTER, DEFAULT_ZOOM);
    map.attributionControl.setPrefix(false);
    const t = tileSettings();
    if (t.off) {
      el.classList.add("map-empty-grid");
      if (onTileProblem) onTileProblem("off");
      return map;
    }
    let errors = 0, loaded = 0;
    const layer = L.tileLayer(t.url, { maxZoom: 19, attribution: t.attribution, crossOrigin: false });
    layer.on("tileerror", function () {
      errors += 1;
      if (errors >= 2 && loaded === 0) { el.classList.add("map-empty-grid"); if (onTileProblem) onTileProblem("error"); }
    });
    layer.on("tileload", function () { loaded += 1; });
    layer.addTo(map);
    return map;
  }

  // Polygon drawer: click to add corners, finish on the first corner, by double click or finish(); drag corners to edit.
  function Drawer(el, opts) {
    this.opts = opts || {};
    this.map = baseMap(el, this.opts.onTileProblem);
    this.points = [];
    this.markers = [];
    this.drawing = false;
    this.closed = false;
    this.shape = L.polygon([], { color: "#30a14e", weight: 3, fillOpacity: 0.18 }).addTo(this.map);
    this.rubber = L.polyline([], { color: "#30a14e", weight: 2, dashArray: "6 6", interactive: false }).addTo(this.map);
    const self = this;
    this.map.on("click", function (e) { if (self.drawing) self.add(e.latlng); });
    this.map.on("dblclick", function (e) {
      if (!self.drawing) return;
      L.DomEvent.stop(e);
      self.finish();
    });
    this.map.on("mousemove", function (e) {
      if (self.drawing && self.points.length) self.rubber.setLatLngs([self.points[self.points.length - 1], e.latlng, self.points[0]]);
    });
  }
  Drawer.prototype.start = function () {
    this.clear(true);
    this.drawing = true;
    this.map.doubleClickZoom.disable();
    this.emit();
  };
  Drawer.prototype.add = function (latlng) {
    if (!this.drawing) return;
    const last = this.points[this.points.length - 1];
    if (last && this.map.latLngToLayerPoint(last).distanceTo(this.map.latLngToLayerPoint(latlng)) < 3) return;  // double click
    this.points.push(latlng);
    this.redraw();
    this.emit();
  };
  Drawer.prototype.addCentre = function () { this.add(this.map.getCenter()); };
  Drawer.prototype.undo = function () {
    if (!this.points.length) return;
    this.points.pop();
    if (this.closed && this.points.length < 3) { this.closed = false; this.drawing = true; this.map.doubleClickZoom.disable(); }
    this.redraw();
    this.emit();
  };
  Drawer.prototype.finish = function () {
    if (this.points.length < 3) return false;
    this.drawing = false;
    this.closed = true;
    this.map.doubleClickZoom.enable();
    this.rubber.setLatLngs([]);
    this.redraw();
    this.emit();
    return true;
  };
  Drawer.prototype.clear = function (silent) {
    this.points = [];
    this.drawing = false;
    this.closed = false;
    this.map.doubleClickZoom.enable();
    this.redraw();
    if (!silent) this.emit();
  };
  Drawer.prototype.load = function (geojson) {
    const ring = ringFrom(geojson);
    if (!ring) return false;
    this.points = ring;
    this.drawing = false;
    this.closed = true;
    this.redraw();
    this.map.fitBounds(L.latLngBounds(ring), { padding: [40, 40], maxZoom: 17 });
    this.emit(true);
    return true;
  };
  Drawer.prototype.redraw = function () {
    const self = this;
    this.markers.forEach(function (m) { m.remove(); });
    this.markers = [];
    this.shape.setLatLngs(this.points);
    this.shape.setStyle({ dashArray: this.closed ? null : "4 6", fillOpacity: this.closed ? 0.22 : 0.08 });
    if (!this.drawing) this.rubber.setLatLngs([]);
    this.points.forEach(function (p, i) {
      const icon = L.divIcon({ className: "vertex" + (i === 0 ? " first" : ""), iconSize: [14, 14] });
      const m = L.marker(p, { icon: icon, draggable: true, keyboard: false, title: "Corner " + (i + 1) }).addTo(self.map);
      m.on("drag", function (e) { self.points[i] = e.target.getLatLng(); self.shape.setLatLngs(self.points); });
      m.on("dragend", function () { self.emit(); });
      m.on("click", function (e) {
        L.DomEvent.stop(e);
        if (self.drawing && i === 0) self.finish();
      });
      self.markers.push(m);
    });
  };
  Drawer.prototype.state = function () {
    const n = this.points.length;
    return {
      drawing: this.drawing, closed: this.closed, count: n,
      area_ha: n >= 3 ? ringArea(this.points) / 10000 : null,
      geojson: this.closed && n >= 3 ? toGeoJSON(this.points) : null,
    };
  };
  Drawer.prototype.emit = function (fromLoad) {
    if (this.opts.onChange) this.opts.onChange(this.state(), !!fromLoad);
  };
  Drawer.prototype.invalidate = function () { this.map.invalidateSize(); };

  // Read-only map with one parcel outline.
  function Viewer(el, opts) {
    this.map = baseMap(el, opts && opts.onTileProblem);
    this.layer = null;
  }
  Viewer.prototype.show = function (geojson) {
    if (this.layer) this.layer.remove();
    const ring = ringFrom(geojson);
    this.map.invalidateSize();
    if (!ring) return;
    this.layer = L.polygon(ring, { color: "#30a14e", weight: 3, fillOpacity: 0.22 }).addTo(this.map);
    this.map.fitBounds(this.layer.getBounds(), { padding: [30, 30], maxZoom: 17 });
  };

  return { Drawer: Drawer, Viewer: Viewer, tileSettings: tileSettings, saveTileSettings: saveTileSettings,
           ringFrom: ringFrom, ringArea: ringArea, available: function () { return typeof window.L !== "undefined"; } };
})();
