# Architecture overview

## Flow of one question

1. **Context C.** The parcel (GeoJSON polygon, crop, sowing date or BBCH stage, optional agronomic inputs) and its
   input profile: daily weather from Open-Meteo (forecast, archive, or the forecast as it was available at the
   decision time via the previous-runs API) and Sentinel-2 L2A NDVI statistics from the Copernicus Statistical API
   with a per-pixel SCL cloud mask (`obs_date`, `valid_px_ratio`, `cloud_flag` are stored with every value).
2. **Quality q.** Each input gets origin, age, coverage and reliability; thresholds come from
   `backend/config/thresholds.yaml`.
3. **Intent.** Deterministic keyword rules classify the type of advice (`pipeline/intent.py`), no LLM.
4. **Retrieval.** BM25 (diacritics-folded, light stemming) and optional vector search, fused by reciprocal rank.
5. **Applicability π.** A deterministic filter and re-rank over passage metadata (crop, stage, region, date, source
   type). It never calls a language model.
6. **Sufficiency σ and asking α.** Required inputs per advice type (`config/requirements.yaml`); when something is
   missing or unreliable, α picks the question with the largest effect on the decision (`config/asking.yaml`).
7. **Policy δ.** recommend, conditional, ask, abstain or refer, with fixed prohibitions (no quantity or dose without
   sufficient inputs, no cause of a vegetation change from an index alone, no plant-protection prescription).
8. **Tools.** FAO-56 ETc = Kc × ET0, water balance, gross dose = net / efficiency, phenology; tested in code.
9. **Generation and grounding γ.** A deterministic template by default; optionally an LLM provider (Anthropic,
   OpenAI-compatible endpoints, local models) phrases the text. Numbers that are not supported by a tool output are
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
