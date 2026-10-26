"""Read-only views of the research API: weather and NDVI series of a parcel, the FAO-56 daily water balance, the
evaluation overview and the provenance export of one answer.

Nothing here fetches data, changes a stored record or runs the decision model:
- the series are the rows the stored parcel profile already holds (pipeline/profile.py);
- the water balance takes Kc and ETc = Kc x ET0 from the core tools (core/tools/etc.py) and the stage from the core
  phenology tool; only the daily bookkeeping of the root-zone deficit is done here, and it is labelled as an
  illustration (the advice itself uses the core irrigation tools, not this series);
- the evaluation overview passes evalkit's own measures through (evalkit.report, evalkit.tables, evalkit.lock,
  evalkit.guard) without computing any number differently; the test scenarios are never run or shown.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from .. import config
from ..core.quality import annotate_quality, observe_all
from ..core.tools import crop_evapotranspiration, estimate_bbch
from ..core.tools.etc import SOURCE as ETC_SOURCE
from ..core.tools.ndvi_stats import MIN_SHARE_FOR_TREND
from ..core.types import to_date
from ..pipeline.profile import context_from
from ..providers import satellite, weather
from ..store import Store, now_iso

NDVI_QUALITY_FIELDS = ("cloud_flag", "cloud_px_share", "shadow_px_share", "interior_buffer_m", "n_px_interior",
                       "mixed_px_share", "temporal_outlier")
SCL_MASK = "Sentinel-2 scene classification (SCL) per pixel: no data, saturated, cloud shadow, cloud (medium, high), " \
           "cirrus and snow are excluded"
BALANCE_FORMULA = "Dr[i] = min(TAW, max(0, Dr[i-1] + ETc[i] - P[i])); Dr[0] = 0 (assumption); TAW = AWC x Zr"
BALANCE_SOURCE = "Allen et al. (1998), FAO-56, ch. 8, eq. 85 (simplified: rain counted in full, no runoff, " \
                 "no capillary rise)"


def _now() -> datetime:
    return datetime.now().astimezone()


def _age_hours(stamp: Optional[str], now: Optional[datetime] = None) -> Optional[float]:
    if not stamp:
        return None
    try:
        then = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    now = now or _now()
    if then.tzinfo is None:
        then = then.replace(tzinfo=now.tzinfo)
    return round((now - then).total_seconds() / 3600.0, 1)


# ---------------------------------------------------------------- weather and NDVI (decision context C, quality q)
def series(parcel: Dict[str, Any], profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The weather rows and the NDVI observations of the latest stored profile, with their source and age.

    No profile, or a provider that failed, gives status "missing" and the stored message; no value is filled in."""
    out: Dict[str, Any] = {"parcel_id": parcel["id"], "profile_id": None, "as_of": None, "generated_at": now_iso()}
    if not profile:
        out["weather"] = {"status": "missing", "source": weather.SOURCE, "message": "no_profile", "rows": []}
        out["ndvi"] = {"status": "missing", "source": satellite.SOURCE, "message": "no_profile", "rows": []}
        return out
    out.update(profile_id=profile["id"], as_of=profile["as_of"])
    w = profile.get("weather") or {}
    summary = w.get("summary") or {}
    out["weather"] = {
        "status": w.get("status") or "missing", "message": w.get("message") or "", "source": w.get("source") or weather.SOURCE,
        "endpoint": w.get("endpoint"), "fetched_at": w.get("fetched_at"), "age_hours": _age_hours(w.get("fetched_at")),
        "forecast_issued_at": summary.get("forecast_issued_at"), "horizon_days": summary.get("horizon_days"),
        "retrospective_constructed": bool(w.get("retrospective_constructed")), "request_hash": w.get("request_hash"),
        "variables": {"tmax_c": "temperature_2m_max", "tmin_c": "temperature_2m_min", "precip_mm": "precipitation_sum",
                      "et0_mm": "et0_fao_evapotranspiration"},
        "rows": [{k: r.get(k) for k in ("date", "tmin_c", "tmax_c", "precip_mm", "et0_mm", "is_forecast")}
                 for r in w.get("daily") or []],
    }
    s = profile.get("satellite") or {}
    rows = []
    # The profile's series with the observations of the parcel features, if any (same merge as the decision context).
    for o in context_from(parcel, profile).S.ndvi_series:
        share = o.usable_share
        rows.append({"obs_date": o.obs_date, "median": o.median, "p10": o.p10, "p90": o.p90, "valid_px_ratio": share,
                     # the core NDVI tool uses an observation for the 14-day trend only at this share (ndvi_stats.py)
                     "meets_trend_share": None if share is None else share >= MIN_SHARE_FOR_TREND,
                     # mask metadata from the parcel feature provider; None = not reported for this observation
                     **{k: getattr(o, k) for k in NDVI_QUALITY_FIELDS}})
    latest = rows[-1]["obs_date"] if rows else None
    as_of = to_date(profile["as_of"])
    out["ndvi"] = {
        "status": s.get("status") or "missing", "message": s.get("message") or "", "source": s.get("source") or satellite.SOURCE,
        "fetched_at": s.get("fetched_at"), "age_hours": _age_hours(s.get("fetched_at")), "request_hash": s.get("request_hash"),
        "latest_obs_date": latest,
        "latest_age_days": (as_of - to_date(latest)).days if latest and as_of else None,
        "lookback_days": satellite.LOOKBACK_DAYS, "cloud_mask": SCL_MASK,
        "cloud_flag": rows[-1]["cloud_flag"] if rows else None,
        "cloud_flag_note": "stored per observation when the parcel feature provider reports it (cloud_flag, cloud and "
                           "shadow shares, interior pixels); the Statistical API path does not report it, its cloudy "
                           "pixels are masked per pixel and counted in valid_px_ratio",
        "trend_min_share": MIN_SHARE_FOR_TREND, "summary": s.get("summary"), "rows": rows,
    }
    stored = profile.get("parcel_features")
    if stored:                                     # present only when a parcel feature provider is configured
        doc = stored.get("document") or {}
        out["parcel_features"] = {"status": stored.get("status"), "message": stored.get("message") or "",
                                  "source": stored.get("source"), "document_sha256": stored.get("document_sha256"),
                                  "producer": stored.get("producer"), "stage_estimate": doc.get("stage_estimate")}
    return out


# ---------------------------------------------------------------- FAO-56 water balance (computed in code)
def _root_depth(bbch: Optional[int]) -> Optional[float]:
    """Effective root depth by stage from config/rules.yaml (the same table the core decision uses)."""
    if bbch is None:
        return None
    for row in config.load("rules")["irrigation"]["root_depth_m_by_bbch"]:
        if bbch <= row["bbch_max"]:
            return float(row["depth"])
    return None


def water_balance(parcel: Dict[str, Any], profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Daily ET0, Kc, ETc, rain and root-zone deficit over the stored weather window of the parcel.

    Kc and ETc come from core.tools.crop_evapotranspiration for each day; the stage of each day from
    core.tools.estimate_bbch (days since sowing). Without a sowing date the stage of the decision date (q layer) is
    used for every day, and without any stage Kc, ETc and the deficit stay empty. The deficit starts at 0 on the first
    day (an assumption: root zone full); it is an illustration of the inputs, not an input of the advice."""
    out: Dict[str, Any] = {"parcel_id": parcel["id"], "status": "missing", "message": "", "computed_in": "code",
                           "method": "FAO-56", "formula_etc": "ETc = Kc * ET0", "source_etc": ETC_SOURCE,
                           "formula_deficit": BALANCE_FORMULA, "source_deficit": BALANCE_SOURCE,
                           "used_by_advice": False, "assumptions": [], "rows": [], "totals": None, "taw_mm": None}
    if not profile:
        out["message"] = "no_profile"
        return out
    w = profile.get("weather") or {}
    days = w.get("daily") or []
    out.update(profile_id=profile["id"], as_of=profile["as_of"], weather_source=w.get("source"),
               weather_fetched_at=w.get("fetched_at"),
               weather_retrospective_constructed=bool(w.get("retrospective_constructed")))
    if w.get("status") != "ok" or not days:
        out["message"] = w.get("message") or "no_weather"
        return out
    ctx = context_from(parcel, profile)
    obs, q = observe_all(ctx), annotate_quality(ctx)
    agronomic = parcel.get("agronomic") or {}
    sowing = to_date(agronomic.get("sowing_date"))
    stage_now = obs["phenophase"].value
    awc = obs["soil_awc"].value
    out["inputs"] = {
        "sowing_date": agronomic.get("sowing_date"), "hybrid_fao": agronomic.get("hybrid_fao"),
        "stage_on_decision_date": stage_now, "stage_reliability": q["phenophase"].reliability.value,
        "soil_awc_mm_m": awc, "soil_awc_origin": obs["soil_awc"].origin.value if awc is not None else None,
        "soil_awc_reliability": q["soil_awc"].reliability.value,
    }
    if sowing is not None:
        stage_method = "days_since_sowing"
        out["assumptions"].append("stage_from_days_since_sowing")
    elif stage_now is not None:
        stage_method = "decision_date_stage"
        out["assumptions"].append("stage_constant")
    else:
        stage_method = None
        out["assumptions"].append("no_stage")
    out["assumptions"].append("deficit_starts_at_zero")
    if awc is None:
        out["assumptions"].append("no_taw_cap")
    else:
        out["assumptions"].append("taw_cap")                # TAW = AWC (soil texture or reported) x Zr (stage)
    out["stage_method"] = stage_method

    rows: List[Dict[str, Any]] = []
    dr: Optional[float] = 0.0
    for r in days:
        day = to_date(r["date"])
        bbch: Optional[int] = None
        if stage_method == "days_since_sowing" and day is not None and day >= sowing:
            est = estimate_bbch(None, (day - sowing).days, agronomic.get("hybrid_fao")).output
            bbch = est["bbch"] if est else None
        elif stage_method == "decision_date_stage":
            bbch = int(stage_now)
        et0, rain = r.get("et0_mm"), r.get("precip_mm")
        tool = crop_evapotranspiration(bbch, et0)
        kc = tool.output["kc"] if tool.output else None
        etc = tool.output["etc_mm"] if tool.output else None
        zr = _root_depth(bbch)
        taw = round(awc * zr, 1) if awc is not None and zr is not None else None
        if day is not None and sowing is not None and day < sowing:
            deficit = None                                  # before sowing: no crop, no balance
        elif dr is None or etc is None or rain is None:
            dr = None                                       # a gap breaks the chain; nothing is carried over
            deficit = None
        else:
            dr = max(0.0, dr + etc - rain)
            if taw is not None:
                dr = min(taw, dr)
            deficit = round(dr, 1)
        rows.append({"date": r["date"], "is_forecast": bool(r.get("is_forecast")), "et0_mm": et0, "bbch": bbch,
                     "kc": kc, "etc_mm": etc, "rain_mm": rain, "taw_mm": taw, "deficit_mm": deficit})
    out["rows"] = rows
    observed = [r for r in rows if not r["is_forecast"]]

    def total(key: str, part: List[Dict[str, Any]]) -> Optional[float]:
        xs = [r[key] for r in part if r[key] is not None]
        return round(sum(xs), 1) if xs and len(xs) == len(part) else None
    out["totals"] = {"observed_days": len(observed), "forecast_days": len(rows) - len(observed),
                     "et0_observed_mm": total("et0_mm", observed), "etc_observed_mm": total("etc_mm", observed),
                     "rain_observed_mm": total("rain_mm", observed)}
    tail = [r for r in observed if r["deficit_mm"] is not None]
    out["deficit_last_observed"] = {"date": tail[-1]["date"], "deficit_mm": tail[-1]["deficit_mm"]} if tail else None
    out["taw_mm"] = next((r["taw_mm"] for r in reversed(observed) if r["taw_mm"] is not None), None)
    out["status"] = "ok" if any(r["etc_mm"] is not None for r in rows) else "partial"
    if out["status"] == "partial":
        out["message"] = "no_stage"
    return out


# ---------------------------------------------------------------- evaluation overview (read-only, from evalkit)
SET_LABELS = {"dev": "development set", "test": "test set"}


def _strip(measures: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in measures.items() if not k.startswith("_")}


def _lock_view() -> Dict[str, Any]:
    from ..evalkit import lock
    path = lock.default_lock_path()
    if not path.is_file():
        return {"status": "not_locked", "path": "backend/eval/protocol-lock.json"}
    try:
        data = lock.read(path)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        return {"status": "unreadable", "message": str(exc)[:200]}
    view = {"status": "locked", "tag": data.get("tag"), "set": data.get("set"), "created_at": data.get("created_at"),
            "combined_sha256": data.get("combined_sha256"), "prompt_hash": data.get("prompt_hash"),
            "n_files": len(data.get("files") or {})}
    try:
        from ..evalkit.__main__ import _lock_inputs     # the same inputs `evalkit lock --check` compares
        files, prompt = _lock_inputs(data["set"], None, None, None, data.get("cache_snapshot"))
        diff = lock.differences(data, files, prompt)
        view.update(check="matches" if not diff else "differs", n_differences=len(diff))
    except (FileNotFoundError, KeyError) as exc:
        view.update(check="not_verifiable", message=str(exc)[:200])
    return view


def _guard_view(set_name: str) -> Dict[str, Any]:
    """Counts of the leakage guard for one set (evalkit.guard.check). Only counts: no scenario text is returned."""
    from ..evalkit import guard
    from ..evalkit.scenarios import load_scenarios, scenario_dir
    from ..retrieval.corpus import corpus_dir
    if not scenario_dir(set_name).is_dir():
        return {"set": set_name, "status": "absent"}
    scenarios = load_scenarios(set_name)
    if not scenarios:
        return {"set": set_name, "status": "absent"}
    passages = guard.load_passages(corpus_dir())
    n_corpus = len(passages)
    if set_name != "dev" and scenario_dir("dev").is_dir():
        passages = passages + guard.scenario_passages(load_scenarios("dev"))
    res = guard.check(scenarios, passages)
    return {"set": set_name, "status": "clean" if not res["hits"] else "hits", "n_scenarios": res["n_scenarios"],
            "n_fields": res["n_fields"], "n_hits": len(res["hits"]), "n_corpus_passages": n_corpus,
            "n_dev_fields": len(passages) - n_corpus, "n": res["n"], "span": res["span"], "share": res["share"],
            "isolation_checked": False}


def eval_overview(store: Store) -> Dict[str, Any]:
    """Evaluation results as evalkit reports them, one block per scenario set found in the store.

    A development-set block is labelled as such and is never an experiment result. Rated measures, paired differences
    with bootstrap intervals and rater agreement appear only when ratings exist."""
    from ..evalkit import rating
    from ..evalkit import report as rep
    from ..evalkit import tables
    items = store.list_eval_items()
    ratings = store.list_ratings()
    raters = sorted({r["rater"] for r in ratings})
    rated_ids = {r["item_id"] for r in ratings}
    sets = []
    for set_name in sorted({i.get("set") or "unknown" for i in items}, key=lambda s: (s != "test", s)):
        group = [i for i in items if (i.get("set") or "unknown") == set_name]
        auto = rep.automatic(group)
        variants = [v for v in tables._variants(group) if v in auto]
        scores = rep.scenario_scores(store, group, None)
        meta = rep.scenario_meta(group)
        steps = []
        for a, b, code in tables.STEPS:
            p = rep.paired_measure(scores, a, b, "act_correct", meta)
            steps.append({"a": a, "b": b, "comparison": None if code == tables.DASH else code,
                          "measure": "act_correct", "paired": p})
        per_rater = {}
        for rater in raters:
            rated = rep.rated(store, group, rater)
            if not rated:
                continue
            per_rater[rater] = {"rated": {v: _strip(m) for v, m in rated.items()},
                                "steps": [{"a": a, "b": b, "paired": rep.paired(rated, a, b)}
                                          for a, b, _h in tables.STEPS]}
        group_ids = {i["id"] for i in group}
        agreement = None
        if len(per_rater) >= 2:
            first, second = sorted(per_rater)[:2]
            # evalkit's agreement reads every rating of the two raters; it is shown only when they rated this set alone
            only_here = all(r["item_id"] in group_ids for r in ratings if r["rater"] in (first, second))
            agreement = dict(rep.agreement(store, first, second), raters=[first, second]) if only_here else \
                {"raters": [first, second], "status": "mixed_sets"}
        sets.append({
            "set": set_name, "label": SET_LABELS.get(set_name, set_name), "experiment_result": set_name == "test",
            "n_items": len(group), "n_rated_items": len(group_ids & rated_ids),
            "batches": rating.batches(store, set_name if set_name != "unknown" else None),
            "ladder": list(tables.LADDER), "variants": variants, "automatic": {v: auto[v] for v in variants},
            "steps": steps, "raters": per_rater, "agreement": agreement,
            # exactly what `python -m smartagri.evalkit report --format md` prints for these items
            "report_md": tables.render(store, group, raters[0] if raters else None,
                                       tuple(agreement["raters"]) if agreement and "status" not in agreement else None),
        })
    return {"generated_at": now_iso(), "sets": sets, "has_test_results": any(s["set"] == "test" for s in sets),
            "lock": _lock_view(), "guard": [_guard_view("dev"), _guard_view("test")],
            "commands": {"report": "python -m smartagri.evalkit report --format md",
                         "guard": "python -m smartagri.evalkit guard --set test",
                         "lock_check": "python -m smartagri.evalkit lock --check"}}


# ---------------------------------------------------------------- provenance export of one answer
def provenance(store: Store, run: Dict[str, Any]) -> Dict[str, Any]:
    """Everything stored for one answer, for download: the run (answer, decisions pi/q/sigma/alpha/delta/gamma,
    sources, data with age and reliability, hashes) and the stored provenance of the profile it was given."""
    from .. import __version__
    prov = run.get("provenance") or {}
    profile = store.get_profile(prov["profile_id"]) if prov.get("profile_id") else None
    profile_view = None
    if profile:
        w, s = profile.get("weather") or {}, profile.get("satellite") or {}
        profile_view = {"id": profile["id"], "as_of": profile.get("as_of"), "provenance": profile.get("provenance"),
                        "weather": {k: w.get(k) for k in ("status", "source", "endpoint", "fetched_at", "request_hash",
                                                          "retrospective_constructed", "summary")},
                        "satellite": {k: s.get(k) for k in ("status", "source", "fetched_at", "request_hash", "summary")},
                        "quality": profile.get("quality")}
    answer = run.get("answer") or {}
    return {
        "format": "smartagri-provenance/1", "exported_at": now_iso(),
        "run": run,
        "hashes": {"config": prov.get("config_hashes"), "corpus": prov.get("corpus_hash"),
                   "prompt": prov.get("prompt_hash"), "judge_prompt": prov.get("judge_prompt_hash"),
                   "code_version": {"package_version_at_export": __version__, "recorded_with_run": False}},
        "decisions": run.get("decisions"),
        "sources": answer.get("sources") or answer.get("citations") or [],
        "inputs": answer.get("data_used") or [],
        "profile": profile_view,
    }
