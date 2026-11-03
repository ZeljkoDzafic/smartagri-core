# Evaluation protocol

## Variants

`backend/config/variants.yaml` defines an ablation ladder in which each rung adds exactly one layer of the design. The
layer of V4 is the explicit sufficiency-and-asking model (q, σ and α, introduced together by definition); the layer of
V5 is the decision policy and its grounding check (δ, γ):

| Variant | Adds |
|---|---|
| V0 | answer without retrieval, from the static parcel profile (no weather, no NDVI) |
| V1 | retrieval (BM25; fused with a dense ranking only when `EMBEDDINGS_PROVIDER=fastembed`) |
| V2 | applicability π over the conditions named in the question |
| V3 | dynamic parcel context: π reads the parcel's conditions, and the weather summary W and NDVI series S become visible |
| V4 | quality q, sufficiency σ and asking α (below V4 no input carries a reliability grade) |
| V5 | policy δ and grounding γ |
| V5-weather, V5-satellite | V5 with the weather summary or the NDVI series removed (context ablations) |
| VC | baseline outside the ladder: a free LLM conversation with the same context and the same applicable passages, without the decision model |

V0–V3 are a language model with the data their rung allows: the question, the parcel data (ungraded), the passages the
rung retrieves and the results of the calculation tools whose inputs the rung has (ETc, net and gross irrigation: numbers
come from code). The model chooses the act itself (recommend, conditional, ask or abstain) and states it in a required
output field; it receives no act, action, timing or other conclusion of the decision core. An output without a valid
act is an error item, never a default. With a language model these variants may also ask one free question per turn,
answered from the scenario's prepared replies exactly as for VC. V4 and V5 differ in who decides: the layers choose the
act and the model only phrases the answer, so the primary comparison E1 (V4 vs V3) measures the package (q, σ, α) together
with the change of the decision-maker from the language model to the rules.

The template generator has no language model. For V0–V3 it is only a deterministic fallback that always recommends and
shows the decision core's action; every such answer carries the label **"template, not a baseline"** in the run record,
in `evalkit report` and in the web evaluation view, and is never a result of the rung. The development set runs with the
template to check the pipeline. The full rung-to-layer map and the analysis plan are in [protocol.md](protocol.md).

Comparisons reported by `evalkit report`:

- **E1** V4 vs V3 (primary comparison: the effect of the sufficiency-and-asking model together with the change of who
  chooses the act; primary outcome: the share of scenarios with a K4 or K5 error);
- **E2** V3 vs V2 (parcel conditions and dynamic context), **E3** V5 vs V4 (δ, γ);
- **E4** context ablations (V5-weather, V5-satellite against V5);
- **E5** V5 vs VC (critical-error rate at a rubric score that is not worse: a non-inferiority test whose margin is
  set in `backend/config/analysis.yaml` before the lock).

## Measures

Blind rating with a rubric r1–r5 (0–2 each) and critical errors K1–K5 (see `docs/RATER_GUIDE.md`), act accuracy,
selective-answering behaviour, retrieval recall and citation coverage. Paired differences use bootstrap intervals
(10 000 resamples, cluster bootstrap by parcel where applicable). The negative control (V4 vs V3 on scenarios with
complete inputs) is an equivalence test (TOST); secondary comparisons carry Holm-adjusted p-values. Rater agreement
uses weighted Cohen's κ (Cohen, 1968) with a bootstrap interval. A report covers one scenario set and the named
batches (`report --set test --batch ...`); raters get their items through `evalkit assign`, in a seeded order that is
recorded in the assignment file together with the seed, the lock, the repetition rule and the subset. `assign` can rate one
repetition per scenario (`--repeat K`, or `--pick-repeat`: seeded) and a balanced subset (`--per-stratum N`: seeded, the
same scenarios for every rater). The blind rater sees the input facts without the reliability grades of the q layer
(`rater_view: raw` in `config/evaluation.yaml`; `graded` shows the quality table). The primary outcome is the rate of
scenarios with a K4 or K5 error; a cluster bootstrap over fewer than `min_clusters` parcels is reported as not estimable,
and a test whose margin is not set is reported as not evaluated. E5 (V5 against VC) is outside the first lock
(`scope.include_e5`). See [protocol.md](protocol.md).

## Reproducibility

The full procedure, including a clean install and what the lock records, is in
[reproducibility.md](reproducibility.md); the protocol is in [protocol.md](protocol.md). In short:

1. **Run without keys.** `pytest -q`, then `python -m smartagri.evalkit run --set dev && python -m smartagri.evalkit report`.
2. **Offline re-run.** Import the external-cache snapshot (`python -m smartagri.cache import <snapshot.tar>`), set
   `SMARTAGRI_OFFLINE=1`, and run again; every weather and satellite answer then comes from the snapshot.
3. **Report tables.** `python -m smartagri.evalkit report --format md` rebuilds every table from stored runs and
   ratings; no number is typed in by hand.

The protocol lock (`python -m smartagri.evalkit lock --set test --cache-snapshot <snapshot.tar>`) records sha256 of
the scenarios, the corpus, `backend/config/`, the prompts (generator, VC, judge), the rater guide, the analysis plan
and the cache snapshot (mandatory for the test set), and binds the environment: git commit, a hash of the source tree,
`requirements.lock`, the Python version, the model settings and the generator the environment selects. Every run
stores the hashes it used.
Held-out test scenarios (`backend/eval/scenarios/test/`) are published only after the lock. Until then the leakage
guard (`evalkit guard`) keeps their text out of the corpus and the index.
