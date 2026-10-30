"""Scenario files on disk. No imports from the pipeline, so tools that must not run the system
(the leakage guard) can read scenarios without loading the decision model."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# Retrospective sets (docs/retrospective-set.md): real parcels at a past decision moment, read from a folder outside the
# repository. Season 2024 is development, season 2025 is the test; the test season is protected like the test set.
RETRO_SETS = {"retrospective-dev": 2024, "retrospective-test": 2025}
PROTECTED_SETS = ("test", "retrospective-test")     # sets the system must never be run on before the protocol is locked


def scenario_dir(name: str) -> Path:
    if name in RETRO_SETS:
        from .retrospective import retro_dir
        return retro_dir(name)
    return Path(__file__).resolve().parents[3] / "eval" / "scenarios" / name


def with_decision_hour(sc: Dict[str, Any], hour: Optional[int]) -> Dict[str, Any]:
    """The scenario with its decision moment (`context.as_of`) fixed to `hour`:00 UTC of its own day; unchanged for None.
    The rain-forecast age, and with it q and sigma, depends on the decision hour (the forecast is taken as available 6 h
    after its run), so a protocol may fix one hour for every scenario. ValueError for a naive or non-ISO `as_of`."""
    if hour is None:
        return sc
    from .retrospective import with_decision_hour as move
    ctx = dict(sc["context"])
    as_of = ctx.get("as_of")
    if as_of is None:
        raise ValueError("scenario %s has no context.as_of to fix the decision hour on" % sc.get("id"))
    moment = as_of if isinstance(as_of, datetime) else datetime.fromisoformat(str(as_of))
    ctx["as_of"] = move(moment, hour).isoformat()
    return dict(sc, context=ctx)


def load_scenarios(name: str, folder: Optional[Path] = None, decision_hour_utc: Optional[int] = None) -> List[Dict[str, Any]]:
    """Scenarios of a set. `decision_hour_utc` (default None: the files as written) fixes the decision hour of every one."""
    if name in RETRO_SETS:
        from .retrospective import load_pairs
        return load_pairs(folder or scenario_dir(name), RETRO_SETS[name], decision_hour_utc)
    files = sorted(p for p in (folder or scenario_dir(name)).glob("*.yaml") if not p.name.startswith("_"))
    return [with_decision_hour(yaml.safe_load(p.read_text(encoding="utf-8")), decision_hour_utc) for p in files]


def load_scenario(name: str, scenario_id: str) -> Dict[str, Any]:
    for sc in load_scenarios(name):
        if sc.get("id") == scenario_id:
            return sc
    raise KeyError("Scenario %s not found in set %s" % (scenario_id, name))
