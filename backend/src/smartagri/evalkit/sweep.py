"""Synthetic variations of one development scenario (docs/protocol.md: secondary analysis).

Each combination of the varied parameters yields a copy of the scenario with shifted observation
dates, forecast issue time or usable-pixel share; the copy is played like any scenario and only
automatic measures are kept (act, sufficiency, question, turns). Results are not stored as
evaluation items: they are not independent samples and never enter the primary test.

Monotonicity: older (or less usable) data must never raise the sufficiency rank
(insufficient < partial < sufficient) when every other parameter is held fixed.
"""
from __future__ import annotations

import copy
import itertools
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Sequence, Tuple

from .scenarios import PROTECTED_SETS

SUFFICIENCY_RANK = {"insufficient": 0, "partial": 1, "sufficient": 2}
# parameter -> True when a larger value means older / worse data
WORSE_WHEN_LARGER = {"ndvi_age": True, "forecast_age": True, "soil_water_age": True, "bbch_age": True,
                     "usable_share": False}


def parse_vary(specs: Sequence[str]) -> List[Tuple[str, List[float]]]:
    """["ndvi_age=2,5,8"] -> [("ndvi_age", [2.0, 5.0, 8.0])]."""
    out = []
    for spec in specs:
        name, _, raw = spec.partition("=")
        name = name.strip()
        if name not in WORSE_WHEN_LARGER:
            raise ValueError("Unknown parameter %r; known: %s" % (name, ", ".join(sorted(WORSE_WHEN_LARGER))))
        vals = [float(x) for x in raw.strip().strip("[]").split(",") if x.strip()]
        if not vals:
            raise ValueError("No values for %s" % name)
        out.append((name, vals))
    return out


def _as_of(sc: Dict[str, Any]) -> datetime:
    v = sc["context"]["as_of"]
    return v if isinstance(v, datetime) else datetime.fromisoformat(str(v))


def _series(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    series = (ctx.get("S") or {}).get("ndvi_series") or []
    if not series:
        raise ValueError("The scenario has no NDVI series to vary")
    return sorted(series, key=lambda o: str(o["obs_date"]))


def derive(sc: Dict[str, Any], params: Dict[str, float]) -> Dict[str, Any]:
    """Copy of `sc` with the given data ages (days before as_of) and usable share applied."""
    out = copy.deepcopy(sc)
    ctx = out["context"]
    as_of = _as_of(out)
    for name, value in params.items():
        if name == "ndvi_age":
            series = _series(ctx)
            latest = datetime.fromisoformat(str(series[-1]["obs_date"])).date()
            shift = (as_of.date() - timedelta(days=int(value))) - latest
            for o in series:
                o["obs_date"] = (datetime.fromisoformat(str(o["obs_date"])).date() + shift).isoformat()
            ctx["S"]["ndvi_series"] = series
        elif name == "usable_share":
            series = _series(ctx)
            series[-1]["usable_share"] = float(value)
            ctx["S"]["ndvi_series"] = series
        elif name == "forecast_age":
            if not ctx.get("W"):
                raise ValueError("The scenario has no weather summary to vary")
            ctx["W"]["forecast_issued_at"] = (as_of - timedelta(days=float(value))).isoformat()
        elif name == "soil_water_age":
            ctx.setdefault("A", {})["soil_water_reported_on"] = (as_of.date() - timedelta(days=int(value))).isoformat()
        elif name == "bbch_age":
            ctx.setdefault("A", {})["bbch_reported_on"] = (as_of.date() - timedelta(days=int(value))).isoformat()
        else:
            raise ValueError("Unknown parameter %r" % name)
    out["id"] = "%s~%s" % (sc["id"], ",".join("%s=%g" % kv for kv in sorted(params.items())))
    out.pop("expect", None)                     # the expectation belongs to the original scenario only
    return out


def combinations(vary: Sequence[Tuple[str, List[float]]]) -> List[Dict[str, float]]:
    names = [n for n, _ in vary]
    return [dict(zip(names, combo)) for combo in itertools.product(*[v for _, v in vary])]


def monotonicity(rows: List[Dict[str, Any]], names: Sequence[str]) -> List[Dict[str, Any]]:
    """Pairs where data got older (or less usable) along one parameter, all others fixed, and the
    sufficiency rank went up. Rows without a sufficiency outcome (variants without sigma) are skipped."""
    violations = []
    for name in names:
        others = [n for n in names if n != name]
        groups: Dict[Tuple, List[Dict[str, Any]]] = {}
        for r in rows:
            groups.setdefault(tuple(r["params"][o] for o in others), []).append(r)
        for group in groups.values():
            ordered = sorted(group, key=lambda r: r["params"][name], reverse=not WORSE_WHEN_LARGER[name])
            for better, worse in zip(ordered, ordered[1:]):
                rb, rw = SUFFICIENCY_RANK.get(better["sufficiency"]), SUFFICIENCY_RANK.get(worse["sufficiency"])
                if rb is not None and rw is not None and rw > rb:
                    violations.append({"vary": name, "from": better["params"], "to": worse["params"],
                                       "sufficiency_from": better["sufficiency"], "sufficiency_to": worse["sufficiency"],
                                       "act_from": better["act"], "act_to": worse["act"]})
    return violations


def sweep(sc: Dict[str, Any], set_name: str, vary: Sequence[Tuple[str, List[float]]], variant: str,
          play: Callable[[Dict[str, Any]], Dict[str, Any]]) -> Dict[str, Any]:
    """Play every combination with `play` (a scenario -> run_scenario result function)."""
    if set_name in PROTECTED_SETS:
        raise PermissionError("Sweeps on the %r set are not allowed: test scenarios are never run during development." % set_name)
    rows = []
    for params in combinations(vary):
        res = play(derive(sc, params))
        rows.append({"params": params, "act": res["first_act"], "final_act": res["final_act"],
                     "sufficiency": res.get("first_sufficiency"), "question": res.get("first_question_input"),
                     "n_turns": res["n_turns"]})
    names = [n for n, _ in vary]
    return {"scenario": sc["id"], "set": set_name, "variant": variant, "vary": {n: v for n, v in vary},
            "rows": rows, "monotonicity_violations": monotonicity(rows, names)}


def text_table(result: Dict[str, Any]) -> str:
    names = list(result["vary"])
    head = names + ["act", "sufficiency", "question", "turns"]
    body = [["%g" % r["params"][n] for n in names] + [r["act"], r["sufficiency"] or "-", r["question"] or "-", str(r["n_turns"])]
            for r in result["rows"]]
    widths = [max(len(h), *(len(b[i]) for b in body)) if body else len(h) for i, h in enumerate(head)]
    lines = ["%s %s %s" % (result["scenario"], result["variant"], result["set"]),
             "  ".join(h.ljust(w) for h, w in zip(head, widths)), "  ".join("-" * w for w in widths)]
    lines += ["  ".join(c.ljust(w) for c, w in zip(b, widths)) for b in body]
    v = result["monotonicity_violations"]
    lines.append("monotonicity: %s" % ("OK" if not v else "%d violation(s)" % len(v)))
    for x in v:
        lines.append("  %s: %s (%s) -> %s (%s)" % (x["vary"], x["from"], x["sufficiency_from"], x["to"], x["sufficiency_to"]))
    return "\n".join(lines)
