# SmartAgri core

SmartAgri is an open, testable core for **active, uncertainty-aware agronomic advice**. It answers a farmer's
question about one parcel (maize) and decides, before any text is generated, whether it may advise at all: recommend,
give a conditional answer, ask a follow-up question, abstain, or refer to an expert.

The decision is made by explicit, deterministic layers; a language model (optional) only phrases the answer.

- **C** the decision context: parcel, agronomic inputs, Open-Meteo weather and Sentinel-2 L2A NDVI;
- **π** applicability of each knowledge passage (deterministic filter over passage metadata: crop, stage, region,
  date, source type);
- **q** quality of each input (origin, age, coverage, reliability);
- **σ** sufficiency of the inputs for the requested type of advice;
- **α** choice of the next question;
- **δ** the decision policy (recommend, conditional, ask, abstain, refer);
- **γ** grounding checks of the answer (numbers come from tools, sentences must be supported by passages).

Agronomic numbers are computed in code (FAO-56: ETc = Kc × ET0, water balance, gross dose = net / efficiency), never
by the language model.

## Contents

| Path | What |
|---|---|
| `backend/src/smartagri/core/` | decision model π, q, σ, α, δ, FAO-56 tools, grounding |
| `backend/src/smartagri/retrieval/` | corpus loading, BM25 + vector retrieval with rank fusion, corpus ingest and coverage |
| `backend/src/smartagri/pipeline/`, `providers/`, `llm/` | answer generation and judge, weather and satellite adapters, LLM providers |
| `backend/src/smartagri/evalkit/` | `python -m smartagri.evalkit run / report / export / guard / sweep / lock` |
| `backend/src/smartagri/research_api/` | minimal HTTP API and one-page client (parcels, profile, advice, provenance, blind rating) |
| `backend/config/` | rules, thresholds, variants, question bank, Kc table (locked with the evaluation protocol) |
| `backend/corpus/` | corpus manifest (licence per document) and passages |
| `backend/eval/scenarios/dev/` | development scenarios; held-out test scenarios are published only after the protocol lock |
| `docs/` | architecture overview, evaluation protocol, rater guide |

## Install and test

Python 3.9 or newer. Docker is not required.

```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -c constraints-py39.txt -e ".[dev,api]"      # Python 3.12: -c requirements.lock
pytest -q                                                # SQLite, offline; no keys needed
```

`.env.example` lists the optional settings: LLM provider, Copernicus credentials and offline mode. Without any of
them the system uses the deterministic template generator and works without network access to models.

## Run

```bash
cd backend && . .venv/bin/activate
python -m smartagri.research_api            # http://127.0.0.1:8100 — local use, no accounts
```

The page lets you add a parcel (GeoJSON polygon) and fetch its profile, see the quality table q, ask a question under
any variant V0–V5, answer the follow-up question, and open "Zašto?" to see the π/q/σ/α/δ decisions and their
provenance. The VC chat (a free LLM conversation with the same data and sources) needs `LLM_PROVIDER`.

## Evaluation

`evalkit` runs an ablation ladder of variants V0–V5 (each rung adds one layer) and the LLM baseline VC over scenario
sets, and supports blind rating, bootstrap intervals, rater agreement, a leakage guard and a protocol lock.
See [`docs/evaluation.md`](docs/evaluation.md).

```bash
python -m smartagri.evalkit run --set dev && python -m smartagri.evalkit report
```

## Corpus licences

`backend/corpus/manifest.yaml` gives the source, URL and licence of every document. The published passages are short
paraphrases with citations, or the author's own notes. A document whose licence does not allow redistribution is
published as metadata only (title, URL, licence); the corpus hash recorded in every run lets you check a locally
rebuilt corpus.

## Data sources and standards

FAO Irrigation and Drainage Paper 56 (crop coefficients, ET0, water balance), BBCH growth stages, Open-Meteo
(forecast, historical and previous-runs APIs), Copernicus Data Space Ecosystem (Sentinel-2 L2A, Statistical API),
OpenStreetMap. Each keeps its own licence and terms.

## Licence

MIT (`LICENSE`). Cite with `CITATION.cff`. A commercial product built on this core is developed separately; it is
not needed to run, check or reproduce anything here.
