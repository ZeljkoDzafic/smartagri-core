"""Question selection alpha: ask for the input that changes the decision and that the user can supply."""
from __future__ import annotations

from typing import Any, Dict, List, Sequence

from .. import config
from .rules import decide_action_core
from .types import AdviceType, QuestionCandidate, QuestionChoice


def choose_question(t: AdviceType, vals: Dict[str, Any], missing: List[str], questions_asked: int,
                    declined: Sequence[str] = ()) -> QuestionChoice:
    """Rank the missing or unreliable inputs by decision sensitivity, then by cost.

    sensitivity(x) = number of distinct decision classes over the plausible values of x, minus one.
    An input with sensitivity 0 is never asked for: the answer would not change what we advise.
    An input the user already said they cannot supply is treated as not obtainable.
    """
    cfg = config.load("asking")
    candidates: List[QuestionCandidate] = []
    for name in missing:
        spec = cfg["inputs"].get(name, {})
        if not spec.get("user_obtainable", False) or name in declined:
            candidates.append(QuestionCandidate(name, 0, 0, [], False))
            continue
        outcomes = []
        for value in spec.get("plausible_values", []):
            outcome = decide_action_core(t, dict(vals, **{name: value}))
            if outcome not in outcomes:
                outcomes.append(outcome)
        candidates.append(QuestionCandidate(name, max(0, len(outcomes) - 1), int(spec.get("cost", 1)), outcomes))

    if not candidates:
        return QuestionChoice(None, candidates=candidates, reason="nothing_missing")
    obtainable = [c for c in candidates if c.user_obtainable]
    if not obtainable:
        return QuestionChoice(None, candidates=candidates, reason="not_obtainable")
    useful = [c for c in obtainable if c.sensitivity > 0]
    if not useful:
        return QuestionChoice(None, candidates=candidates, reason="decision_insensitive")
    if questions_asked >= int(cfg.get("max_questions", 2)):
        return QuestionChoice(None, candidates=candidates, reason="budget_exhausted")
    best = sorted(useful, key=lambda c: (-c.sensitivity, c.cost, missing.index(c.input)))[0]
    spec = cfg["inputs"][best.input]
    return QuestionChoice(best.input, spec.get("question_sr", ""), spec.get("how_to_obtain_sr", ""),
                          candidates, "selected")
