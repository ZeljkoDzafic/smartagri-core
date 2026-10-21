# Evaluation protocol

## Variants

`backend/config/variants.yaml` defines an ablation ladder; each rung adds one layer to the previous one:

| Variant | Adds |
|---|---|
| V0 | answer without retrieval |
| V1 | hybrid retrieval (BM25 + vectors) |
| V2 | applicability π over the conditions named in the question |
| V3 | π over the parcel's conditions, with the dynamic context C (weather, satellite) |
| V4 | quality q, sufficiency σ and asking α |
| V5 | policy δ and grounding γ |
| V5-weather, V5-satellite | V5 with the weather summary or the NDVI series removed (context ablations) |
| VC | baseline outside the ladder: a free LLM conversation with the same context and the same applicable passages, without the decision model |

Comparisons reported by `evalkit report`:

- **E1** V4 vs V3 (primary comparison: the effect of q, σ, α);
- **E2** V3 vs V2 (parcel conditions and dynamic context), **E3** V5 vs V4 (δ, γ);
- **E4** context ablations (V5-weather, V5-satellite against V5);
- **E5** V5 vs VC (critical-error rate at a rubric score that is not worse).

## Measures

Blind rating with a rubric r1–r5 (0–2 each) and critical errors K1–K5 (see `docs/RATER_GUIDE.md`), act accuracy,
selective-answering behaviour, retrieval recall and citation coverage. Paired differences use bootstrap intervals
(10 000 resamples, cluster bootstrap by parcel where applicable); rater agreement uses weighted Cohen's κ.

## Reproducibility

1. **Run without keys.** `pytest -q`, then `python -m smartagri.evalkit run --set dev && python -m smartagri.evalkit report`.
2. **Offline re-run.** Import the external-cache snapshot (`python -m smartagri.cache import <snapshot.tar>`), set
   `SMARTAGRI_OFFLINE=1`, and run again; every weather and satellite answer then comes from the snapshot.
3. **Report tables.** `python -m smartagri.evalkit report --format md` rebuilds every table from stored runs and
   ratings; no number is typed in by hand.

The protocol lock (`python -m smartagri.evalkit lock --set test`) records sha256 of the scenarios, the corpus,
`backend/config/`, the prompts, the rater guide and the optional cache snapshot; every run stores the hashes it used.
Held-out test scenarios (`backend/eval/scenarios/test/`) are published only after the lock. Until then the leakage
guard (`evalkit guard`) keeps their text out of the corpus and the index.
