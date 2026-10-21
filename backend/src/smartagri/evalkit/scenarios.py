"""Scenario files on disk. No imports from the pipeline, so tools that must not run the system
(the leakage guard) can read scenarios without loading the decision model."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

PROTECTED_SETS = ("test",)          # sets the system must never be run on before the protocol is locked


def scenario_dir(name: str) -> Path:
    return Path(__file__).resolve().parents[3] / "eval" / "scenarios" / name


def load_scenarios(name: str, folder: Optional[Path] = None) -> List[Dict[str, Any]]:
    files = sorted(p for p in (folder or scenario_dir(name)).glob("*.yaml") if not p.name.startswith("_"))
    return [yaml.safe_load(p.read_text(encoding="utf-8")) for p in files]


def load_scenario(name: str, scenario_id: str) -> Dict[str, Any]:
    for sc in load_scenarios(name):
        if sc.get("id") == scenario_id:
            return sc
    raise KeyError("Scenario %s not found in set %s" % (scenario_id, name))
