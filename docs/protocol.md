# Analysis plan (pre-registered with the protocol lock)

Status: draft. This plan is locked together with the scenarios, the corpus, the configuration and the rater guide
(`python -m smartagri.evalkit lock`; the lock records the sha256 of this file as `analysis_plan/protocol.md`). After
the lock nothing in it changes; a later change is a new experiment. Items marked **TO BE DECIDED** must be decided by
the protocol owner and written here and in `backend/config/analysis.yaml` before the lock. Until then the report
prints intervals without a verdict.

The machine-readable parameters (alpha, bootstrap, `min_clusters`, margins, the primary comparison and measure, the
Holm family, the scope of the first lock) are in `backend/config/analysis.yaml`; `evalkit report` reads them from there
and never from this text. This text and the file must say the same; `tests/test_evalkit_plan.py` checks it.

**Scope of the first lock.** The ablation ladder below is the design. The first lock covers V3, V4 and VC on the 40
scenarios, plus a retrospective set (`docs/retrospective-set.md`; season 2024 development, season 2025 test).
V0-V2, V5 and E2-E5 remain in the design and the code and are run only on a small subset or in a later lock; E5 is
excluded by a switch (`scope.include_e5: false`, section 7). The independent agronomist rates; a second agronomist
reviews the configuration. The rater sees the input facts without the reliability grades of the q layer
(`rater_view: raw`, `docs/RATER_GUIDE.md`).

## 1. Design in one paragraph

Forty test scenarios (one crop, maize; four advice groups; about four complete, three missing-input and three
unreliable-input or conflicting-source scenarios per group) are answered by every rung of the ablation ladder
(`backend/config/variants.yaml`) and by the language-model baseline VC. Each rung adds one layer of the design:

| Rung | Adds | Comparison it carries |
|---|---|---|
| V0 | language model with the static parcel profile (P, A, Q), no retrieval | floor |
| V1 | hybrid retrieval (standard RAG) | |
| V2 | applicability pi from the question (condition-aware RAG) | |
| V3 | dynamic parcel context: pi reads the parcel, weather W and NDVI S become visible | E2 = V3 − V2 |
| V4 | the sufficiency-and-asking model: input quality q, sufficiency sigma, question choice alpha (one layer by design) | **E1 = V4 − V3 (primary, K4 ∪ K5)** |
| V5 | decision policy delta and grounding check gamma | E3 = V5 − V4 |
| V5-weather, V5-satellite | V5 without one source of the dynamic context | E4 |
| VC | language model with the same data, reliability labels and passages, no decision model | E5 = V5 − VC |

Below V4 no input carries a reliability grade ("ungraded"); V0-V3 may ask one free question per turn when a language
model is used, and the prepared reply is given exactly as for VC. A question with no prepared reply is answered "Ne znam." by the simulated user in **every** variant (structured question of V4/V5, free question of V0-V3 and VC) and the conversation continues; three turns at most. Every variant uses the same model, corpus, tools,
passage budget and output limit (`backend/config/evaluation.yaml`).

### 1.1 What a rung receives, and who chooses the act

V0-V3 are a language model with the data the rung allows. The model receives the question; the parcel data (static
profile P, A, Q, ungraded; from V3 also the weather summary W and the NDVI series S); the passages the rung retrieves
(none for V0; every passage counts as applicable for V1; pi over the question for V2 and over the parcel from V3); and
the results of the calculation tools that the rung's inputs allow (ETc, net and gross irrigation: numbers come from
code, never from the model; they appear when their inputs do, so from V3 on for irrigation; net and gross depth,
volume and application time only while `rules.irrigation.quantity_validated` is true, as for V4/V5). It chooses the act itself
(recommend, conditional, ask or abstain) and phrases the answer. It receives **no** act, action, timing or other
conclusion of the decision core (`core/rules.py`, the action core D_t); its prompt does not mention a core
(`pipeline/generate.py`, `SYSTEM_PROMPT_FREE`, `fact_sheet`).

The model states its act in the required field `act` of its output (one of the four words, exactly). An output without a
valid act is an error item (stored, never rated, never replaced by a default or by template text, the run exits non-zero),
like any other failed model call (section 10).

V4 and V5 differ in who decides: the layers (q, sigma, alpha, and delta from V5) choose the act, and the language model
only phrases the answer from the core's act and action. E1 = V4 − V3 therefore measures the package (q, sigma and alpha
together) **and** the change of the decision-maker from the language model to the rules; this is reported as such. E2 =
V3 − V2 measures the dynamic parcel context together with the tool results that depend on W.

The template generator has no language model. For V0-V3 it is only a deterministic fallback that always recommends and
shows the action of the decision core; every such answer carries the label **"template, not a baseline"** in the run
record (`baseline`), in `evalkit report` (JSON and tables) and in the web evaluation view, and is never a result of the
rung. The development set runs with the template to check the pipeline; a locked test-set run uses a language model for
every variant.

## 2. Primary outcome (E1)

**One primary outcome: the rate of scenarios with a K4 or K5 error (K4 ∪ K5)** — the share of a scenario's answers
(repeats averaged first) in which the independent agronomist marks at least one of K4 (premature recommendation) and K5
(unjustified abstention or question), compared as the paired difference V4 − V3 over the 40 test scenarios
(`primary.measure: k4_or_k5`). Decided by the product owner on 28 October 2026.

Note on the choice: the union with K1 is not used. K1 cannot occur while `quantity_validated` is false (quantities are
excluded), and K2 and K3 do not depend on the layer under test, so including them would only add noise. The any-class
rate K1-K5 is still reported, as a secondary outcome. The rubric score and the correctness of the first act are key
secondary outcomes (section 3).

Estimate: mean paired difference with a 95 % percentile bootstrap interval (10,000 resamples, seed 7). E1 is supported
when the whole interval lies below zero.

The primary result rests on the independent agronomist's ratings; the second rater's ratings serve agreement and the
secondary analyses. Without the independent rating E1 is reported as author-rated and is not counted as supported.

## 3. Secondary outcomes

Key secondary (E1, same pairs): K1, K2 and K3 rates, rubric total (0-10), first-turn act correctness against the
reference act; reported also: the K4 and K5 rates separately and the any-class rate K1-K5. V4 − VC (same data and
sources, no decision model) is pre-specified; whether it is co-primary or key secondary is **TO BE DECIDED** and it is
not in the Holm family until it is.

Other secondary:

- E2 (V3 − V2): Recall@k and precision of applicable sources; rubric total.
- E3 (V5 − V4): critical-error rate; K5 rate.
- E4 (V5 against V5-weather and V5-satellite): rubric total by advice group, on the scenarios where the removed source
  is relevant.
- E5 (V5 − VC): critical-error rate and K4 rate (lower is better); rubric total as non-inferiority (section 7).
- Selective answering (V3, V4, V5): coverage, critical errors among given recommendations, share and justification of
  questions and abstentions, turns to the final act.
- Cost of asking: turns, model calls, tokens, time.

Strata (complete / missing input / unreliable input or conflicting sources) and advice groups are reported
descriptively; no interval is shown for a subset of fewer than 10 scenarios (`min_n_for_ci`).

## 4. Alpha and multiple comparisons

- alpha = 0.05, two-sided (95 % intervals). Proposed default, to be confirmed before the lock.
- Hierarchy: E1 is the only confirmatory test and is tested at the full alpha. The key secondary outcomes of the first lock are
  tested only after E1 and are reported with Holm-adjusted p-values (Wilcoxon signed-rank, supplementary;
  `evalkit/report.py:holm_family`) across the family listed in `analysis.yaml` (`holm.family`): E1-rubrika, E1-K1,
  E1-K2, E1-K3 and E1-prvi-cin (all V4 − V3). A member without variation (for example K1 while quantities are off) has
  no p-value and is not counted. Their intervals are unadjusted and described as such. E2-E5 are not in the first lock
  and not in the family; a later lock that adds them must list them in `holm.family` first. Earlier drafts of this plan
  named the family {E2, E3, E4, E5} and the code {E2, E3}; neither is the plan of the first lock. Proposed rule, to be
  confirmed.
- Nothing else is called significant.

## 5. Sample size and power

N = 40 test scenarios (plus 15 development scenarios used only for development and rater calibration). Two
independent generations per variant and scenario are averaged before any comparison; repeats are not independent
samples.

Power (**simulation estimate**, not a measurement: percentile bootstrap as in evalkit, 500 simulated experiments per
setting, assumptions stated):

| Outcome | Assumed effect | Estimated power |
|---|---|---|
| Critical-error rate, paired binary | V4 better in 25 %, worse in 5 % of scenarios (difference −0.20) | ≈ 0.66 |
| | 20 % / 5 % (−0.15) | ≈ 0.48 |
| | 15 % / 5 % (−0.10) | ≈ 0.29 |
| | −0.20 only outside the complete stratum (about 24 scenarios) | ≈ 0.45 |
| Rubric total, SD of paired differences 2 points | difference 1.0 | ≈ 0.90 |
| | 0.8 | ≈ 0.73 |
| | 0.5 | ≈ 0.36 |

What may be concluded: a large effect on the critical-error rate (about 20 percentage points or more, with few
scenarios in the opposite direction) and on the rubric. A moderate effect will most likely remain inconclusive, and an
interval that includes zero is reported as inconclusive, never as "no effect".

## 6. Bootstrap units (clusters)

The resampling unit is the scenario's `cluster` field; a scenario without it falls back to its parcel id
(`P.parcel_id`) and then to its own id (`evalkit/runner.py:cluster_of`), so scenarios on one parcel share a cluster. Whole clusters are resampled with replacement
(`evalkit/report.py:bootstrap_ci`). A cluster bootstrap over fewer than `min_clusters` clusters (`backend/config/analysis.yaml`, proposed default 5) is
**not estimable**: the report prints the point difference and the reason, never an interval, and no verdict (supported or
non-inferior) is drawn from it. With about ten clusters or fewer the cluster definition (base situation versus parcel x
date) is **TO BE DECIDED** before the lock, because a bootstrap over a few clusters gives an unusable interval.

## 7. Non-inferiority (E5)

**E5 is not in the first lock** (`scope.include_e5: false`): the report prints no E5 table and uses no margin. The
implementation stays, behind the switch, for a later lock. The text below is the design.

The rubric total of V5 is non-inferior to VC when the lower limit of the two-sided 95 % interval of V5 − VC (a
one-sided test at alpha/2 = 0.025) lies above −margin.

**Non-inferiority margin: TO BE DECIDED BY THE PROTOCOL OWNER** (`noninferiority.margin` in
`backend/config/analysis.yaml`, currently null). A margin must be locked before measurement; no value is
justified or assumed here. With a null margin the report does not evaluate the test and says why (status
`not_evaluated`); a margin that is not a positive number is an error. The justification (for example a minimal important difference agreed
with the agronomist) is written in this section when the margin is set.

## 8. Negative control: equivalence on the complete stratum

On scenarios with complete and reliable inputs (stratum `complete`, about 16) the sufficiency layer should change
nothing. This is tested as equivalence, not as "no difference": two one-sided tests (TOST) at alpha = 0.05, i.e. the
90 % percentile bootstrap interval of V4 − V3 on the rubric total must lie inside (−margin, +margin).

**Equivalence margin: TO BE DECIDED BY THE PROTOCOL OWNER** (`equivalence.margin` in `backend/config/analysis.yaml`,
currently null). Until it is set the report does not evaluate the test (it says the margin is not set) and draws no verdict.

## 9. Rater agreement

Two raters (the independent agronomist and a second rater) rate blind, each in a seeded order recorded with the
assignment (`evalkit assign`, `backend/eval/assignments/<rater>.json`). Agreement is reported on the items both rated:

- rubric criteria r1-r5 (0-2): quadratic-weighted kappa (Cohen, 1968) with a 95 % percentile bootstrap interval over
  items (2,000 resamples, seed 7), and the share of exact agreement;
- critical-error classes (any, K1-K5): unweighted kappa (Cohen, 1960) with the same interval, and percent agreement.

Kappa can be low at high agreement when the margins are skewed; percent agreement is always shown next to it. A
minimum acceptable agreement and the action if it is not reached are **TO BE DECIDED** before the lock.

## 10. Exclusions and failed runs

- An item whose model call failed, was answered by a model other than the pinned one, or (V0-V3) has no valid `act` in
  the model's output is an error item: it is stored, never rated, never replaced by template text, and makes the run
  exit non-zero. The affected scenario and
  variant are run again; the count of error items per variant is reported.
- No scenario is excluded after the lock. Rating is restricted to the items of the assignment; a report covers one
  scenario set and the named batches only (`evalkit report --set test --batch ...`).

## 11. What the lock binds

Protocol files (scenarios, corpus, `backend/config/*.yaml` including `evaluation.yaml` and `analysis.yaml`, the rater
guide, this plan, the generator prompt (V4, V5), the prompt of the variants whose act the model chooses (V0-V3), the
VC and judge prompts, the external-cache snapshot, which is mandatory for the test set) and the environment (git commit, sha256 of the source tree, `requirements.lock`, Python version, model ids and
generation settings, the generator the environment selects, embedding settings, grounding judge). See
`docs/reproducibility.md`.

## References

- Cohen, J. (1960). A coefficient of agreement for nominal scales. *Educational and Psychological Measurement*, 20(1),
  37-46.
- Cohen, J. (1968). Weighted kappa: Nominal scale agreement with provision for scaled disagreement or partial credit.
  *Psychological Bulletin*, 70(4), 213-220.
