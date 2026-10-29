"""Orchestrate one decision under a VariantConfig. Never branches on a variant name."""
from __future__ import annotations

from typing import Any, Dict, List

from .. import config
from .applicability import applicability, select_budget
from .asking import choose_question
from .conflicts import detect as detect_conflicts
from .parcel_features import input_conflicts
from .plausibility import check_number, limits
from .policy import decide as decide_act
from .quality import annotate_quality, values
from .rules import decide_action_core, soil_status
from .sufficiency import sufficiency
from .tools import crop_evapotranspiration, gross_irrigation, net_irrigation_need
from .types import Act, AdviceType, Context, Decision, Passage, PolicyDecision, Reliability, Sufficiency, ToolResult, VariantConfig

IRRIGATION = (AdviceType.IRRIGATION_TIMING, AdviceType.IRRIGATION_AMOUNT)


def _root_depth(bbch):
    if bbch is None:
        return None
    lo, hi = limits("root_depth_m")
    for row in config.load("rules")["irrigation"]["root_depth_m_by_bbch"]:
        if bbch <= row["bbch_max"]:
            return row["depth"] if check_number(row["depth"], lo, hi) is None else None   # an unusable depth gives no dose
    return None


def run_tools(t: AdviceType, vals: Dict[str, Any]) -> List[ToolResult]:
    """Run the calculations relevant to t. Each returns output=None with a reason when an input is missing."""
    if t not in IRRIGATION:
        return []
    days = config.load("rules")["irrigation"]["forecast_days"]
    bbch, et0 = vals.get("phenophase"), vals.get("et0_past_7d")
    et0_next = None if et0 is None else round(et0 * days / 7.0, 1)
    etc = crop_evapotranspiration(bbch, et0_next)
    net = net_irrigation_need(soil_status(vals), vals.get("soil_awc"), _root_depth(bbch), vals.get("precip_forecast_3d"))
    gross = gross_irrigation(net.output["net_mm"] if net.output else None, vals.get("irrigation_efficiency"))
    tools = [etc, net, gross]
    capacity = vals.get("irrigation_capacity")
    if capacity and gross.output:
        # How long the system needs for one application.
        days = round(gross.output["gross_mm"] / float(capacity), 1)
        tools.append(ToolResult("application_time", {"gross_mm": gross.output["gross_mm"], "capacity_mm_day": capacity},
                                {"days_per_application": days}, "days = gross_mm / capacity_mm_day",
                                "system capacity reported by the user"))
    return tools


def decide(ctx: Context, passages: List[Passage], variant: VariantConfig, budget: int = 6) -> Decision:
    t = ctx.Q.advice_type
    vals = values(ctx)
    q = annotate_quality(ctx, quality_aware=variant.quality)

    retrieved = passages if variant.retrieval != "none" else []
    app = [applicability(p, ctx, q, vals, variant.applicability, variant.quality) for p in retrieved]
    passage_budget = select_budget(app, budget)
    corpus_ok = variant.retrieval == "none" or bool(passage_budget)

    in_scope = t != AdviceType.OUT_OF_SCOPE
    suff = sufficiency(t, q, corpus_ok) if (variant.sufficiency and in_scope) else None
    question = None
    if variant.asking and suff is not None and suff.status != Sufficiency.SUFFICIENT:
        question = choose_question(t, vals, suff.missing_inputs(), ctx.questions_asked, ctx.declined_inputs)
    have_values = False
    if suff is not None and suff.missing:
        def present(name):
            return q[name].reliability != Reliability.MISSING
        have_values = all(any(present(n) for n in m["one_of"]) if isinstance(m, dict) else present(m)
                          for m in suff.missing)
    policy = decide_act(t, suff, question, variant.policy, have_values)
    conflicts = detect_conflicts(retrieved, app, passage_budget, t)
    if variant.policy and policy.act == Act.RECOMMEND and any(c.resolution == "degrade" for c in conflicts):
        policy = PolicyDecision(Act.CONDITIONAL, "source_conflict", False, ["state_both_positions"])

    return Decision(
        variant=variant.name, advice_type=t, quality=q, applicability=app, passage_budget=passage_budget,
        sufficiency=suff, question=question, policy=policy,
        core_action=decide_action_core(t, vals) if in_scope else None,
        tools=run_tools(t, vals), config_hashes=config.config_hashes(), conflicts=conflicts,
        input_conflicts=input_conflicts(q),
    )
