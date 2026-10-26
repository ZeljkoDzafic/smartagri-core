"""Conflicts between applicable sources (the source-conflict rule of the decision model, docs/architecture.md).

The core does not pick a winner by asking a language model which source is more credible.
It uses applicability, which is checkable:
 (i)   one side has only applicable passages, the other only conditional ones: prefer the applicable side;
 (ii)  both sides have applicable passages and the key concerns the advice type asked about: the
       advice is degraded to a conditional answer that states both positions;
 (iii) otherwise: both positions are reported, the act is unchanged.
"""
from __future__ import annotations

from typing import Dict, List

from .types import AdviceType, Applicability, ApplicabilityResult, Passage, SourceConflict


def detect(passages: List[Passage], results: List[ApplicabilityResult], budget: List[str],
           t: AdviceType) -> List[SourceConflict]:
    status = {r.passage_id: r.status for r in results}
    by_id = {p.id: p for p in passages}
    keys: Dict[str, Dict[str, List[str]]] = {}
    for pid in budget:
        for key, value in ((by_id[pid].meta.recommends or {}).items() if pid in by_id else []):
            keys.setdefault(key, {}).setdefault(value, []).append(pid)
    out = []
    for key, values in sorted(keys.items()):
        if len(values) < 2:
            continue
        applicable = {v for v, ids in values.items() if any(status[i] == Applicability.APPLICABLE for i in ids)}
        if len(applicable) == 1:
            out.append(SourceConflict(key, values, "prefer_applicable", next(iter(applicable))))
        elif applicable and key.startswith(t.value.split("_")[0]):
            out.append(SourceConflict(key, values, "degrade"))
        else:
            out.append(SourceConflict(key, values, "report"))
    return out
