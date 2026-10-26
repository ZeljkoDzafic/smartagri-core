# SmartAgri core

[![ci](https://github.com/ZeljkoDzafic/smartagri-core/actions/workflows/ci.yml/badge.svg)](https://github.com/ZeljkoDzafic/smartagri-core/actions/workflows/ci.yml)

SmartAgri is an open, testable core for **active, uncertainty-aware agronomic advice**. It answers a farmer's
question about one parcel (maize) and decides, before any text is generated, whether it may advise at all: recommend,
give a conditional answer, ask a follow-up question, or abstain (with a referral to the extension service when the
question is out of scope or the corpus does not cover it).

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
| `backend/src/smartagri/research_api/` | minimal HTTP API and the web app (map drawing, profile, advice, provenance, blind rating) |
| `backend/config/` | rules, thresholds, variants, question bank, Kc table (locked with the evaluation protocol) |
| `backend/corpus/` | corpus manifest (licence per document) and passages |
| `backend/eval/scenarios/dev/` | development scenarios; held-out test scenarios are published only after the protocol lock |
| `docs/` | architecture overview, evaluation protocol, rater guide |
| `website/`, `tools/check_presentation_site.py` | static presentation site and its check (published manually to GitHub Pages) |

## Install and test

Python 3.9 or newer. Docker is not required.

```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -c constraints-py39.txt -e ".[dev,api]"      # Python 3.12: -c requirements.lock
pytest -q                                                # SQLite, offline; no keys needed
```

`.env.example` lists the optional settings: LLM provider, Copernicus credentials, offline mode and the answer
language (`SMARTAGRI_LOCALE`, default `en`). Without any of
them the system uses the deterministic template generator and works without network access to models.

## Run

```bash
cd backend && . .venv/bin/activate
python -m smartagri.research_api            # http://127.0.0.1:8100 — local use, no accounts
```

## Web app

![SmartAgri web app: the question "When should I irrigate?" and an answer card with a conditional recommendation, its follow-up question, the reasoning, the calculations and the data used with their reliability](website/assets/images/web-advice.png)

Open `http://127.0.0.1:8100`. Draw a parcel on the map (or paste or import a GeoJSON polygon), fetch its profile and
see each input with its origin, age and reliability (q), ask a question under any variant V0–V5, answer the
follow-up question, and open "Why?" to see the π, q, σ, α, δ and γ decisions and the provenance hashes.

Answers are in English by default. `SMARTAGRI_LOCALE=sr-Latn` switches the answers to the local language (Latin
script); a browser can also choose it in Settings (sent as `X-SmartAgri-Lang`). Questions are recognised in English
and in the local language. Sources are quoted in their original language: the passages of the published corpus are
short paraphrases in Serbian, so source titles and excerpts appear in Serbian. Evaluation runs never go through the
API and always use the default locale, so the answer language does not change any result. The VC chat (a free LLM
conversation with the same data and sources) answers in the language of the message and needs `LLM_PROVIDER`. The
blind rating screen shows only the blinded item and the rubric, in the wording of the rater guide.

The client has no build step and loads nothing from a CDN; Leaflet 1.9.4 is vendored with its licence
(`research_api/static/vendor/leaflet/`). OpenStreetMap tiles are its only external request:
`SMARTAGRI_TILE_URL` sets another tile server (`none` turns tiles off; drawing still works) and
`SMARTAGRI_TILE_ATTRIBUTION` its attribution. Light and dark themes follow the system or the settings sheet.

## Website

A static presentation of the project lives in [`website/`](website/) and is meant for
<https://zeljkodzafic.github.io/smartagri-core/>. It is published only by running the
`Deploy website to GitHub Pages` workflow by hand; see [`website/README.md`](website/README.md).

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
