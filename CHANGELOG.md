# Changelog

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html). While the major version is 0, a minor version may
change the decision model, the configuration or the evaluation protocol; such changes are listed under **Changed**
with the files they touch.

A release is a git tag `vX.Y.Z` whose version matches `backend/pyproject.toml`, `CITATION.cff` and a heading below.
The release workflow (`.github/workflows/release.yml`) publishes the section of that heading as the release notes.

## [Unreleased]

### Added
- Web settings: every agronomic parameter of `rules.yaml`, `kc_maize.yaml`, `thresholds.yaml`, `asking.yaml`,
  `requirements.yaml` and `parcel_features.yaml` can be set through the web app at three levels (global by an
  administrator, user, parcel) over the file defaults, with a registry that describes each parameter (label in English
  and Serbian, unit, type, range, recommended values, source and status), an editing form generated from it, table
  editors, per-parameter and whole-set reset, versions with restore, an append-only audit log, administrator limits
  (user-editable switch, allowed range, shape) and the locked protocol files shown read only. Storage: migration
  `0015` (additive tables; append-only triggers on versions and audit log). API under `/api/settings`. Administrators:
  `SMARTAGRI_ADMINS` with `SMARTAGRI_ACCOUNTS=optional`; the local user with `off`. See `docs/settings.md`.
- A "settings used" block in the provenance of every web answer (version, hash, overrides with their level), in the
  "Why?" panel and in the JSON export.
- `config.use_overlay` / `config.load_file`: a per-request, context-variable overlay of settings over the file data.
  Without an overlay `config.load()` returns the cached file data, `evalkit` and the protocol lock read the files only,
  and the file hashes are unchanged.
- Parcel features: the `parcel_features` data contract (schema version 1, JSON Schema in `docs/parcel-features.md` and in
  `core/parcel_features.py`), a validator, a geometry hash and the producer's hashes, a generic provider interface that
  reads precomputed files (`providers/parcel_features.py`, `SMARTAGRI_PARCEL_FEATURES_DIR`), loading from scenario files
  (`context.S.parcel_features`) and from the research API. Only observations dated before the decision moment are
  accepted. The features live inside S, so the `V5-satellite` ablation removes them.
- NDVI observation quality metadata: cloud and shadow shares, `cloud_flag` (now stored), interior buffer and pixel
  counts, mixed-pixel share and temporal-outlier screening; q lowers the grade by thresholds in
  `config/parcel_features.yaml` (development defaults). The web client shows them in the data-and-reliability card and
  the NDVI table (English and Serbian catalogues).
- Stage-conflict rule in q: when the stage in use disagrees with a satellite stage interval beyond a tolerance, the
  stage reliability is capped at low and the conflict is recorded (quality row, `Decision.input_conflicts`, provenance).
  It acts through σ, α and π; it is dormant until a document carries a stage estimate.
- Consumer side of a crop plausibility check and of bare-soil and harvest markers, switched off
  (`enabled: false`): recorded in the provenance, no effect on any decision.
- `docs/parcel-features.md`; a section in `docs/layers.md` and `docs/limitations.md`.

### Changed
- V0–V3 are an LLM with the data their rung allows (decision D11): the language model of a variant without the
  sufficiency layer no longer receives the decision core's act, action, timing or any other conclusion (D_t); it
  chooses the act itself and states it in the required field `act`. Its fact sheet holds the question, the parcel data
  (ungraded below V4), data statements without the core's conclusions, the limitations, the retrieved passages and the
  results of the calculation tools the rung's inputs allow (numbers from code stay available). A new prompt
  (`SYSTEM_PROMPT_FREE`, `FREE_PROMPT_HASH`) and schema (`ANSWER_SCHEMA_FREE`) serve these variants and join the protocol
  lock as `prompt/generator_free_act`; the V4/V5 prompt (`PROMPT_HASH`) and every decision of the core are unchanged.
  An output without a valid act is an error item in an evaluation (never a default). Files: `pipeline/generate.py`,
  `pipeline/run.py`, `evalkit/__main__.py`, `docs/protocol.md` (section 1.1).
- The template answer of V0–V3 is labelled "template, not a baseline" (answer field `baseline_label`, run record field
  `baseline`, `evalkit report` JSON and tables, `evalkit run` notice, web evaluation view). It always recommends and is a
  fallback for checking the development set, not a result of the rung. The dev-run digests of V0–V3 changed by that
  label only; V4, V5 and the ablations are byte-identical.
- E1 (V4 vs V3) is documented as measuring the package (q, σ, α) together with the change of who chooses the act.
- The open core no longer carries the name or environment prefix of other products or numbered references to internal
  specifications; the website says "six layers" and that V4 adds q, σ and α as one package.
- The research API computes profile, advice, free conversation, series and water balance with the caller's effective
  settings. With no overrides the decisions are byte-identical to the previous version (checked on every development
  scenario and variant); the blind rating endpoints and evaluation are unchanged.
- `config/parcel_features.yaml` is a new configuration file: it is hashed in `config.config_hashes()` (a seventh key) and
  bound by the protocol lock, so the lock fingerprint and every run's `config_hashes` differ from 0.2.0. No act of the
  development scenarios changes; the dev-set decisions are identical apart from the new hash.
- `Quality` has an optional `detail`, `Observation` an optional `detail`, `NdviObservation` optional quality fields,
  `SatelliteSummary` an optional `parcel_features`, `Decision` an `input_conflicts` list; all default to empty.
- π reads the crop check through the input `crop_identity` when it exists (only when the crop plausibility check is
  switched on); otherwise the crop check is unchanged.
- Web settings: every numeric parameter has a default limit (what is accepted until an administrator sets a limit) and a
  recommended range, both inside the physical bounds, which were the only bounds before. A range of a cited source is
  used where the source gives one (largest net depth per irrigation, water capacity per texture, Kc, nitrogen share of
  four fertilisers); everywhere else the range is a development band around the file default and says so. The client
  warns while typing and after saving when a value leaves the recommended range, and every answer computed with a
  non-default setting shows "Custom settings applied" on the card and in the "Why?" panel (`provenance.settings` gains
  `outside_recommended`). The API of `GET /api/settings` adds `default_limit`, `range_basis` and per-slot `bounds`.
- The decision regression of the settings code compares the development scenarios against stored digests
  (`backend/tests/golden_dev/`, rewritten only by `python tests/golden_dev/update.py`), and a test runs two requests
  with different settings at the same moment.

### Security
- **Administrator bootstrap.** With accounts on and SMTP off, registering an address listed in `SMARTAGRI_ADMINS` no longer
  makes the account an administrator (it did: the first sign-up with the owner's address got the role and locked the
  owner out). An administrator is now an account the operator promoted on the server with
  `python -m smartagri.research_api --make-admin EMAIL` (also `--revoke-admin`, `--reset-password`; recorded in the audit
  log), or an account whose listed address was confirmed through its mailbox. A listed address cannot be registered over
  HTTP without SMTP; with SMTP the mail to a listed address sets the password instead of confirming a password chosen at
  sign-up. An account taken by someone else is taken over by the operator command.
- **Client address behind a proxy.** `FORWARDED_ALLOW_IPS=*` (advised by the deployment guide) made uvicorn take the leftmost
  `X-Forwarded-For` entry, which the client chooses, so the per-address limits of sign-in, sign-up, reset and settings
  writes could be walked around. The app now reads the header itself, only from the proxies in the new
  `SMARTAGRI_TRUSTED_PROXIES` (default: none), from the right; uvicorn's own proxy handling is off. The guide, the nginx
  example (`X-Forwarded-For $remote_addr`) and the image are changed accordingly.
- **Request limits.** A body over `SMARTAGRI_MAX_BODY_BYTES` (default 256 KiB) is refused with 413, JSON nested deeper than
  32 levels or with `NaN`/`Infinity` with 400, a polygon has at most 500 positions, and malformed input is answered 400
  (a wrong type, an impossible date, a growth stage outside 0-99, a name over 120 characters) instead of 500 or a stored
  parcel that fails on every later call.
- **Security headers.** `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options` and a restrictive
  `Content-Security-Policy` (own files and the map tile host only, `frame-ancestors 'none'`) on every response.
- **Settings limits.** The web settings accept only values inside default limits narrower than the physical bounds (a wind
  limit for spraying of 40 m/s or a rain wait of 0 mm used to be accepted); see Added.
- Not changed, listed as open items in `docs/deployment.md`: limits on outbound provider calls and on language-model
  spending, and on the number of parcels per owner.

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
