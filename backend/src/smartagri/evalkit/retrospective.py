"""Retrospective pairs: a real parcel at a past decision moment, the outcome realised afterwards.

A pair is one JSON file in a folder OUTSIDE the repository (like the test set it is never committed; the folder comes
from `--scenarios-dir` or `SMARTAGRI_RETRO_DIR/<set>`). The format is documented in docs/retrospective-set.md. Reading
files only: nothing here fetches data, runs the system or imports the decision model beyond the context record.

The loader turns a pair into the scenario shape the rest of evalkit reads (`id`, `stratum`, `cluster`, `context`,
`user_replies`), with two extra blocks that never reach the system or the rater: `retrospective` (season, decision
moment, snapshot reference) and `outcome` (what happened afterwards). It fails loudly: an unknown field, a missing block,
a date after the decision moment (context, snapshot, replies), an outcome that precedes the decision, a duplicate id, a
season that does not belong to the set, a folder inside the repository.

`rain_wait_outcome` is the objective outcome of rain-wait advice against the realised rainfall (docs/retrospective-set.md,
section 4 of the design): a pure function over a daily series the caller supplies. Its parameters are decisions of the
protocol owner and the agronomist; they have no defaults.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

SCHEMA = "smartagri-retrospective-pair/1"
REQUIRED = ("schema", "id", "season", "parcel_code", "decision_at", "advice_type", "question", "context",
            "weather_snapshot", "outcome")
OPTIONAL = ("stratum", "user_replies", "note")
SNAPSHOT_REQUIRED = ("source", "ref", "issued_before")
# Keys a context must not carry: the decision moment and the question come from the pair, the outcome never from here.
CONTEXT_FORBIDDEN = ("as_of", "Q", "outcome", "realised", "observed", "actual")


class RetrospectiveError(ValueError):
    """A retrospective pair or folder does not meet the format or the leakage rules."""


def _moment(text: Any, label: str) -> datetime:
    try:
        m = datetime.fromisoformat(str(text))
    except ValueError:
        raise RetrospectiveError("%s is not an ISO date-time: %r" % (label, text))
    if m.tzinfo is None:
        raise RetrospectiveError("%s has no UTC offset: %r" % (label, text))
    return m


def _day(text: Any, label: str) -> date:
    try:
        return date.fromisoformat(str(text)[:10])
    except ValueError:
        raise RetrospectiveError("%s is not an ISO date: %r" % (label, text))


def with_decision_hour(moment: datetime, hour: Optional[int]) -> datetime:
    """The decision moment moved to `hour`:00 UTC of its own calendar day (the day in the moment's own offset).
    None leaves it as it is. ValueError for an hour outside 0-23, for a moment without a UTC offset (the hour would be
    ambiguous), and when that UTC hour falls on another calendar day of the moment's offset."""
    if hour is None:
        return moment
    if isinstance(hour, bool) or not isinstance(hour, int) or not 0 <= hour <= 23:
        raise ValueError("decision_hour_utc must be an hour 0-23, not %r" % (hour,))
    if moment.tzinfo is None:
        raise ValueError("decision_hour_utc needs a decision moment with a UTC offset; %s has none" % moment.isoformat())
    new = datetime(moment.year, moment.month, moment.day, hour, tzinfo=timezone.utc)
    if new.astimezone(moment.tzinfo).date() != moment.date():
        raise ValueError("%02d:00 UTC is another local day than the decision day %s (offset %s)"
                         % (hour, moment.date().isoformat(), moment.tzinfo.utcoffset(moment)))
    return new


def retro_dir(set_name: str) -> Path:
    """Folder of a retrospective set outside the repository: SMARTAGRI_RETRO_DIR/<set>. No default location."""
    import os
    env = os.environ.get("SMARTAGRI_RETRO_DIR")
    if not env:
        raise RetrospectiveError("a retrospective set is read from a folder outside the repository: pass --scenarios-dir "
                                 "or set SMARTAGRI_RETRO_DIR (the pairs are never committed)")
    return Path(env) / set_name


def _outside_repo(folder: Path) -> None:
    from .lock import REPO
    f, repo = folder.resolve(), REPO.resolve()
    if f == repo or repo in f.parents:
        raise RetrospectiveError("%s is inside the repository; retrospective pairs live outside the repository "
                                 "(never committed)" % folder)


def parse_pair(data: Mapping[str, Any], source: str, decision_hour_utc: Optional[int] = None) -> Dict[str, Any]:
    from ..core.types import AdviceType, Context
    where = "%s: " % source
    unknown = sorted(set(data) - set(REQUIRED) - set(OPTIONAL))
    if unknown:
        raise RetrospectiveError(where + "unknown field(s) %s" % ", ".join(unknown))
    missing = [k for k in REQUIRED if k not in data]
    if missing:
        raise RetrospectiveError(where + "missing field(s) %s" % ", ".join(missing))
    if data["schema"] != SCHEMA:
        raise RetrospectiveError(where + "schema must be %r, not %r" % (SCHEMA, data["schema"]))
    if not isinstance(data["season"], int) or isinstance(data["season"], bool):
        raise RetrospectiveError(where + "season must be a year")
    if not str(data["id"]).strip() or not str(data["parcel_code"]).strip():
        raise RetrospectiveError(where + "id and parcel_code are required")
    try:
        AdviceType(data["advice_type"])
    except ValueError:
        raise RetrospectiveError(where + "advice_type %r is not one of %s" % (data["advice_type"],
                                                                              ", ".join(a.value for a in AdviceType)))
    decision = _moment(data["decision_at"], where + "decision_at")
    try:
        decision = with_decision_hour(decision, decision_hour_utc)
    except ValueError as exc:
        raise RetrospectiveError(where + str(exc))
    snap = data["weather_snapshot"]
    if not isinstance(snap, dict) or any(not snap.get(k) for k in SNAPSHOT_REQUIRED):
        raise RetrospectiveError(where + "weather_snapshot needs %s" % ", ".join(SNAPSHOT_REQUIRED))
    if _moment(snap["issued_before"], where + "weather_snapshot.issued_before") > decision:
        raise RetrospectiveError(where + "the weather snapshot was issued after the decision moment (%s > %s)"
                                 % (snap["issued_before"], decision.isoformat()))
    outcome = data["outcome"]
    series = outcome.get("daily_precip_mm") if isinstance(outcome, dict) else None
    if not isinstance(outcome, dict) or not outcome.get("source") or not isinstance(series, dict) or not series:
        raise RetrospectiveError(where + "outcome needs source and a non-empty daily_precip_mm {date: mm}")
    for day, mm in series.items():
        if _day(day, where + "outcome date") < decision.date():
            raise RetrospectiveError(where + "outcome date %s is before the decision day %s" % (day, decision.date()))
        if mm is not None and (not isinstance(mm, (int, float)) or isinstance(mm, bool) or mm < 0):
            raise RetrospectiveError(where + "outcome %s is negative or not a number: %r" % (day, mm))
    ctx = data["context"]
    if not isinstance(ctx, dict):
        raise RetrospectiveError(where + "context must be a mapping")
    bad = [k for k in CONTEXT_FORBIDDEN if k in ctx]
    if bad:
        raise RetrospectiveError(where + "context must not contain %s (as_of and Q come from the pair; the outcome never "
                                         "enters the context)" % ", ".join(bad))
    for obs in (ctx.get("S") or {}).get("ndvi_series") or []:
        if _day(obs.get("obs_date"), where + "ndvi obs_date") > decision.date():
            raise RetrospectiveError(where + "an NDVI observation (%s) is dated after the decision day" % obs.get("obs_date"))
    context = dict(ctx, as_of=decision.isoformat(), Q={"text": data["question"], "advice_type": data["advice_type"]})
    try:
        Context.from_dict(context)                              # dates of the record against the decision moment, field names
    except (ValueError, TypeError) as exc:
        raise RetrospectiveError(where + "context: %s" % exc)
    replies = data.get("user_replies") or {}
    if not isinstance(replies, dict):
        raise RetrospectiveError(where + "user_replies must be a mapping (replies recorded before the decision)")
    return {"id": str(data["id"]), "stratum": data.get("stratum"), "cluster": str(data["parcel_code"]), "question": data["question"],
            "note": data.get("note"), "context": context, "user_replies": replies, "reference": None,
            "retrospective": {"schema": SCHEMA, "season": data["season"], "decision_at": decision.isoformat(),
                              "advice_type": data["advice_type"], "weather_snapshot": dict(snap),
                              "decision_hour_utc": decision_hour_utc},
            "outcome": {"source": outcome["source"], "daily_precip_mm": dict(series)}}


def load_pairs(folder: Path, season: Optional[int] = None, decision_hour_utc: Optional[int] = None) -> List[Dict[str, Any]]:
    """Every pair file (`*.json`, not starting with `_`) of a folder as a scenario dict; `season` (when given) must be the
    season of every pair. RetrospectiveError on the first problem."""
    folder = Path(folder)
    if not folder.is_dir():
        raise RetrospectiveError("%s is not a folder" % folder)
    _outside_repo(folder)
    files = sorted(p for p in folder.glob("*.json") if not p.name.startswith("_"))
    if not files:
        raise RetrospectiveError("no pair files (*.json) in %s" % folder)
    out, seen = [], set()
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise RetrospectiveError("%s: not valid JSON (%s)" % (path.name, exc))
        if not isinstance(data, dict):
            raise RetrospectiveError("%s: a pair is a JSON object" % path.name)
        sc = parse_pair(data, path.name, decision_hour_utc)
        if season is not None and sc["retrospective"]["season"] != season:
            raise RetrospectiveError("%s: season %s, but this set holds season %s" % (path.name, sc["retrospective"]["season"], season))
        if sc["id"] in seen:
            raise RetrospectiveError("duplicate pair id %s (%s)" % (sc["id"], path.name))
        seen.add(sc["id"])
        out.append(sc)
    return out


# ---------------------------------------------------------------- objective outcome of rain-wait advice

ADVICE_KINDS = ("wait", "irrigate_now")


def advice_kind(core_action: Optional[str]) -> Optional[str]:
    """Rain-wait kind of an irrigation-timing core action (core/rules.py): wait_for_rain -> "wait",
    irrigate_within_2d -> "irrigate_now"; None for any other action (no rain-wait outcome)."""
    return {"wait_for_rain": "wait", "irrigate_within_2d": "irrigate_now"}.get(core_action or "")


def rain_wait_outcome(advice: str, decision_date: Any, daily_precip_mm: Mapping[Any, Optional[float]], *,
                      window_days: int, threshold_mm: float, effect_lag_days: int,
                      include_decision_day: bool) -> Dict[str, Any]:
    """Is rain-wait advice contrary to the realised rainfall? A pure function; nothing is fetched.

    Input contract (the caller supplies; every keyword parameter is a decision, none has a default):
      advice               "wait" (wait for rain) or "irrigate_now" (irrigate without waiting); other values are not evaluable
      decision_date        the calendar day of the decision (date or ISO text)
      daily_precip_mm      {day: mm} of the realised rainfall (station, hydrometeorological service or reanalysis: the
                           source is the caller's, and is reported with the result); a day that is missing or None is unknown
      window_days          N: days after the decision in which the awaited rain must fall ([DECISION] of the protocol owner)
      threshold_mm         x: rain that justifies waiting ([DECISION] of the agronomist who does not rate; not the rules.yaml value)
      effect_lag_days      days before irrigation could act; rain inside it makes "irrigate now" contrary ([DECISION])
      include_decision_day whether the decision day itself counts (daily data cannot say what fell after the decision hour)

    Rule: "wait" is contrary when the rain in the window is below the threshold; "irrigate_now" is contrary when the rain
    in the first `effect_lag_days` reaches the threshold. Returns {evaluable, contrary (None when not evaluable), rain_mm,
    window [first, last], rule, reason}. Incomplete data is not evaluable and never filled in."""
    for name, value in (("window_days", window_days), ("effect_lag_days", effect_lag_days)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError("%s must be a whole number of at least 1" % name)
    if isinstance(threshold_mm, bool) or not isinstance(threshold_mm, (int, float)) or not threshold_mm > 0:
        raise ValueError("threshold_mm must be a positive number")
    if advice not in ADVICE_KINDS:
        return {"evaluable": False, "contrary": None, "rain_mm": None, "window": None, "rule": None,
                "reason": "the advice %r is not rain-wait advice (wait, irrigate_now)" % (advice,)}
    day0 = decision_date if isinstance(decision_date, date) and not isinstance(decision_date, datetime) \
        else _day(decision_date, "decision_date")
    first = day0 if include_decision_day else day0 + timedelta(days=1)
    days = window_days if advice == "wait" else effect_lag_days
    window = [first + timedelta(days=k) for k in range(days)]
    series = {_day(k, "daily_precip_mm key").isoformat(): v for k, v in daily_precip_mm.items()}
    gaps = [d.isoformat() for d in window if series.get(d.isoformat()) is None]
    rule = ("wait: contrary when rain in %d day(s) < %s mm" % (window_days, threshold_mm) if advice == "wait" else
            "irrigate_now: contrary when rain in the first %d day(s) >= %s mm" % (effect_lag_days, threshold_mm))
    span = [window[0].isoformat(), window[-1].isoformat()]
    if gaps:
        return {"evaluable": False, "contrary": None, "rain_mm": None, "window": span, "rule": rule,
                "reason": "no realised rainfall for %s" % ", ".join(gaps)}
    rain = round(sum(float(series[d.isoformat()]) for d in window), 6)
    contrary = rain < threshold_mm if advice == "wait" else rain >= threshold_mm
    return {"evaluable": True, "contrary": contrary, "rain_mm": rain, "window": span, "rule": rule, "reason": None}
