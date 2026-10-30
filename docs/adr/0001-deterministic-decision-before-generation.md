# 0001. Deterministic decision layers before any text generation

- Status: Accepted
- Date: 2026-10-21

## Context

An advisory answer has two parts: what to do (advise, ask, or decline) and how to say it. If a language model
decides both, the decision cannot be inspected, repeated or attributed to an input, and an ablation cannot tell which
part of the system caused a change in quality. Selective answering (asking or abstaining when inputs are missing or
unreliable) needs to be a property of the system that can be tested, not a tendency of a prompt.

## Decision

The act (recommend, conditional, ask, abstain), the reason, the question to ask and whether a quantity may be shown
are chosen by explicit, deterministic layers before any text is produced: applicability π, quality q,
sufficiency σ, asking α and policy δ (`backend/src/smartagri/core/`, orchestrated by `core/decide.py`). Each layer
reads its parameters from a YAML file in `backend/config/`. The text generator receives the finished decision and
may only phrase it; γ checks the generated text afterwards.

The ablation rungs without the sufficiency layer (V0–V3) are the exception by design: they stand for a language model
with the data of their rung, so the generator chooses the act itself and receives no conclusion of the decision core
(`pipeline/generate.py`, `fact_sheet`). The decision of the core is still computed and recorded for them.

Variants switch layers on and off through flags in `config/variants.yaml`; the core never branches on a variant
name.

## Consequences

- Every decision is reproducible from its inputs and the hashed configuration, and is covered by unit tests
  (see [layers.md](../layers.md)).
- Layers can be ablated one configuration flag at a time for evaluation.
- The decision is only as good as the rules and thresholds; those are development defaults pending review
  ([limitations.md](../limitations.md)).
- Questions outside the six advice types are not answered by the model's general knowledge; they lead to abstention
  with a referral.
