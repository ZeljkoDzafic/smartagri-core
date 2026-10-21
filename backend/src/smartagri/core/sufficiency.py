"""Sufficiency predicate sigma(t, C, q): do we know enough, reliably enough, to advise on t?"""
from __future__ import annotations

from typing import Any, List, Optional

from .. import config
from .types import AdviceType, QualityProfile, Reliability, Sufficiency, SufficiencyResult


def _below(q: QualityProfile, item: dict) -> bool:
    return q[item["input"]].reliability.rank < Reliability(item["min_reliability"]).rank


def missing_inputs(t: AdviceType, q: QualityProfile) -> List[Any]:
    spec = config.load("requirements")["advice_types"][t.value]
    missing: List[Any] = [r["input"] for r in spec.get("required", []) if _below(q, r)]
    for group in spec.get("one_of", []):
        if all(_below(q, g) for g in group):
            missing.append({"one_of": [g["input"] for g in group]})
    return missing


def sufficiency(t: AdviceType, q: QualityProfile, corpus_ok: bool = True) -> SufficiencyResult:
    """sufficient: nothing missing. partial: a narrower advice type is fully supported. insufficient: otherwise.

    corpus_ok=False means no applicable or conditional passage exists for t; the user cannot fix that.
    """
    missing = missing_inputs(t, q)
    if not missing:
        return SufficiencyResult(t, Sufficiency.SUFFICIENT, [], None, not corpus_ok)
    degraded: Optional[str] = config.load("requirements").get("degrade", {}).get(t.value)
    if degraded and not missing_inputs(AdviceType(degraded), q):
        return SufficiencyResult(t, Sufficiency.PARTIAL, missing, AdviceType(degraded), not corpus_ok)
    return SufficiencyResult(t, Sufficiency.INSUFFICIENT, missing, None, not corpus_ok)
