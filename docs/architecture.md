# Architecture overview

## Flow of one question

1. **Context C.** The parcel (GeoJSON polygon, crop, sowing date or BBCH stage, optional agronomic inputs) and its
   input profile: daily weather from Open-Meteo and Sentinel-2 L2A NDVI statistics. For a decision at the present
   time the weather comes from the forecast endpoint. For an earlier decision time the days before it come from the
   historical-forecast archive (near-analysis values of past days), and the forecast days from the Previous Runs API:
   for every hour only the value of a model run that was available at the decision time is used (a run is taken as
   issued 24 h x N before the valid hour and available 6 h later; incomplete days stay missing). Such a profile is
   labelled `retrospective_constructed` (`providers/weather.py`). Scenarios whose weather is written by hand keep it.
   The NDVI statistics come
   from the Copernicus Statistical API with a per-pixel SCL cloud mask. Weather and NDVI reach a variant only from
   rung V3 on (`dynamic_context`, `pipeline/run.py`). Each observation keeps its `obs_date` and
   the share of usable pixels (`usable_share`, shown as `valid_px_ratio`); there is no separate per-observation
   `cloud_flag`, because cloudy pixels are masked and counted in that share.
2. **Quality q.** Each input gets origin, age, coverage and reliability; thresholds come from
   `backend/config/thresholds.yaml`. Variants without the q layer (V0–V3) grade nothing: present inputs are
   "ungraded", never "high".
3. **Intent.** Deterministic keyword rules classify the type of advice (`pipeline/intent.py`), no LLM.
4. **Retrieval.** BM25 (diacritics-folded, light stemming); with `EMBEDDINGS_PROVIDER=fastembed` also a dense
   ranking, fused with BM25 by reciprocal rank. The default is BM25 only.
5. **Applicability π.** A deterministic filter and re-rank over passage metadata (crop, stage, region, date, source
   type). It never calls a language model.
6. **Sufficiency σ and asking α.** Required inputs per advice type (`config/requirements.yaml`); when something is
   missing or unreliable, α picks the question with the largest effect on the decision (`config/asking.yaml`).
7. **Policy δ.** One of four acts: recommend, conditional, ask or abstain. An abstention for an out-of-scope
   question or an insufficient corpus carries a referral to the extension service; the referral is not a separate
   act. δ also decides whether a quantity may be shown; the template answers never state a quantity or dose without
   that permission, never infer the cause of a vegetation change from an index alone and never prescribe a
   plant-protection product (for a language model these are prompt instructions; see
   [limitations.md](limitations.md#scope)).
8. **Tools.** ETc = Kc × ET0 with FAO-56 crop coefficients, a simplified root-zone balance, gross depth = net /
   efficiency, phenology; tested in code. See [layers.md](layers.md) for the map of layers and tools to code,
   configuration and tests.
9. **Generation and grounding γ.** A deterministic template by default; optionally an LLM provider (Anthropic,
   OpenAI-compatible endpoints, local models) phrases the text. In an evaluation run the model id (exact, never an
   alias), effort and output limit come from `backend/config/evaluation.yaml`, no server-side model fallback is sent,
   and a failed call is stored as an error item and makes the run exit non-zero; it is never replaced by template
   text. Numbers that are not supported by a tool output are
   rejected; sentences without passage support are removed (lexical check, optional LLM entailment judge).

Every answer carries `{act, action, time/condition, data + age + reliability, sources + π status, next question}`
and is stored with the hashes of config, corpus and prompts that produced it.

## Storage

SQLite (default, tests) or PostgreSQL (`DATABASE_URL`); records are JSON with key columns. Every external response
goes through the `external_cache` table, and `SMARTAGRI_OFFLINE=1` answers only from that cache, so a run can be
repeated byte for byte from a cache snapshot.

## Packages

| Package | Role |
|---|---|
| `core/` | types, π, q, σ, α, δ, rules, conflicts, grounding, FAO-56 tools |
| `retrieval/` | corpus loading, BM25, vectors, fusion, ingest, coverage |
| `providers/` | Open-Meteo weather, Sentinel-2 statistics |
| `pipeline/` | intent, profile, run (variants), generation, judge, LLM chat baseline |
| `llm/` | provider interface and adapters (template, Anthropic SDK, OpenAI-compatible, local CLI, HTTP bridge) |
| `evalkit/` | scenario runner, rating queue, reports, leakage guard, sweep, protocol lock |
| `research_api/` | minimal FastAPI app and static one-page client |
