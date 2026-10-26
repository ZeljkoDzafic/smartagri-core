"""The `parcel_features` data contract (schema_version 1): external parcel indicators with provenance.

A parcel feature provider (an offline producer that is not part of this package) computes, for one parcel and one
decision moment, indicators from satellite observations made BEFORE that moment and writes them as one JSON document.
This module defines the contract (`SCHEMA`), checks a document against it (`validate`, `parse`), and holds the rules
the quality layer q applies to what it carries. Standard library only; nothing here fetches data.

Design rules (docs/parcel-features.md):
- a document that breaks the contract, names another parcel or geometry, or uses an observation made after the decision
  moment is rejected as a whole, with the reasons; nothing is partly used;
- uncertainty is carried as intervals (stage), sets (crop) and sufficiency indicators, never as a point value that
  hides it, and no indicator turns into a reliability grade except through a rule in config/parcel_features.yaml;
- every rule here can only LOWER a grade (a minimum over caps), so the monotonicity of the sufficiency layer holds;
- the features live inside S, the satellite context, so the ablation that removes S removes them.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .. import config
from .types import NdviObservation, Observation, Origin, ParcelFeatures, Quality, Reliability

SCHEMA_VERSION = 1

# ---------------------------------------------------------------- the contract as a JSON Schema (draft 2020-12 subset)
_SHA256 = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_ISO = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?)?$"}
_ISO_OR_NULL = {"type": ["string", "null"], "pattern": _ISO["pattern"]}
_SHARE = {"type": "number", "minimum": 0, "maximum": 1}
_COUNT = {"type": "integer", "minimum": 0}
_BBCH = {"type": "integer", "minimum": 0, "maximum": 99}

SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "parcel_features v1",
    "description": "Indicators of one parcel at one decision moment, computed only from observations made before "
                   "that moment. Units: NDVI has no unit; shares are in [0, 1]; dates are ISO 8601 (a date alone "
                   "counts as the end of that day); durations are in days; distances in metres.",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "parcel_id", "geometry_sha256", "as_of", "computed_at", "source_obs_dates",
                 "producer"],
    "properties": {
        "schema_version": {"const": 1},
        "parcel_id": {"type": "string", "minLength": 1},
        "geometry_sha256": dict(_SHA256, description="sha256 of the normalised GeoJSON (see geometry_sha256())"),
        "as_of": dict(_ISO, description="the decision moment the document was computed for"),
        "computed_at": dict(_ISO, description="when the producer ran; not earlier than the latest source date"),
        "source_obs_dates": {"type": "array", "items": _ISO, "description": "every observation used (S2, S1)"},
        "producer": {
            "type": "object", "additionalProperties": False,
            "required": ["name", "version", "commit", "config_sha256", "run_manifest_sha256", "data_access"],
            "properties": {
                "name": {"type": "string", "minLength": 1},
                "version": {"type": "string", "minLength": 1},
                "commit": {"type": "string", "pattern": "^[0-9a-f]{7,40}$"},
                "config_sha256": _SHA256,
                "model_sha256": {"type": ["string", "null"], "pattern": "^[0-9a-f]{64}$"},
                "run_manifest_sha256": _SHA256,
                "data_access": {"enum": ["stac-cog", "cdse-odata", "cdse-statistical", "openeo", "other"]},
            },
        },
        "ndvi_observations": {
            "type": "array",
            "description": "one entry per observation, on the interior of the parcel; an entry replaces the "
                           "observation of the same obs_date in S.ndvi_series and adds the dates S lacks",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["obs_date", "median", "usable_share"],
                "properties": {
                    "obs_date": _ISO,
                    "median": {"type": "number", "minimum": -1, "maximum": 1},
                    "p10": {"type": ["number", "null"], "minimum": -1, "maximum": 1},
                    "p90": {"type": ["number", "null"], "minimum": -1, "maximum": 1},
                    "usable_share": dict(_SHARE, description="valid_px_ratio over the interior pixels"),
                    "n_px_total": _COUNT, "n_px_interior": _COUNT, "n_px_valid": _COUNT,
                    "interior_buffer_m": {"type": "number", "minimum": 0},
                    "mixed_px_share": dict(_SHARE, description="share of the parcel's pixels on its boundary"),
                    "cloud_px_share": _SHARE, "shadow_px_share": _SHARE,
                    "cloud_flag": {"type": "boolean"},
                    "temporal_outlier": {"type": "boolean"},
                    "mask_layers": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "stage_estimate": {
            "type": ["object", "null"], "additionalProperties": False, "required": ["method", "status"],
            "description": "growth stage as an interval, from observations before as_of only (causal)",
            "properties": {
                "method": {"type": "string", "minLength": 1},
                "status": {"enum": ["estimated", "pre_emergence", "insufficient_data"]},
                "bbch_min": _BBCH, "bbch_max": _BBCH,
                "greenup_date": _ISO_OR_NULL,
                "greenup_date_ci_days": {"type": ["array", "null"], "items": {"type": "integer"},
                                         "minItems": 2, "maxItems": 2},
                "last_clear_obs_date": _ISO,
                "n_clear_obs": _COUNT,
                "longest_gap_days": {"type": "number", "minimum": 0},
            },
        },
        "crop_plausibility": {
            "type": ["object", "null"], "additionalProperties": False,
            "required": ["season_year", "cutoff_doy", "p_maize", "prediction_set", "alpha", "coverage_guarantee",
                         "decision", "transfer_validated"],
            "properties": {
                "season_year": {"type": "integer", "minimum": 1990, "maximum": 2100},
                "cutoff_doy": {"type": "integer", "minimum": 1, "maximum": 366},
                "p_maize": _SHARE,
                "prediction_set": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
                "alpha": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
                "coverage_guarantee": {"type": "boolean"},
                "aoa_fraction": _SHARE,
                "n_px_interior": _COUNT,
                "decision": {"enum": ["agreement", "discrepancy", "uncertain", "insufficient_resolution",
                                      "out_of_applicability"]},
                "transfer_validated": {"type": "boolean"},
                "training_overlap_m": {"type": ["number", "null"], "minimum": 0},
            },
        },
        "events": {
            "type": ["object", "null"], "additionalProperties": False, "required": ["data_sufficiency"],
            "properties": {
                "data_sufficiency": {"enum": ["s2+s1", "s2", "s1", "insufficient"]},
                "bare_soil_now": {"type": ["boolean", "null"]},
                "bare_soil_since": _ISO_OR_NULL,
                "harvest_detected": {"type": ["boolean", "null"]},
                "harvest_date": _ISO_OR_NULL,
                "harvest_evidence": {"type": "string"},
                "confidence": dict(_SHARE, description="confidence of the reported bare-soil or harvest state"),
                "greenup_date": _ISO_OR_NULL,
            },
        },
    },
}


class ParcelFeaturesError(ValueError):
    """The document breaks the contract; `errors` lists every reason."""

    def __init__(self, errors: Sequence[str]):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


# ---------------------------------------------------------------- a small JSON Schema checker (the subset above)
def _type_ok(value: Any, name: str) -> bool:
    if name == "null":
        return value is None
    if name == "boolean":
        return isinstance(value, bool)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "string":
        return isinstance(value, str)
    if name == "array":
        return isinstance(value, list)
    if name == "object":
        return isinstance(value, dict)
    raise ValueError("unsupported type " + name)


def _check(schema: Dict[str, Any], value: Any, path: str, errors: List[str]) -> None:
    here = path or "document"
    if "const" in schema and value != schema["const"]:
        errors.append("%s: must be %r" % (here, schema["const"]))
        return
    if "enum" in schema and value not in schema["enum"]:
        errors.append("%s: %r is not one of %s" % (here, value, ", ".join(repr(x) for x in schema["enum"])))
        return
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_ok(value, n) for n in names):
            errors.append("%s: expected %s, got %s" % (here, "/".join(names), type(value).__name__))
            return
    if value is None:
        return
    if isinstance(value, str):
        if "pattern" in schema and not re.match(schema["pattern"], value):
            errors.append("%s: %r does not match the required format" % (here, value))
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append("%s: must not be empty" % here)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append("%s: %r is below %r" % (here, value, schema["minimum"]))
        if "maximum" in schema and value > schema["maximum"]:
            errors.append("%s: %r is above %r" % (here, value, schema["maximum"]))
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errors.append("%s: %r must be above %r" % (here, value, schema["exclusiveMinimum"]))
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append("%s: needs at least %d item(s)" % (here, schema["minItems"]))
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append("%s: at most %d item(s)" % (here, schema["maxItems"]))
        if schema.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            errors.append("%s: items must be unique" % here)
        if "items" in schema:
            for i, item in enumerate(value):
                _check(schema["items"], item, "%s[%d]" % (here, i), errors)
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append("%s: missing required field %r" % (here, key))
        for key, item in value.items():
            if key in props:
                _check(props[key], item, "%s.%s" % (here, key) if path else key, errors)
            elif schema.get("additionalProperties") is False:
                errors.append("%s: unknown field %r" % (here, key))


# ---------------------------------------------------------------- hashes
def _plain_dates(obj: Any) -> Any:
    """Dates as ISO strings, so a document read from YAML (where `2026-07-01` is a date) hashes like its JSON form."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): _plain_dates(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain_dates(v) for v in obj]
    return obj


def canonical_json(doc: Any) -> str:
    """Sorted keys, no spaces, ASCII: the text whose sha256 is the document hash."""
    return json.dumps(_plain_dates(doc), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def document_sha256(doc: Any) -> str:
    return hashlib.sha256(canonical_json(doc).encode("ascii")).hexdigest()


def _coord(v: float) -> float:
    v = round(float(v), 7)
    return 0.0 if v == 0 else v


def _ring(points: Sequence[Sequence[float]], exterior: bool) -> List[List[float]]:
    pts: List[Tuple[float, float]] = []
    for p in points:
        c = (_coord(p[0]), _coord(p[1]))
        if not pts or pts[-1] != c:
            pts.append(c)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    if len(pts) < 3:
        raise ValueError("a ring needs at least three distinct points")
    area2 = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
                for i in range(len(pts)))
    if (area2 > 0) != exterior:                 # exterior counter-clockwise, holes clockwise
        pts.reverse()
    start = pts.index(min(pts))
    pts = pts[start:] + pts[:start]
    return [[x, y] for x, y in pts + [pts[0]]]


def normalize_geometry(geometry: Dict[str, Any]) -> Dict[str, Any]:
    """GeoJSON Polygon / MultiPolygon (or a Feature holding one) in EPSG:4326 as a canonical Polygon or MultiPolygon:
    coordinates rounded to 7 decimals, closing point and repeated points removed, exterior ring counter-clockwise and
    holes clockwise, every ring starting at its smallest point, holes and polygons in sorted order."""
    g = geometry.get("geometry") if geometry.get("type") == "Feature" else geometry
    if not isinstance(g, dict) or g.get("type") not in ("Polygon", "MultiPolygon"):
        raise ValueError("geometry must be a GeoJSON Polygon or MultiPolygon")
    polys = [g["coordinates"]] if g["type"] == "Polygon" else list(g["coordinates"])
    out = []
    for poly in polys:
        rings = [_ring(poly[0], True)] + sorted(_ring(r, False) for r in poly[1:])
        out.append(rings)
    out.sort()
    if len(out) == 1:
        return {"type": "Polygon", "coordinates": out[0]}
    return {"type": "MultiPolygon", "coordinates": out}


def geometry_sha256(geometry: Dict[str, Any]) -> str:
    text = json.dumps(normalize_geometry(geometry), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("ascii")).hexdigest()


# ---------------------------------------------------------------- time: only what was observed before the decision
def _parse_iso(value: str) -> Tuple[datetime, bool]:
    """(wall-clock datetime, was it a date alone). Offsets are dropped: the decision moment and the observations
    are compared as wall-clock values in the zone the scenario or parcel uses."""
    text = value.strip().replace(" ", "T", 1)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if len(text) == 10:
        return datetime.combine(date.fromisoformat(text), time(0, 0)), True
    return datetime.fromisoformat(text).replace(tzinfo=None), False


def moment(value: Any) -> datetime:
    """The moment an observation date stands for. A date alone gives no time of day, so it counts as the END of that
    day: the latest it can have been observed. An observation dated on the decision day is therefore usable only when
    it carries a time at or before the decision moment."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime.combine(value, time(23, 59, 59))
    d, date_only = _parse_iso(str(value))
    return datetime.combine(d.date(), time(23, 59, 59)) if date_only else d


def as_of_moment(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    return _parse_iso(str(value))[0]


def _day(value: str) -> date:
    return _parse_iso(value)[0].date()


# ---------------------------------------------------------------- validation
def validate(doc: Any, as_of: Any = None, parcel_id: Optional[str] = None,
             geometry: Optional[Dict[str, Any]] = None) -> List[str]:
    """Every reason the document cannot be used; an empty list means it can.

    as_of: the decision moment of the context; the document must have been computed for the same day, at or before
    that moment, and no observation, estimate date or marker date may lie after the earlier of the two.
    parcel_id / geometry: when given, the document must name that parcel and that geometry (by hash)."""
    errors: List[str] = []
    if not isinstance(doc, dict):
        return ["document: expected an object"]
    doc = _plain_dates(doc)
    _check(SCHEMA, doc, "", errors)
    if errors:                                   # the semantic checks need a well-formed document
        return errors
    try:
        doc_as_of = as_of_moment(doc["as_of"])
        limit = doc_as_of
        if as_of is not None:
            ctx_as_of = as_of_moment(as_of)
            if doc_as_of > ctx_as_of or doc_as_of.date() != ctx_as_of.date():
                errors.append("as_of: the document was computed for %s, not for the decision moment %s (it may "
                               "not be later, and must be from the same day)" % (doc["as_of"], ctx_as_of.isoformat()))
            limit = min(limit, ctx_as_of)
        if parcel_id is not None and doc["parcel_id"] != parcel_id:
            errors.append("parcel_id: %r is not the parcel %r" % (doc["parcel_id"], parcel_id))
        if geometry is not None:
            try:
                expected = geometry_sha256(geometry)
            except (ValueError, KeyError, TypeError, IndexError) as exc:
                errors.append("geometry: cannot be hashed (%s)" % exc)
            else:
                if doc["geometry_sha256"] != expected:
                    errors.append("geometry_sha256: does not match the parcel geometry")

        def after(label: str, value: Optional[str]) -> None:
            if value is not None and moment(value) > limit:
                errors.append("%s: %s is after the decision moment (%s)" % (label, value, limit.isoformat()))

        for i, v in enumerate(doc["source_obs_dates"]):
            after("source_obs_dates[%d]" % i, v)
        if doc["source_obs_dates"]:
            latest = max(_day(v) for v in doc["source_obs_dates"])
            if _day(doc["computed_at"]) < latest:
                errors.append("computed_at: earlier than the latest source observation (%s)" % latest.isoformat())
        sources = {_day(v) for v in doc["source_obs_dates"]}
        seen = set()
        for i, o in enumerate(doc.get("ndvi_observations") or []):
            p = "ndvi_observations[%d]" % i
            after(p + ".obs_date", o["obs_date"])
            d = _day(o["obs_date"])
            if d in seen:
                errors.append("%s.obs_date: %s appears twice" % (p, d.isoformat()))
            seen.add(d)
            if d not in sources:
                errors.append("%s.obs_date: %s is not listed in source_obs_dates" % (p, d.isoformat()))
            tot, inner, valid = o.get("n_px_total"), o.get("n_px_interior"), o.get("n_px_valid")
            if tot is not None and inner is not None and inner > tot:
                errors.append("%s: n_px_interior exceeds n_px_total" % p)
            if inner is not None and valid is not None and valid > inner:
                errors.append("%s: n_px_valid exceeds n_px_interior" % p)
            if o.get("p10") is not None and o.get("p90") is not None and o["p10"] > o["p90"]:
                errors.append("%s: p10 is above p90" % p)
        se = doc.get("stage_estimate")
        if se:
            lo, hi = se.get("bbch_min"), se.get("bbch_max")
            if se["status"] in ("estimated", "pre_emergence") and (lo is None or hi is None):
                errors.append("stage_estimate: status %r needs bbch_min and bbch_max" % se["status"])
            if lo is not None and hi is not None and lo > hi:
                errors.append("stage_estimate: bbch_min is above bbch_max")
            if (lo is None) != (hi is None):
                errors.append("stage_estimate: bbch_min and bbch_max come together")
            if se["status"] == "estimated" and se.get("last_clear_obs_date") is None:
                errors.append("stage_estimate: status 'estimated' needs last_clear_obs_date")
            after("stage_estimate.last_clear_obs_date", se.get("last_clear_obs_date"))
            after("stage_estimate.greenup_date", se.get("greenup_date"))
            if se.get("last_clear_obs_date") is not None and _day(se["last_clear_obs_date"]) not in sources:
                errors.append("stage_estimate.last_clear_obs_date: not listed in source_obs_dates")
            ci = se.get("greenup_date_ci_days")
            if ci and ci[0] > ci[1]:
                errors.append("stage_estimate.greenup_date_ci_days: lower bound above upper bound")
        cp = doc.get("crop_plausibility")
        if cp:
            try:
                cutoff = date(cp["season_year"], 1, 1) + timedelta(days=cp["cutoff_doy"] - 1)
            except (ValueError, OverflowError):
                errors.append("crop_plausibility: season_year and cutoff_doy do not give a date")
            else:
                if moment(cutoff) > limit:
                    errors.append("crop_plausibility: the feature window ends on %s, after the decision moment"
                                  % cutoff.isoformat())
        ev = doc.get("events")
        if ev:
            for key in ("bare_soil_since", "harvest_date", "greenup_date"):
                after("events." + key, ev.get(key))
            if ev.get("harvest_detected") and ev.get("confidence") is None:
                errors.append("events: harvest_detected needs confidence")
    except (ValueError, KeyError, TypeError) as exc:    # a malformed date the patterns let through (e.g. month 13)
        errors.append("document: %s" % exc)
    return errors


def parse(doc: Any, as_of: Any = None, parcel_id: Optional[str] = None,
          geometry: Optional[Dict[str, Any]] = None) -> ParcelFeatures:
    """The validated document as a ParcelFeatures; raises ParcelFeaturesError listing every reason otherwise."""
    errors = validate(doc, as_of, parcel_id, geometry)
    if errors:
        raise ParcelFeaturesError(errors)
    d = _plain_dates(copy.deepcopy(doc))
    return ParcelFeatures(
        schema_version=d["schema_version"], parcel_id=d["parcel_id"], geometry_sha256=d["geometry_sha256"],
        as_of=d["as_of"], computed_at=d["computed_at"], source_obs_dates=list(d["source_obs_dates"]),
        producer=d["producer"],
        ndvi_observations=[NdviObservation(**o) for o in d.get("ndvi_observations") or []],
        stage_estimate=d.get("stage_estimate"), crop_plausibility=d.get("crop_plausibility"),
        events=d.get("events"), document_sha256=document_sha256(d))


def merge_ndvi(series: List[NdviObservation], pf: Optional[ParcelFeatures]) -> List[NdviObservation]:
    """S.ndvi_series with the producer's observations: one of the same date replaces the series entry (it was made on
    the interior of the parcel and carries the mask metadata), a date the series lacks is added."""
    if pf is None or not pf.ndvi_observations:
        return list(series)
    by_day = {str(o.obs_date)[:10]: o for o in series}
    for o in pf.ndvi_observations:
        by_day[str(o.obs_date)[:10]] = o
    return [by_day[k] for k in sorted(by_day)]


def causality_errors(pf: ParcelFeatures, as_of: Any) -> List[str]:
    """The contract checks that depend on the decision moment, for a ParcelFeatures that was not parsed against it."""
    return validate(_as_document(pf), as_of=as_of)


def _as_document(pf: ParcelFeatures) -> Dict[str, Any]:
    out: Dict[str, Any] = {"schema_version": pf.schema_version, "parcel_id": pf.parcel_id,
                           "geometry_sha256": pf.geometry_sha256, "as_of": pf.as_of, "computed_at": pf.computed_at,
                           "source_obs_dates": list(pf.source_obs_dates), "producer": pf.producer}
    if pf.ndvi_observations:
        out["ndvi_observations"] = [{k: v for k, v in o.to_dict().items() if v is not None}
                                    for o in pf.ndvi_observations]
    for key in ("stage_estimate", "crop_plausibility", "events"):
        if getattr(pf, key) is not None:
            out[key] = getattr(pf, key)
    return out


def usable(ctx: Any) -> Tuple[Optional[ParcelFeatures], List[str]]:
    """The features of a context, or (None, reasons) when they cannot be used at its decision moment. A context built
    from a scenario or a profile was checked when it was built; this guards one assembled by hand."""
    pf = ctx.S.parcel_features
    if pf is None:
        return None, []
    if ctx.as_of is None:
        return None, ["as_of: the context has no decision moment"]
    errors = causality_errors(pf, ctx.as_of)
    return (None, errors) if errors else (pf, [])


# ---------------------------------------------------------------- the rules of q (only ever lower a grade)
def settings() -> Dict[str, Any]:
    return config.load("parcel_features")


_LEVELS = {"high": Reliability.HIGH, "medium": Reliability.MEDIUM, "low": Reliability.LOW}


def ndvi_detail(o: NdviObservation) -> Optional[Dict[str, Any]]:
    """The quality fields an observation carries, or None when it carries none (it is then graded as before)."""
    d = {k: getattr(o, k) for k in ("cloud_flag", "cloud_px_share", "shadow_px_share", "interior_buffer_m",
                                    "n_px_total", "n_px_interior", "n_px_valid", "mixed_px_share", "mask_layers")
         if getattr(o, k) is not None}
    return d or None


def ndvi_caps(detail: Optional[Dict[str, Any]]) -> List[Tuple[Reliability, str]]:
    """(highest grade allowed, reason) for every threshold the observation's quality fields cross."""
    cfg = settings()["ndvi_quality"]
    if not detail or not cfg["enabled"]:
        return []
    caps: List[Tuple[Reliability, str]] = []
    if detail.get("cloud_flag"):
        caps.append((_LEVELS[cfg["cloud_flag_caps_at"]], "cloud or shadow on the parcel (cloud_flag)"))
    if detail.get("cloud_px_share") is not None or detail.get("shadow_px_share") is not None:
        masked = (detail.get("cloud_px_share") or 0.0) + (detail.get("shadow_px_share") or 0.0)
        if masked > cfg["max_masked_share_for_medium"]:
            caps.append((Reliability.LOW, "cloud and shadow share %.2f > %.2f" % (masked, cfg["max_masked_share_for_medium"])))
        elif masked > cfg["max_masked_share_for_high"]:
            caps.append((Reliability.MEDIUM, "cloud and shadow share %.2f > %.2f" % (masked, cfg["max_masked_share_for_high"])))
    if detail.get("mixed_px_share") is not None:
        m = detail["mixed_px_share"]
        if m > cfg["max_mixed_share_for_medium"]:
            caps.append((Reliability.LOW, "mixed-pixel share %.2f > %.2f" % (m, cfg["max_mixed_share_for_medium"])))
        elif m > cfg["max_mixed_share_for_high"]:
            caps.append((Reliability.MEDIUM, "mixed-pixel share %.2f > %.2f" % (m, cfg["max_mixed_share_for_high"])))
    n = detail.get("n_px_valid") if detail.get("n_px_valid") is not None else detail.get("n_px_interior")
    if n is not None:
        if n < cfg["min_interior_px_for_medium"]:
            caps.append((Reliability.LOW, "%d interior pixels < %d" % (n, cfg["min_interior_px_for_medium"])))
        elif n < cfg["min_interior_px_for_high"]:
            caps.append((Reliability.MEDIUM, "%d interior pixels < %d" % (n, cfg["min_interior_px_for_high"])))
    return caps


def stage_status(pf: Optional[ParcelFeatures], as_of: Any) -> str:
    """Whether the satellite stage estimate of the features takes part in the stage comparison: 'compared', or why not
    ('off', 'absent', 'not_estimated' for a status other than 'estimated', 'stale' when older than the configured
    days)."""
    cfg = settings()["stage_conflict"]
    if not cfg["enabled"]:
        return "off"
    if pf is None or not pf.stage_estimate:
        return "absent"
    se = pf.stage_estimate
    if se.get("status") != "estimated" or se.get("bbch_min") is None:
        return "not_estimated"
    if (as_of_moment(as_of).date() - _day(se["last_clear_obs_date"])).days > cfg["max_estimate_age_days"]:
        return "stale"
    return "compared"


def stage_conflict(chosen: Observation, pf: Optional[ParcelFeatures], as_of: Any) -> Optional[Dict[str, Any]]:
    """Two stage sources that disagree: the stage in use (reported by the farmer or derived from the sowing date)
    lies further than the tolerance outside the satellite interval. None when they agree, when the rule is off, when
    there is no usable satellite estimate (status other than 'estimated', or older than the configured days) or no
    stage in use. The conflict is returned as evidence; the cap is applied by `apply_conflicts`."""
    cfg = settings()["stage_conflict"]
    if chosen.value is None or stage_status(pf, as_of) != "compared":
        return None
    se = pf.stage_estimate
    age = (as_of_moment(as_of).date() - _day(se["last_clear_obs_date"])).days
    lo, hi, v, tol = se["bbch_min"], se["bbch_max"], float(chosen.value), cfg["tolerance_bbch"]
    distance = max(lo - v, v - hi, 0.0)
    if distance <= tol:
        return None
    return {"rule": "stage_conflict", "input": "phenophase", "cap": cfg["cap_reliability_at"],
            "in_use": {"bbch": chosen.value, "origin": chosen.origin.value, "age_days": chosen.age_days,
                       "source_ref": chosen.source_ref},
            "satellite": {"bbch_min": lo, "bbch_max": hi, "method": se.get("method"), "age_days": age,
                          "last_clear_obs_date": se.get("last_clear_obs_date"),
                          "n_clear_obs": se.get("n_clear_obs")},
            "tolerance_bbch": tol, "distance_bbch": round(distance, 1)}


def field_state(pf: Optional[ParcelFeatures], as_of: Any) -> Optional[Observation]:
    """The bare-soil / harvest markers as an input `field_state` (crop_present | bare_soil | harvested), graded from
    the producer's confidence by config. None unless the markers are enabled and carry a usable state."""
    cfg = settings()["field_markers"]
    if not cfg["enabled"] or pf is None or not pf.events:
        return None
    ev = pf.events
    if ev.get("data_sufficiency") == "insufficient":
        return None
    if ev.get("harvest_detected") and ev.get("harvest_date"):
        state = "harvested"
    elif ev.get("bare_soil_now") is True:
        state = "bare_soil"
    elif ev.get("bare_soil_now") is False:
        state = "crop_present"
    else:
        return None
    conf = ev.get("confidence") or 0.0
    level = Reliability(cfg["default"])
    for g in cfg["grades"]:
        if conf >= g["min_confidence"] and ev["data_sufficiency"] in g["data_sufficiency"]:
            level = Reliability(g["reliability"])
            break
    when = ev.get("harvest_date") if state == "harvested" else ev.get("bare_soil_since")
    age = float((as_of_moment(as_of).date() - _day(when)).days) if when else None
    return Observation(state, Origin.MODELED, age, None, None, "events:" + state,
                       {"state_reliability": level.value, "confidence": conf,
                        "data_sufficiency": ev["data_sufficiency"], "evidence": ev.get("harvest_evidence")})


def marker_conflict(state: Optional[Observation], chosen: Observation, advice_type: str) -> Optional[Dict[str, Any]]:
    """A field state that contradicts the stage in use: bare soil with a stage at or above the configured BBCH, or a
    harvest when the advice assumes a standing crop. Only a state graded at or above the configured level counts."""
    cfg = settings()["field_markers"]
    if state is None or chosen.value is None:
        return None
    if Reliability(state.detail["state_reliability"]).rank < Reliability(cfg["min_reliability_for_conflict"]).rank:
        return None
    if state.value == "bare_soil" and float(chosen.value) >= cfg["bare_soil_conflict_min_bbch"]:
        why = "bare soil now, stage in use BBCH %s" % chosen.value
    elif state.value == "harvested" and advice_type in cfg["harvest_conflicting_advice"]:
        why = "harvest detected, advice type %s" % advice_type
    else:
        return None
    return {"rule": "field_markers", "input": "phenophase", "cap": cfg["cap_reliability_at"], "why": why,
            "field_state": state.value, "confidence": state.detail["confidence"],
            "in_use": {"bbch": chosen.value, "origin": chosen.origin.value, "age_days": chosen.age_days}}


def crop_identity(declared_crop: str, pf: Optional[ParcelFeatures]) -> Optional[Observation]:
    """The declared crop as an input `crop_identity`, checked against the producer's plausibility result. A
    discrepancy counts only when the producer says the classifier was validated for this season and window; every
    other decision (uncertain, insufficient resolution, out of applicability, agreement) is carried and changes
    nothing. None unless the check is enabled and the document carries it."""
    cfg = settings()["crop_plausibility"]
    if not cfg["enabled"] or pf is None or not pf.crop_plausibility:
        return None
    cp = pf.crop_plausibility
    detail: Dict[str, Any] = {"crop_plausibility": {k: cp.get(k) for k in (
        "decision", "p_maize", "prediction_set", "alpha", "coverage_guarantee", "transfer_validated", "aoa_fraction",
        "training_overlap_m", "season_year", "cutoff_doy")}}
    if cp["decision"] == "discrepancy" and cp["transfer_validated"]:
        detail["conflicts"] = [{"rule": "crop_plausibility", "input": "crop_identity", "cap": cfg["cap_reliability_at"],
                                "declared": declared_crop, "prediction_set": cp["prediction_set"],
                                "p_maize": cp["p_maize"]}]
    return Observation(declared_crop, Origin.USER_REPORTED, None, None, None, "parcel_features:crop_plausibility", detail)


def cap(q: Quality, level: Reliability, reason: str, detail: Optional[Dict[str, Any]] = None) -> Quality:
    """q with its reliability at most `level` (never raised), the reason appended to the basis, detail merged."""
    merged = dict(q.detail or {}, **(detail or {})) or None
    if q.reliability.rank <= level.rank:
        return Quality(q.input, q.origin, q.age_days, q.coverage, q.reliability, q.basis, q.source_ref, merged)
    return Quality(q.input, q.origin, q.age_days, q.coverage, level, q.basis + "; capped to %s: %s" % (level.value, reason),
                   q.source_ref, merged)


def apply_detail(q: Quality, o: Observation) -> Quality:
    """The caps an observation's detail calls for: NDVI quality fields, and input conflicts (list `conflicts`)."""
    detail = o.detail
    if not detail:
        return q
    if q.input.startswith("ndvi"):
        caps = ndvi_caps(detail)
        for level, reason in caps:
            q = cap(q, level, reason)
        extra = dict(detail, capped_by=[r for _, r in caps]) if caps else dict(detail)
        return cap(q, Reliability.HIGH, "", extra)          # HIGH: nothing lowered here, only the detail is recorded
    q = cap(q, Reliability.HIGH, "", dict(detail))              # nothing lowered here, the detail is recorded
    for c in detail.get("conflicts") or []:
        q = cap(q, _LEVELS[c["cap"]], "input conflict (%s)" % c["rule"])
    return q


FEATURE_INPUTS = ("crop_identity", "field_state")     # inputs that exist only when their switch in config is on


def grade_feature_input(name: str, o: Observation) -> Quality:
    """Grade of crop_identity (the declared crop: user-reported, high; a validated discrepancy then caps it) and of
    field_state (the producer's confidence, by the grades in config/parcel_features.yaml)."""
    if name == "crop_identity":
        return Quality(name, o.origin, o.age_days, None, Reliability.HIGH, "declared by the user", o.source_ref)
    level = Reliability((o.detail or {}).get("state_reliability", "low"))
    return Quality(name, o.origin, o.age_days, None, level,
                   "producer confidence %.2f, data %s" % ((o.detail or {}).get("confidence", 0.0),
                                                          (o.detail or {}).get("data_sufficiency")), o.source_ref)


def input_conflicts(quality: Dict[str, Quality]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for q in quality.values():
        out.extend((q.detail or {}).get("conflicts") or [])
    return out


# ---------------------------------------------------------------- provenance of a run
def provenance(ctx: Any, quality: Dict[str, Quality]) -> Optional[Dict[str, Any]]:
    """What a run recorded about the parcel features: which document (hash, producer), what was compared, what was
    applied to the grading, and the parts that are only recorded because their switch in config is off."""
    pf = ctx.S.parcel_features
    if pf is None:
        return None
    _, rejected = usable(ctx)
    if rejected:                                     # a context assembled by hand with features that cannot be used
        return {"document_sha256": pf.document_sha256, "producer": dict(pf.producer), "rejected": rejected}
    cfg = settings()
    conflicts = input_conflicts(quality)
    block: Dict[str, Any] = {
        "schema_version": pf.schema_version, "document_sha256": pf.document_sha256, "parcel_id": pf.parcel_id,
        "geometry_sha256": pf.geometry_sha256, "as_of": pf.as_of, "computed_at": pf.computed_at,
        "producer": dict(pf.producer), "n_source_obs": len(pf.source_obs_dates),
        "applied": {
            "ndvi_quality": any((q.detail or {}).get("capped_by") for q in quality.values()),
            "stage_conflict": any(c["rule"] == "stage_conflict" for c in conflicts),
            "crop_plausibility": any(c["rule"] == "crop_plausibility" for c in conflicts),
            "field_markers": any(c["rule"] == "field_markers" for c in conflicts)},
        "input_conflicts": conflicts,
    }
    if pf.stage_estimate:
        block["stage_estimate"] = {k: pf.stage_estimate.get(k) for k in (
            "method", "status", "bbch_min", "bbch_max", "last_clear_obs_date", "n_clear_obs", "longest_gap_days")}
        block["stage_estimate"]["comparison"] = stage_status(pf, ctx.as_of)
    for key, rule in (("crop_plausibility", "crop_plausibility"), ("events", "field_markers")):
        value = getattr(pf, key)
        if value is not None:
            block[key] = {"enabled": bool(cfg[rule]["enabled"]), "recorded": value}
    return block
