"""Decision policy delta: recommend, recommend conditionally, ask, or abstain."""
from __future__ import annotations

from typing import Optional

from .. import config
from .types import Act, AdviceType, PolicyDecision, QuestionChoice, Sufficiency, SufficiencyResult

# Outputs that are never allowed, whatever the variant's text generator produces.
PROHIBITIONS = (
    "quantity_or_dose_without_sufficient_inputs",
    "cause_of_vegetation_change_from_index_alone",
    "plant_protection_product_prescription",
)


def _spec(t: AdviceType) -> dict:
    return config.load("requirements")["advice_types"].get(t.value, {})


def decide(t: AdviceType, suff: Optional[SufficiencyResult], question: Optional[QuestionChoice],
           policy_on: bool, missing_have_values: bool = False) -> PolicyDecision:
    """Choose the act.

    Without the sufficiency layer the core does not choose an act: the text generator is free
    (act=None). With sufficiency but without the policy layer, a deliberately simple rule applies
    and nothing is prohibited, which is exactly what the ablation step measures.

    missing_have_values: every input below its required reliability does have a value (it is
    stale or uncertain, not absent). If the user cannot improve it, the advice is given
    conditionally with the limitation stated; abstention is kept for inputs that are absent.
    """
    if t == AdviceType.OUT_OF_SCOPE:
        if policy_on:
            return PolicyDecision(Act.ABSTAIN, "out_of_scope", False, ["refer_to_extension_service"])
        return PolicyDecision(None, "delegated_to_generator", True)
    if suff is None:
        return PolicyDecision(None, "delegated_to_generator", True)

    quantity = bool(_spec(t).get("quantity", False))
    asked = question is not None and question.input is not None

    if not policy_on:
        if suff.status == Sufficiency.SUFFICIENT:
            return PolicyDecision(Act.RECOMMEND, "sufficient", True)
        if asked:
            return PolicyDecision(Act.ASK, "missing_input_changes_decision", True)
        return PolicyDecision(Act.RECOMMEND, "no_policy_layer", True, ["missing_inputs_unresolved"])

    if suff.corpus_insufficient:
        return PolicyDecision(Act.ABSTAIN, "corpus_insufficient", False, ["refer_to_extension_service"])
    if suff.status == Sufficiency.SUFFICIENT:
        return PolicyDecision(Act.RECOMMEND, "sufficient", quantity)
    if asked:
        if _spec(t).get("risk") == "high":
            return PolicyDecision(Act.ASK, "high_risk_ask_before_any_quantity", False)
        return PolicyDecision(Act.CONDITIONAL, "conditional_with_question", False)
    reason = question.reason if question is not None else "asking_layer_off"
    if suff.status == Sufficiency.PARTIAL:
        return PolicyDecision(Act.CONDITIONAL, "degraded_to_" + suff.degraded_to.value, False, [reason])
    if reason in ("decision_insensitive", "budget_exhausted"):
        return PolicyDecision(Act.CONDITIONAL, reason, False, ["state_remaining_missing_inputs"])
    if missing_have_values:
        return PolicyDecision(Act.CONDITIONAL, "unreliable_inputs_stated", False, ["state_unreliable_inputs"])
    return PolicyDecision(Act.ABSTAIN, "missing_inputs_" + reason, False, ["state_remaining_missing_inputs"])
