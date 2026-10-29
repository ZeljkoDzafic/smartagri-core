# Limitations

This page lists what the current version does **not** do, or does only in a simplified way. Each item names the
file where the behaviour can be checked. Paths are relative to `backend/`. The list is part of the documentation of
any result produced with this version; results should be read together with it.

## Corpus

- **Development corpus only.** `corpus/passages.yaml` holds 22 passages from 4 documents (`corpus/manifest.yaml`);
  18 of them are marked `verify: true`, that is, not yet checked against their source. One document (`dev_notes`)
  is the developer's own notes and is labelled "not an expert source". The manifest header states that this corpus
  exists so that the system runs end to end and that it is not the corpus of an experiment.
- **One language.** Passages are paraphrases in Serbian. An English question is mapped to its advice type and
  retrieved with the canonical local question of that type (`research_api/service.py`, `labels_en.py`,
  `LOCAL_QUERIES`), so English retrieval quality is not measured separately.
- **Retrieval default is BM25 only.** Dense ranking and rank fusion are used only with
  `EMBEDDINGS_PROVIDER=fastembed` (`retrieval/embed.py`, `make_embedder`; `retrieval/__init__.py`,
  `make_retriever`). The value `retrieval: hybrid` in `config/variants.yaml` names the intended mode; the effective
  mode depends on that setting.

## Input checks

- **Plausible ranges are development values.** `rules.input_limits` only catches values that cannot be right (a percentage
  for a fraction, metres for mm/m, a negative rain); it does not judge unusual values. The AWC range (20-300 mm/m) spans
  FAO-56 Table 19 (50-200 mm/m by texture); the other ranges are engineering choices awaiting agronomist review.
- **Heavy rain.** The 25 mm threshold that postpones field work and top-dressing is a development value; it applies to the
  3-day (else 7-day) forecast total and does not distinguish intensity or soil.
- **Ages are calendar days.** A forecast issued 23 h before the decision can be one day old, one issued 25 h before can be
  one day old as well (audit D8, proposal: ages in hours, `max_age_hours`; not done because it changes the meaning of
  every `max_age_days` in `thresholds.yaml`). Satellite publication lag (D9) is not modelled: a scene of the previous
  day is assumed available.
- **Grounding by value (D14)** accepts a number that appears anywhere in the context; the lexical support check does not
  see negation. Both stay as limits of gamma.
- **Reply parsing** is rule-based Serbian; English replies use a separate, simpler parser (`pipeline/intent_en.py`) that
  has not had these fixes. The research API confirms every free-text value before writing it.

## Agronomic parameters

- **Development defaults, not reviewed.** `config/rules.yaml` begins with "PLACEHOLDER VALUES for development";
  `config/thresholds.yaml` with "INITIAL VALUES, NOT LOCKED". Thresholds for rain, late season, root depth, AWC by
  texture, irrigation efficiency, fertilization windows and field operations, and the quality grades of q, are
  development values pending agronomic review.
- **Kc values.** `config/kc_maize.yaml` takes Kc ini 0.30, Kc mid 1.20 and Kc end 0.60 from FAO-56 Table 12, uses
  0.75 as a midpoint for the development stage, and is marked "VERIFY against the source".
- **Depletion by soil-water status.** The net irrigation need maps a qualitative status (dry, moist, wet) to a
  fixed fraction of total available water (`core/tools/water_balance.py`, `DEPLETION_BY_STATUS`, marked as a
  placeholder).
- **Region classes.** `geo.py` (`region_class`) assigns `pannonian`, `mediterranean` or `hilly_mountain` from latitude
  and elevation with a placeholder rule.

## Web settings

- **Settings are not approvals.** A web setting changes a value; it does not change its review status. The status
  shown next to a parameter (verified, partly verified, disputed, no source, development value) comes from a comparison
  of the constants with the cited documents on one date, read through a summary of the pages; the numbers of the printed
  tables should be compared once more before a protocol is locked. The recommended ranges are given only where a source
  gives a range, so most parameters have none and a value outside the source's typical range is not flagged.
- **Some constants are not parameters.** The depletion fractions per soil-water class, the small-parcel limit, the NDVI
  trend minimum share, the factor of 5 for heavy rain in the decision core and the two-day horizon of "irrigate soon"
  are in code, not in a file, and cannot be set through the web. The same holds for the open agronomy issues: bands of
  the soil sensor that depend on texture, a nitrogen cap in kg N/ha, interpolation of Kc through the late stage and a
  soil-temperature check for sowing need code changes ([settings.md](settings.md)).
- **Tables are edited as a whole.** A list, a map or a table is one parameter; a user who edits one row owns the whole
  table, and the file's later changes to other rows are then not picked up at that level.
- **Stored profiles.** A parameter that acts when a profile is built (the base temperature of the growing-degree-day
  sum) applies when the profile is refreshed; the quality rows of an already stored profile reflect the settings of
  that moment, while every answer is decided with the current settings.
- **Evaluation is not affected, by design.** Results of `evalkit` never reflect web settings, so a setting that helps in
  the web app says nothing about the evaluation.
- **Concurrent edits.** Two administrators editing the same level are protected only if the client sends
  `base_version`; the web client does.

## Parcel features

- **No satellite stage estimator.** The stage-conflict rule of q (`core/parcel_features.py`, `stage_conflict`) compares the
  stage in use with a satellite stage interval carried by a `parcel_features` document. The estimator that would produce
  it does not exist in this repository or yet on the provider side, so the rule is dormant: it is tested with synthetic
  documents only. Its tolerance (10 BBCH units) and maximum estimate age (14 days) are development defaults with no
  measurement behind them (`config/parcel_features.yaml`).
- **Crop and marker checks are switched off until validated.** The consumer side of the crop plausibility check and of
  the bare-soil and harvest markers is implemented and tested, but `crop_plausibility.enabled` and
  `field_markers.enabled` are `false`: the producer's classifier has not been validated for transfer to another season
  and has no coverage guarantee, and the marker thresholds have only been tried on synthetic series. While off, the
  blocks are recorded in the provenance and change no decision. The required inputs R_t do not include `crop_identity`
  or `field_state`.
- **The provider reads files only.** `providers/parcel_features.py` reads precomputed documents from a folder
  (`SMARTAGRI_PARCEL_FEATURES_DIR`); there is no live producer, no service call and no network use. The producer's
  hashes are copied, not verified.
- **Quality fields are empty for the fetched series.** The Sentinel Hub Statistical API path (`providers/satellite.py`)
  masks cloud, shadow and snow per pixel but returns no cloud or shadow share, no interior-pixel count and no
  `cloud_flag`; only a feature provider fills them. Observations without them are graded as before.
- **Thresholds are development defaults.** The NDVI quality caps (masked share 0.20 and 0.50, mixed-pixel share 0.30
  and 0.60, 30 and 10 interior pixels) are first guesses, not measured, and are reviewed and locked with the protocol.
- **Sweeps do not vary the features.** `evalkit sweep` shifts the dates and shares of `S.ndvi_series` only; the
  `parcel_features` block of a scenario is copied unchanged (`evalkit/sweep.py`). No development scenario carries one.
- **Wall-clock comparison.** Observation times and the decision moment are compared as wall-clock values; a date alone
  counts as the end of its day, so an observation on the decision day is accepted only with a time before the decision
  moment.

## Water balance and quantities

- **Quantity advice is disabled.** `config/rules.yaml` sets `irrigation.quantity_validated: false`; with it,
  `pipeline/generate.py` (`_quantity`) never states an irrigation depth or volume and adds a note that the
  parameters are not reviewed. The tools still compute net and gross depths; they appear among the calculations
  of an answer only when δ allows a quantity (`allow_quantity`; `pipeline/generate.py`, `calculations`).
- **Simplified root-zone balance, not a FAO-56 daily soil water balance.** The net need is
  `max(0, depletion fraction × AWC × root depth − rain forecast)` (`core/tools/water_balance.py`). ETc is computed
  (`core/tools/etc.py`) and reported, but it does not enter the net need.
- **ET0 for the coming days is persistence.** `core/decide.py` (`run_tools`) sets the ET0 of the next
  `irrigation.forecast_days` (3) days to the sum of ET0 over the past 7 days scaled by 3/7; the ET0 forecast that
  Open-Meteo returns is not used for it.
- **Kc is not interpolated within stages.** `core/tools/etc.py` (`kc_for_bbch`) looks Kc up in a step table by BBCH
  range; there is no linear interpolation during the development and late-season stages as in FAO-56, and BBCH
  90–99 has no Kc (ETc is then missing).
- **Effective rainfall is not modelled.** Forecast rain is subtracted in full from the net need
  (`core/tools/water_balance.py`); the daily balance of the parcel page subtracts daily rain in full
  (`research_api/views.py`, `BALANCE_FORMULA`). No runoff, interception or deep percolation is considered.
- **The daily balance of the parcel page is an illustration.** It starts from a zero deficit and is labelled
  `used_by_advice: false` (`research_api/views.py`, `water_balance`); it is not used by the advice.
- **Age of past-weather sums.** The 7-day past rainfall and ET0 sums enter q with age 0 days
  (`core/quality.py`, `observe_all`); their reliability comes from their origin (modelled), not from their age.

## Scope

- **Maize only.** A parcel created through the API is always `crop: maize` (`research_api/service.py`,
  `create_parcel`); the Kc table, the phenology table and the corpus are for maize.
- **One region.** The development scenarios use a parcel in the Pannonian lowland
  (`eval/scenarios/dev/*.yaml`, `region_class: pannonian`), the corpus has no other regional sources, and the default
  weather time zone is `Europe/Sarajevo` (`providers/weather.py`). Behaviour elsewhere is untested.
- **Advice types.** Irrigation timing and amount, fertilization timing and plan, field-operations window and scouting
  (`core/types.py`, `AdviceType`); everything else is out of scope and leads to abstention with a referral.
  The template answers never prescribe plant-protection products and do not infer the cause of a vegetation
  change from an index alone; with a language model these rules are instructions in the prompt
  (`pipeline/generate.py`), and in this version no separate check enforces them on the generated text.

## Generation

- **Template generator by default.** Without `LLM_PROVIDER` the answer text is built deterministically from the
  decision (`pipeline/generate.py`, `TemplateGenerator`). Results produced with the template generator describe the
  decision layers; they say nothing about the wording, errors or variability of a language model. With a language
  model, γ checks numbers and sentence support (`core/grounding.py`), but the sentence check is lexical unless the
  optional judge is configured (`pipeline/judge.py`), and repeated runs can differ.
- **The template is not a baseline for V0–V3.** The act of V0–V3 belongs to the language model. The template has no
  model: for these variants it always recommends and shows the decision core's action, so it says nothing about what a
  language model with that rung's data would do. Its answers carry the label "template, not a baseline" (run record,
  `evalkit report`, web evaluation view); an experiment run uses a language model for every variant, and a template run
  of V0–V3 on the development set only checks that the pipeline works.
- **CI covers only the template path.** All tests and the CI example run with `LLM_PROVIDER=template`
  (`.github/workflows/ci.yml`); language-model providers are tested with fakes.

## Evaluation

- **Development scenarios are a regression check.** The 15 development scenarios (`eval/scenarios/dev/`) carry
  expectations written by the developer for each variant; act accuracy on them measures conformance with those
  expectations, not correctness. Their references point to `eval/scenarios/dev/_passages.yaml`, so retrieval
  recall on the development set checks the installation, not retrieval quality.
- **Raters.** The blind rating is planned with the developer and one independent agronomist as raters; agreement
  (weighted Cohen's κ, `evalkit/report.py`) is therefore between two people, one of whom built the system. The
  rater guide (`../docs/RATER_GUIDE.md`) is in Serbian and is a draft until it has been calibrated and locked.
  The design of the rating is fixed in [protocol.md](protocol.md).
- **E1 changes two things at once.** V4 vs V3 differs by the package (q, σ, α) and by who chooses the act (the rules
  instead of the language model); the result is not attributed to either alone. A V3 with the core's act would be a
  separate, additional rung that this version does not define.
- **Limits of blinding.** Answers differ in form between variants: the free-text baseline VC is shown as text
  (`evalkit/rating.py`, `blind_answer`), V0 has no sources, and variants without α do not ask a structured
  question. A rater may recognise the family of a variant from the form of the answer.
- **Language of evaluation material.** Scenarios, the rater view and the report tables are in Serbian (Latin
  script); evaluation runs always use the core's default locale (`i18n.py`, `DEFAULT_LOCALE`).
