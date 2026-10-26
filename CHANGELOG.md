# Changelog

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html). While the major version is 0, a minor version may
change the decision model, the configuration or the evaluation protocol; such changes are listed under **Changed**
with the files they touch.

A release is a git tag `vX.Y.Z` whose version matches `backend/pyproject.toml`, `CITATION.cff` and a heading below.
The release workflow (`.github/workflows/release.yml`) publishes the section of that heading as the release notes.

## [Unreleased]

## [0.2.0] - 2026-10-26

This version changes the decision model's ablation ladder, the evaluation harness and the configuration that the
protocol lock covers. The protocol was not locked before it; no results were reported with 0.1.0.

### Added
- Web app on a map: draw, paste or import a parcel polygon, fetch its profile, see every input with origin, age and
  reliability, ask under any variant V0–V5, answer the follow-up question and inspect the π, q, σ, α, δ and γ
  decisions with their provenance hashes.
- Parcel views: stored weather and Sentinel-2 NDVI series with source and age, a daily root-zone balance shown as an
  illustration (not used by the advice), a read-only evaluation overview and a provenance export (JSON) per answer.
- Optional accounts for a public deployment (`SMARTAGRI_ACCOUNTS=optional`): temporary anonymous parcels kept for a
  browser session and saved with an account, rate limits, CSRF check, expiring sessions, optional SMTP for
  confirmation and password reset.
- English answers in the web app and API by default (`SMARTAGRI_LOCALE`), with the Serbian (Latin script) interface
  catalogue; optional soil texture as an input.
- Container image (`Dockerfile`) and a deployment guide (`docs/deployment.md`).
- Static presentation website (`website/`) with deployment to Cloudflare and, by hand, to GitHub Pages.
- Continuous integration: lint, tests on Python 3.9 and 3.12, the leakage guard on the development set, a dependency
  audit of `requirements.lock`, a website check and a container health check.
- Release and citation files: `CHANGELOG.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `AUTHORS.md`,
  `NOTICE`, `.zenodo.json`, a completed `CITATION.cff` and a tag-driven release workflow.
- Documentation: layer map (`docs/layers.md`), limitations (`docs/limitations.md`), reproducibility
  (`docs/reproducibility.md`) and architecture decision records (`docs/adr/`).
- Runnable offline example `examples/advise_one_parcel.py`, executed in CI.
- Analysis plan `docs/protocol.md` (one primary outcome, secondary outcomes, alpha, multiplicity, N, a simulated power
  estimate, bootstrap clusters, non-inferiority and equivalence tests, weighted kappa with interval) and its
  machine-readable parameters `backend/config/analysis.yaml`; margins not yet decided stay null and the report gives
  no verdict for them.
- Statistics in `evalkit/report.py`: non-inferiority (one-sided bootstrap), equivalence (TOST), bootstrap interval for
  Cohen's kappa, Holm adjustment.
- `evalkit assign`: items of one scenario set (and batches) assigned to a rater in a seeded order, written with its
  sha256; `report`, `export` and the rating queue take `--set` / `--batch` and never mix sets.
- Pinned model settings of an evaluation run, `backend/config/evaluation.yaml` (exact model id, effort, output limit,
  no server-side fallback).

### Changed
- Ablation ladder: each rung adds exactly one layer. `dynamic_context` now removes the weather summary and the NDVI
  series for V0–V2; without the q layer inputs are "ungraded" instead of "high"; V0–V3 may ask one free question per
  turn when a language model is used (`config/variants.yaml`, `pipeline/run.py`, `core/quality.py`,
  `pipeline/generate.py`, `evalkit/runner.py`).
- Protocol lock format `smartagri-protocol-lock/2`: it also hashes the analysis plan and the judge prompt, requires a
  cache snapshot for the test set, and binds the environment (commit, source-tree hash, `requirements.lock`, Python,
  model settings, generator selection); `run --locked` refuses any difference.
- An evaluation run fails loudly: a failed or substituted model call is an error item and the run exits non-zero; no
  template fallback. Each item records the model that actually answered, the provider's request ids and tokens.
- Historical weather: forecast days of a past decision time come from the Open-Meteo Previous Runs API, using only runs
  available at that time; the historical-forecast archive is used only for past days (`providers/weather.py`).
- Report tables of comparison E5 use neutral names (`table_e5`, `E5_PAIR`); the rater guide header and source
  references point to `docs/protocol.md`.
- Environment variables, loggers and the request-header value use `smartagri` names; the former names are still read.
- CI runs on Ubuntu 26.04; the Python 3.9 job stays on Ubuntu 24.04 because no prebuilt Python 3.9 exists for 26.04.
- README: the four acts are stated as recommend, conditional, ask and abstain (a referral is attached to some
  abstentions, it is not an act); the answer language, the handling of `.env` and the retrieval default (BM25,
  dense ranking only when configured) are stated as the code implements them.

### Fixed
- A reply on a parcel with a fixed decision date is dated at that date, not at the day it was given.
- `applicability: off` in `variants.yaml` was read by YAML as the boolean false, so V1 applied π from the question like
  V2; mode values are now strings.
- `run --set dev --scenarios-dir <folder with protected scenarios>` no longer bypasses the protocol lock.

### Security
- Pinned dependencies raised past known advisories (certifi, pillow, fastembed, filelock, pypdf).

## [0.1.0] - 2026-10-21

First public version of the core. It was published without a git tag; the first tagged release is 0.2.0.

### Added
- Decision model with explicit, deterministic layers: applicability π of knowledge passages, input quality q,
  sufficiency σ, choice of the next question α, decision policy δ and grounding checks γ.
- Retrieval over the corpus: BM25, optionally fused with a dense ranking by reciprocal rank.
- Agronomic tools computed in code: ETc = Kc × ET0, a simplified root-zone balance, gross depth = net / efficiency,
  phenology estimate, NDVI summary.
- Language model provider adapters; the deterministic template generator is the default.
- Evaluation harness (`python -m smartagri.evalkit`): runs over scenario sets, ablation variants, blind rating
  queue, reports with bootstrap intervals and rater agreement, leakage guard, sweep and protocol lock.
- Minimal research HTTP API and client.
- Configuration (`backend/config/`), a development corpus with its manifest and development scenarios.

### Fixed
- Locked configuration files kept byte-identical apart from required comment changes.

[Unreleased]: https://github.com/ZeljkoDzafic/smartagri-core/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/ZeljkoDzafic/smartagri-core/releases/tag/v0.2.0
[0.1.0]: https://github.com/ZeljkoDzafic/smartagri-core/commit/53a1534
