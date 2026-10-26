# 0003. Offline first; no keys required

- Status: Accepted
- Date: 2026-10-21

## Context

A research artefact has to be checkable by people who have no API keys, no paid model access and possibly no
network, and a historical decision must not see data published after its decision time. External services change
their answers over time.

## Decision

- The default generator is the deterministic template (`LLM_PROVIDER` unset or `template`); a language model is
  optional.
- Dense retrieval is optional (`EMBEDDINGS_PROVIDER=fastembed`); the default is BM25 only.
- Satellite data are optional (Copernicus credentials); without them the NDVI inputs are reported as missing.
- Every external response goes through an external cache table (`providers/base.py`, `cached`).
  `SMARTAGRI_OFFLINE=1` answers only from that cache, and cache snapshots can be exported and imported
  (`python -m smartagri.cache`). A live forecast fetched more than an hour after the decision time is not used
  (`providers/weather.py`, `FORECAST_FETCH_GRACE`).
- Tests and CI run with `SMARTAGRI_OFFLINE=1` and the template generator.

## Consequences

- `pytest`, the development evaluation and `examples/advise_one_parcel.py` run in seconds without network or keys.
- Results obtained offline describe the decision layers with the template generator; language-model behaviour has
  to be measured separately ([limitations.md](../limitations.md)).
- A run that used live data can be repeated byte for byte only with its cache snapshot.
