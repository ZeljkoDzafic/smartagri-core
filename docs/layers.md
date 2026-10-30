# Layer map: model → code → configuration → tests

This page maps every layer of the decision model to the module that implements it, the configuration file it reads
and the tests that cover it. Paths are relative to `backend/` (code under `src/smartagri/`). The configuration files
in `config/` are hashed into every run's provenance (`config.config_hashes()`) and into the protocol lock.

For the flow of one question see [architecture.md](architecture.md); for what the layers do not do yet see
[limitations.md](limitations.md).

## Acts

The policy δ chooses one of **four acts** (`core/types.py`, `class Act`):

| Act | Meaning |
|---|---|
| `recommend` | the inputs are sufficient; the advice is given (a quantity only when the policy allows it, see below) |
| `conditional` | advice that depends on a stated condition: a missing input that α asks for, a degraded advice type, inputs that are present but unreliable, a missing input that would not change the decision, an exhausted question budget, or a conflict between sources |
| `ask` | a follow-up question before any advice (high-risk advice types with a missing input) |
| `abstain` | no advice: the question is out of scope, the corpus has no applicable passage, or required inputs are absent |

"Refer" is **not** a fifth act. An abstention for an out-of-scope question or an insufficient corpus carries the
warning `refer_to_extension_service` (`core/policy.py`), which the answer shows as a referral to the extension
service.

## Layers

| Layer | What it decides | Code | Configuration | Tests | Variant flag (`config/variants.yaml`) |
|---|---|---|---|---|---|
| **C** context | parcel P, agronomic inputs A, weather summary W, NDVI series S, question Q | `core/types.py` (`Context`, `ParcelInfo`, `Agronomic`, `WeatherSummary`, `SatelliteSummary`); `pipeline/profile.py` (`build_profile`, `context_from`); `providers/weather.py`, `providers/satellite.py`, `providers/base.py` (external cache, offline mode); `pipeline/run.py` (`ablate_context`); optional parcel features inside S: `core/parcel_features.py` (contract, validator, hashes), `providers/parcel_features.py` (provider) | `rules.yaml` (`phenology.gdd_base_c` for the GDD sum); `parcel_features.yaml` | `test_research_api.py`, `test_variants.py`, `test_optional_inputs.py`, `test_parcel_features.py` | `dynamic_context`, `use_weather`, `use_satellite` |
| intent | type of advice asked for (keyword rules, no model) | `pipeline/intent.py`, `pipeline/intent_en.py` | — | `test_intent_eval.py` | — |
| retrieval | candidate passages for the question | `retrieval/search.py` (`Retriever`, `reciprocal_rank_fusion`), `retrieval/embed.py`, `retrieval/corpus.py`, `retrieval/__init__.py` (`make_retriever`) | `vocab.yaml` (passage metadata vocabulary, checked when the corpus loads); corpus in `corpus/` | `test_retrieval.py`, `test_corpus.py`, `test_corpus_reports.py`, `test_ingest.py` | `retrieval` (`none` or `hybrid`) |
| **π** applicability | whether each passage applies to this parcel (crop, stage, region, date, source type), and the passage budget | `core/applicability.py` (`applicability`, `select_budget`); `core/conflicts.py` (`detect`) | `vocab.yaml`; `rules.yaml` (`irrigation.rain_wait_mm_3d`) | `test_applicability.py`, `test_policy.py` (source conflicts), `test_dev_scenarios.py` | `applicability` (`off`, `query_conditions`, `parcel_conditions`) |
| **q** quality | origin, age, coverage and reliability of each input; the NDVI observation quality fields and the conflict between two stage sources lower a grade (see below) | `core/quality.py` (`observe_all`, `grade`, `annotate_quality`); `core/parcel_features.py` (the rules that only lower a grade) | `thresholds.yaml`; `parcel_features.yaml`; `rules.yaml` (`soil`, `optional_inputs`) | `test_quality.py`, `test_optional_inputs.py`, `test_parcel_features.py` | `quality` |
| **σ** sufficiency | whether the inputs suffice for the advice type, or for a degraded one | `core/sufficiency.py` (`sufficiency`, `missing_inputs`) | `requirements.yaml` | `test_sufficiency.py` | `sufficiency` |
| **α** asking | the one question whose answer can change the decision, ranked by decision sensitivity, then cost | `core/asking.py` (`choose_question`) | `asking.yaml` | `test_asking.py` | `asking` |
| **δ** policy | the act, the reason code, whether a quantity may be shown | `core/policy.py` (`decide`); `core/decide.py` (`decide`: orchestration, downgrade to `conditional` on a source conflict) | `requirements.yaml` (`quantity`, `risk` per advice type) | `test_policy.py`, `test_dev_scenarios.py`, `test_variants.py` | `policy` |
| decision cores D_t | the action class per advice type (irrigate now / wait, top-dress window, spraying window, scouting priority); its conclusion reaches the text generator of V4 and V5 only, never that of V0–V3 | `core/rules.py` (`decide_action_core`) | `rules.yaml` | `test_dev_scenarios.py`, `test_optional_inputs.py`, `test_free_act_baselines.py` | — (always on for in-scope questions) |
| **γ** grounding | numbers in a generated text must come from a tool or the context; sentences must be supported by a passage | `core/grounding.py` (`unsupported_numbers`, `support_check`, `split_sentences`); `pipeline/generate.py` (LLM path: an unsupported number replaces the text by the template answer, unsupported sentences are removed); `pipeline/judge.py` (optional entailment judge) | — (the lexical support threshold is a default argument of `support_check`, not a configuration value) | `test_tools.py`, `test_judge.py`, `test_generate.py` | `grounding` |

### Web settings and the configuration column

The configuration files named in the table are read through `config.load(name)`. In a research API request that
computes an answer, `config.load` returns the file data with the caller's web settings merged over it (a context
variable, see [settings.md](settings.md)); everywhere else, including `evalkit`, the protocol lock and the blind
rating endpoints, it returns the files unchanged. `core/` is not aware of the overlay. Every web answer records the
settings it used in `provenance.settings`; the file hashes in `config_hashes` do not change. Tests:
`test_web_settings.py`.

The template generator (`pipeline/generate.py`, `TemplateGenerator`, `template_answer`) builds its text from the
decision and the tool outputs, so γ has nothing to reject on that path; γ acts on text written by a language model.

**Who chooses the act.** For V4 and V5 the layers do: the language model receives the core's act and action and only
phrases them. For V0–V3 (no sufficiency layer, `act_free` in `pipeline/run.py`) the model chooses the act itself: its
fact sheet (`pipeline/generate.py`, `fact_sheet`) holds the question, the parcel data (ungraded), the data statements
without the core's conclusions, the limitations, the passages the rung retrieves with the applicability it computes, and
the tool results the rung's inputs allow, and **no** act, action, timing or other conclusion of the decision core D_t.
The prompt (`SYSTEM_PROMPT_FREE`, hash `FREE_PROMPT_HASH`, part of the protocol lock) does not mention a core and requires
the field `act` (`recommend`, `conditional`, `ask`, `abstain`); an output without a valid act is an error item in an
evaluation and a labelled template fallback in interactive use. The template for these variants is a fallback that always
recommends; its answers carry `baseline_label` = "template, not a baseline" (run record: `baseline`). Tests:
`test_free_act_baselines.py`.

## Inputs of q

q describes every input by origin, age, coverage and a reliability grade. The grade comes from `config/thresholds.yaml`
(origin, age, coverage, count). Two sets of facts can only **lower** that grade; both read the optional
`parcel_features` block of the satellite context S (see [parcel-features.md](parcel-features.md)) and are
configured in `config/parcel_features.yaml` (development defaults, not locked):

| Input | Facts q uses | Effect |
|---|---|---|
| `ndvi_latest`, `ndvi_spatial_contrast` | origin `measured`; age and valid-pixel share (`valid_px_ratio`); optional: `cloud_flag`, cloud and shadow share, mixed-pixel share, valid interior pixels, interior buffer, `temporal_outlier` | age and coverage grade as before; a cloud flag, a large masked or mixed share or few interior pixels cap the grade at medium or low; an observation screened as a temporal outlier is left out of the summary |
| `ndvi_trend` | observations of the last 14 days with a usable share of at least 0.60 | grade by their number; outliers left out |
| `phenophase` | the reported stage (user-reported, with the date it was given) or the estimate from the GDD sum or the days since sowing (derived); optional: the satellite stage interval | of the two, the more reliable one is used (an old report yields to the estimate); when the stage in use lies outside the satellite interval by more than the tolerance, the grade is capped at **low** and the conflict is recorded in the quality row, in `Decision.input_conflicts` and in the provenance |
| `crop_identity`, `field_state` | exist only when `crop_plausibility.enabled` or `field_markers.enabled` is true (both false) | a validated crop discrepancy caps `crop_identity` at low; a state that contradicts the stage in use caps `phenophase` at low |

A conflict flows to σ (the stage falls below the level an advice type requires), α (the stage is asked for again) and π
(passages conditioned on a stage become conditional) through their existing rules; no layer has a special case. V0–V3 have
no q and do not see the rule; the ablation that removes the satellite context removes the features.

## Agronomic tools (computed in code)

| Tool | Formula | Code | Configuration | Tests |
|---|---|---|---|---|
| crop coefficient and ETc | Kc by BBCH range (step table); ETc = Kc × ET0 | `core/tools/etc.py` (`kc_for_bbch`, `crop_evapotranspiration`) | `kc_maize.yaml` | `test_tools.py`, `test_research_api.py` |
| net irrigation need | net = max(0, depletion fraction × AWC × root depth − rain forecast), split into applications of at most `max_single_net_mm` | `core/tools/water_balance.py` (`net_irrigation_need`; depletion fractions per qualitative soil-water status in `DEPLETION_BY_STATUS`) | `rules.yaml` (`irrigation.max_single_net_mm`, `irrigation.root_depth_m_by_bbch`) | `test_tools.py` |
| gross irrigation | gross = net / efficiency; m³/ha = gross × 10 | `core/tools/irrigation.py` (`gross_irrigation`) | `rules.yaml` (`soil.efficiency_by_system`, read by q) | `test_tools.py` |
| application time | days = gross / system capacity | `core/decide.py` (`run_tools`) | — | `test_optional_inputs.py` |
| phenology | BBCH from GDD or days since sowing | `core/tools/phenology.py` (`estimate_bbch`) | `rules.yaml` (`phenology`, `optional_inputs.fao_*`) | `test_tools.py`, `test_optional_inputs.py` |
| NDVI summary | latest median, p90 − p10 contrast, 14-day trend; observations screened as outliers left out | `core/tools/ndvi_stats.py` (`ndvi_summary`) | `parcel_features.yaml` (`ndvi_quality`); `MIN_SHARE_FOR_TREND` in code | `test_tools.py`, `test_parcel_features.py` |

`core/decide.py` (`run_tools`) runs the irrigation tools for both irrigation advice types; ET0 for the coming days is
derived there (see [limitations.md](limitations.md)). Whether a quantity reaches the answer is decided in two places:
δ sets `allow_quantity`, and `pipeline/generate.py` shows a depth only when `rules.yaml` has
`irrigation.quantity_validated: true` (it is `false` in this version).

The parcel page of the web app also shows a daily root-zone balance (`research_api/views.py`, `water_balance`). It
uses the same Kc and ETc tool, is labelled as an illustration (`used_by_advice: false`) and does not feed the advice.

## Variants

`config/variants.yaml` defines V0–V5 and the context ablations V5-weather and V5-satellite by the flags above. The core
never branches on a variant name (`core/decide.py`). Each rung adds one layer of the design: `dynamic_context`
removes the weather summary W and the NDVI series S for V0–V2 (`pipeline/run.py`, `ablate_context`), V3 adds them
together with π over the parcel's conditions, V4 adds the sufficiency-and-asking model (q, σ and α together, one layer
by definition), and V5 adds δ and γ. Without q, inputs are "ungraded" (`core/quality.py`). See
[evaluation.md](evaluation.md) and [protocol.md](protocol.md).
