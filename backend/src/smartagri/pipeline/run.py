"""One advisory turn: retrieve, decide, generate, and assemble the run record."""
from __future__ import annotations

import dataclasses
import time
from typing import Any, Dict

from ..core.decide import decide
from ..i18n import L
from ..core.types import AdviceType, Context, SatelliteSummary, VariantConfig, WeatherSummary
from ..retrieval.corpus import Corpus
from ..retrieval.search import Retriever
from .generate import prompt_hash
from .intent import operation_in, parse_reply


def stated_conditions(question: str) -> Dict[str, Any]:
    """Conditions a condition-aware baseline can read from the question text alone."""
    from ..retrieval.search import fold
    t, out = fold(question), {}
    if "kukuruz" in t:
        out["crop"] = "maize"
    kind, bbch = parse_reply("phenophase", question)
    if kind == "value" and any(w in t for w in ("list", "metlic", "svil", "mlecn", "vostan", "bbch")):
        out["bbch"] = bbch
    return out


def ablate_context(ctx: Context, variant: VariantConfig) -> Context:
    """Remove the parts of the dynamic context a variant may not see.

    `dynamic_context: false` (rungs below the dynamic parcel context: V0-V2) removes both the weather summary W
    and the NDVI series S, so those variants see only the static parcel profile (P, A) and the question Q.
    `use_weather` / `use_satellite: false` remove one of them (E4 ablations). Driven only by these flags
    (defaults in config.load_variants), never by the variant's name. Returns a shallow copy; the caller's
    context is left intact."""
    changes: Dict[str, Any] = {}
    dynamic = getattr(variant, "dynamic_context", True)
    if not dynamic or not getattr(variant, "use_weather", True):
        changes["W"] = WeatherSummary()
    if not dynamic or not getattr(variant, "use_satellite", True):
        changes["S"] = SatelliteSummary()
    return dataclasses.replace(ctx, **changes) if changes else ctx


def advise(ctx: Context, corpus: Corpus, retriever: Retriever, variant: VariantConfig, generator) -> Dict[str, Any]:
    """Run the full pipeline for ctx.Q and return answer, decisions, provenance and cost."""
    started = time.time()
    ctx = ablate_context(ctx, variant)
    t = ctx.Q.advice_type
    if t == AdviceType.FIELD_OPS_WINDOW and not ctx.A.operation:
        ctx.A.operation = operation_in(ctx.Q.text)
    ctx.Q.stated_conditions = stated_conditions(ctx.Q.text)
    passages = retriever.search(ctx.Q.text, t) if t != AdviceType.OUT_OF_SCOPE else []
    d = decide(ctx, passages, variant)
    answer, grounding, usage = generator.generate(ctx, d, corpus, grounding_check=variant.grounding)

    decisions = d.to_dict()
    for key in ("variant", "advice_type", "tools", "config_hashes"):
        decisions.pop(key, None)
    decisions["grounding"] = grounding
    scene_dates = [o.obs_date for o in ctx.S.ndvi_series]
    provenance_extra: Dict[str, Any] = {}
    call = getattr(generator, "last_call", None)
    if call:                                  # what actually answered: provider, model, request id, tokens
        provenance_extra["llm_call"] = dict(call)
    judge = getattr(generator, "judge", None)
    if judge is not None and getattr(judge, "calls", None):
        provenance_extra["judge_calls"] = list(judge.calls)
        judge.calls = []
    return {
        "advice_type": t.value, "advice_type_label": L().ADVICE_TYPES[t.value],
        "answer": answer, "decisions": decisions,
        "provenance": {"as_of": ctx.as_of.isoformat() if ctx.as_of else None, "config_hashes": d.config_hashes,
                       "corpus_hash": corpus.hash, "model": generator.model, "prompt_hash": prompt_hash(),
                       "judge_prompt_hash": getattr(generator, "judge_prompt_hash", None),
                       "scene_dates": scene_dates, "forecast_issued_at": ctx.W.forecast_issued_at,
                       "context_used": {"weather": getattr(variant, "dynamic_context", True)
                                        and getattr(variant, "use_weather", True),
                                        "satellite": getattr(variant, "dynamic_context", True)
                                        and getattr(variant, "use_satellite", True)}, **provenance_extra},
        "cost": dict(usage, seconds=round(time.time() - started, 3)),
    }
