# Parcel features

A **parcel feature provider** supplies indicators of one parcel at one decision moment that the decision model cannot
compute itself: quality metadata of the NDVI observations, a satellite estimate of the growth stage, a crop
plausibility check and bare-soil or harvest markers. This page is the data contract (`parcel_features`, schema version
1), the rules that make it safe to use, and the way the quality layer q reads it. For the layers see
[layers.md](layers.md); for what is not done yet see [limitations.md](limitations.md#parcel-features).

## What this is, and what it is not

- A **file** per parcel and decision day, written by an offline producer that is not part of this repository. The
  producer is data (`producer.name`, version, commit, hashes), never code the core imports. The public examples and
  tests use `example-producer`.
- Read through a **generic provider interface** (`providers/parcel_features.py`). The core never names a producer.
- Part of **S**, the satellite context (`SatelliteSummary.parcel_features`). The ablation that removes the satellite
  context (`V5-satellite`) removes the features with it, and the rungs below the dynamic context (V0–V2) never see them.
- Used **only by q** (and through q by π, σ and α). A feature never becomes the value of an input used by the
  decision, and every rule can only **lower** a reliability grade (a minimum over caps), never raise one. Without the
  block, or without the optional fields, every input is graded exactly as before.
- Not a classifier, a stage estimator or a boundary tool. Those live on the producer's side.

## Data flow

```
producer (offline) -> <parcel_id>__<YYYY-MM-DD>.json -> provider (validates) -> profile or scenario -> S.parcel_features -> q
```

| Path | How the document arrives | What happens on failure |
|---|---|---|
| Scenario file (`context.S.parcel_features`) | written into the scenario, so the sha256 of the scenario file covers it and the protocol lock binds it | loading the scenario fails with every reason; nothing is dropped silently |
| Research API and web app | `SMARTAGRI_PARCEL_FEATURES_DIR` names a folder; the profile build reads `<parcel_id>__<YYYY-MM-DD>.json` for the decision day | the document is recorded as `rejected` with the reasons (`profile.parcel_features`, `profile.provenance.parcel_features_*`), the profile is still built, nothing from the document is used |
| Hand-built `Context` | `S.parcel_features` | `core.parcel_features.usable` re-checks the decision moment; an unusable document is ignored and recorded as rejected |

Without `SMARTAGRI_PARCEL_FEATURES_DIR` the profile has no `parcel_features` entry at all.

## The contract

Units: NDVI has no unit; shares are in [0, 1]; dates are ISO 8601 (a date alone counts as the **end** of that day);
durations are in days; distances in metres; BBCH is the integer 0–99 scale.

| Block | Required | Carries |
|---|---|---|
| top level | `schema_version` (= 1), `parcel_id`, `geometry_sha256`, `as_of`, `computed_at`, `source_obs_dates`, `producer` | which parcel, which geometry (hash), for which decision moment, when computed, every observation used |
| `producer` | `name`, `version`, `commit`, `config_sha256`, `run_manifest_sha256`, `data_access`; `model_sha256` only for a classifier | what produced it, by hashes the producer wrote |
| `ndvi_observations[]` | `obs_date`, `median`, `usable_share` | per observation on the **interior** of the parcel: percentiles, pixel counts, interior buffer, mixed-pixel share, cloud and shadow shares, `cloud_flag`, `temporal_outlier`, `mask_layers` |
| `stage_estimate` | `method`, `status` | growth stage as an interval `bbch_min`–`bbch_max`, the green-up date with an interval in days, the last clear observation, number of clear observations, longest gap |
| `crop_plausibility` | `season_year`, `cutoff_doy`, `p_maize`, `prediction_set`, `alpha`, `coverage_guarantee`, `decision`, `transfer_validated` | a calibrated probability, a prediction **set**, applicability fraction, whether transfer to this season and window was validated |
| `events` | `data_sufficiency` | bare soil now or since, harvest detected, date and evidence, `confidence` of the reported state |

`usable_share` is `valid_px_ratio` (usable pixels over the interior pixels). The consumer computes the age of a stage
estimate itself (decision day minus `last_clear_obs_date`); it is not a field.

**Uncertainty is carried as an interval, a set or a sufficiency indicator, never as a bare point value**: the stage
as `bbch_min`–`bbch_max`, the crop as `prediction_set` with `alpha` and `coverage_guarantee`, the data as
`n_clear_obs`, `longest_gap_days` and `data_sufficiency`. No indicator turns into a reliability grade except through a
rule in `config/parcel_features.yaml`.

### JSON Schema

The schema below is the one the validator in `core/parcel_features.py` (`SCHEMA`) checks; a test keeps this page and
the code identical.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "parcel_features v1",
  "description": "Indicators of one parcel at one decision moment, computed only from observations made before that moment. Units: NDVI has no unit; shares are in [0, 1]; dates are ISO 8601 (a date alone counts as the end of that day); durations are in days; distances in metres.",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version",
    "parcel_id",
    "geometry_sha256",
    "as_of",
    "computed_at",
    "source_obs_dates",
    "producer"
  ],
  "properties": {
    "schema_version": {
      "const": 1
    },
    "parcel_id": {
      "type": "string",
      "minLength": 1
    },
    "geometry_sha256": {
      "type": "string",
      "pattern": "^[0-9a-f]{64}$",
      "description": "sha256 of the normalised GeoJSON (see geometry_sha256())"
    },
    "as_of": {
      "type": "string",
      "pattern": "^\\d{4}-\\d{2}-\\d{2}([T ]\\d{2}:\\d{2}(:\\d{2}(\\.\\d+)?)?(Z|[+-]\\d{2}:\\d{2})?)?$",
      "description": "the decision moment the document was computed for"
    },
    "computed_at": {
      "type": "string",
      "pattern": "^\\d{4}-\\d{2}-\\d{2}([T ]\\d{2}:\\d{2}(:\\d{2}(\\.\\d+)?)?(Z|[+-]\\d{2}:\\d{2})?)?$",
      "description": "when the producer ran; not earlier than the latest source date"
    },
    "source_obs_dates": {
      "type": "array",
      "items": {
        "type": "string",
        "pattern": "^\\d{4}-\\d{2}-\\d{2}([T ]\\d{2}:\\d{2}(:\\d{2}(\\.\\d+)?)?(Z|[+-]\\d{2}:\\d{2})?)?$"
      },
      "description": "every observation used (S2, S1)"
    },
    "producer": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "name",
        "version",
        "commit",
        "config_sha256",
        "run_manifest_sha256",
        "data_access"
      ],
      "properties": {
        "name": {
          "type": "string",
          "minLength": 1
        },
        "version": {
          "type": "string",
          "minLength": 1
        },
        "commit": {
          "type": "string",
          "pattern": "^[0-9a-f]{7,40}$"
        },
        "config_sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$"
        },
        "model_sha256": {
          "type": [
            "string",
            "null"
          ],
          "pattern": "^[0-9a-f]{64}$"
        },
        "run_manifest_sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$"
        },
        "data_access": {
          "enum": [
            "stac-cog",
            "cdse-odata",
            "cdse-statistical",
            "openeo",
            "other"
          ]
        }
      }
    },
    "ndvi_observations": {
      "type": "array",
      "description": "one entry per observation, on the interior of the parcel; an entry replaces the observation of the same obs_date in S.ndvi_series and adds the dates S lacks",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "obs_date",
          "median",
          "usable_share"
        ],
        "properties": {
          "obs_date": {
            "type": "string",
            "pattern": "^\\d{4}-\\d{2}-\\d{2}([T ]\\d{2}:\\d{2}(:\\d{2}(\\.\\d+)?)?(Z|[+-]\\d{2}:\\d{2})?)?$"
          },
          "median": {
            "type": "number",
            "minimum": -1,
            "maximum": 1
          },
          "p10": {
            "type": [
              "number",
              "null"
            ],
            "minimum": -1,
            "maximum": 1
          },
          "p90": {
            "type": [
              "number",
              "null"
            ],
            "minimum": -1,
            "maximum": 1
          },
          "usable_share": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "valid_px_ratio over the interior pixels"
          },
          "n_px_total": {
            "type": "integer",
            "minimum": 0
          },
          "n_px_interior": {
            "type": "integer",
            "minimum": 0
          },
          "n_px_valid": {
            "type": "integer",
            "minimum": 0
          },
          "interior_buffer_m": {
            "type": "number",
            "minimum": 0
          },
          "mixed_px_share": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "share of the parcel's pixels on its boundary"
          },
          "cloud_px_share": {
            "type": "number",
            "minimum": 0,
            "maximum": 1
          },
          "shadow_px_share": {
            "type": "number",
            "minimum": 0,
            "maximum": 1
          },
          "cloud_flag": {
            "type": "boolean"
          },
          "temporal_outlier": {
            "type": "boolean"
          },
          "mask_layers": {
            "type": "array",
            "items": {
              "type": "string"
            }
          }
        }
      }
    },
    "stage_estimate": {
      "type": [
        "object",
        "null"
      ],
      "additionalProperties": false,
      "required": [
        "method",
        "status"
      ],
      "description": "growth stage as an interval, from observations before as_of only (causal)",
      "properties": {
        "method": {
          "type": "string",
          "minLength": 1
        },
        "status": {
          "enum": [
            "estimated",
            "pre_emergence",
            "insufficient_data"
          ]
        },
        "bbch_min": {
          "type": "integer",
          "minimum": 0,
          "maximum": 99
        },
        "bbch_max": {
          "type": "integer",
          "minimum": 0,
          "maximum": 99
        },
        "greenup_date": {
          "type": [
            "string",
            "null"
          ],
          "pattern": "^\\d{4}-\\d{2}-\\d{2}([T ]\\d{2}:\\d{2}(:\\d{2}(\\.\\d+)?)?(Z|[+-]\\d{2}:\\d{2})?)?$"
        },
        "greenup_date_ci_days": {
          "type": [
            "array",
            "null"
          ],
          "items": {
            "type": "integer"
          },
          "minItems": 2,
          "maxItems": 2
        },
        "last_clear_obs_date": {
          "type": "string",
          "pattern": "^\\d{4}-\\d{2}-\\d{2}([T ]\\d{2}:\\d{2}(:\\d{2}(\\.\\d+)?)?(Z|[+-]\\d{2}:\\d{2})?)?$"
        },
        "n_clear_obs": {
          "type": "integer",
          "minimum": 0
        },
        "longest_gap_days": {
          "type": "number",
          "minimum": 0
        }
      }
    },
    "crop_plausibility": {
      "type": [
        "object",
        "null"
      ],
      "additionalProperties": false,
      "required": [
        "season_year",
        "cutoff_doy",
        "p_maize",
        "prediction_set",
        "alpha",
        "coverage_guarantee",
        "decision",
        "transfer_validated"
      ],
      "properties": {
        "season_year": {
          "type": "integer",
          "minimum": 1990,
          "maximum": 2100
        },
        "cutoff_doy": {
          "type": "integer",
          "minimum": 1,
          "maximum": 366
        },
        "p_maize": {
          "type": "number",
          "minimum": 0,
          "maximum": 1
        },
        "prediction_set": {
          "type": "array",
          "items": {
            "type": "string"
          },
          "uniqueItems": true
        },
        "alpha": {
          "type": "number",
          "exclusiveMinimum": 0,
          "maximum": 1
        },
        "coverage_guarantee": {
          "type": "boolean"
        },
        "aoa_fraction": {
          "type": "number",
          "minimum": 0,
          "maximum": 1
        },
        "n_px_interior": {
          "type": "integer",
          "minimum": 0
        },
        "decision": {
          "enum": [
            "agreement",
            "discrepancy",
            "uncertain",
            "insufficient_resolution",
            "out_of_applicability"
          ]
        },
        "transfer_validated": {
          "type": "boolean"
        },
        "training_overlap_m": {
          "type": [
            "number",
            "null"
          ],
          "minimum": 0
        }
      }
    },
    "events": {
      "type": [
        "object",
        "null"
      ],
      "additionalProperties": false,
      "required": [
        "data_sufficiency"
      ],
      "properties": {
        "data_sufficiency": {
          "enum": [
            "s2+s1",
            "s2",
            "s1",
            "insufficient"
          ]
        },
        "bare_soil_now": {
          "type": [
            "boolean",
            "null"
          ]
        },
        "bare_soil_since": {
          "type": [
            "string",
            "null"
          ],
          "pattern": "^\\d{4}-\\d{2}-\\d{2}([T ]\\d{2}:\\d{2}(:\\d{2}(\\.\\d+)?)?(Z|[+-]\\d{2}:\\d{2})?)?$"
        },
        "harvest_detected": {
          "type": [
            "boolean",
            "null"
          ]
        },
        "harvest_date": {
          "type": [
            "string",
            "null"
          ],
          "pattern": "^\\d{4}-\\d{2}-\\d{2}([T ]\\d{2}:\\d{2}(:\\d{2}(\\.\\d+)?)?(Z|[+-]\\d{2}:\\d{2})?)?$"
        },
        "harvest_evidence": {
          "type": "string"
        },
        "confidence": {
          "type": "number",
          "minimum": 0,
          "maximum": 1,
          "description": "confidence of the reported bare-soil or harvest state"
        },
        "greenup_date": {
          "type": [
            "string",
            "null"
          ],
          "pattern": "^\\d{4}-\\d{2}-\\d{2}([T ]\\d{2}:\\d{2}(:\\d{2}(\\.\\d+)?)?(Z|[+-]\\d{2}:\\d{2})?)?$"
        }
      }
    }
  }
}
```

### Example

A complete document of the `example-producer` for the parcel `t` at 2026-07-12 06:00 (the file
`backend/tests/fixtures/parcel_features/example_producer_full.json` is the same document):

```json
{
  "schema_version": 1,
  "parcel_id": "t",
  "geometry_sha256": "8add6fa5641dd6859ced242634d9bdc4341ea9759ce4b950e01147c47954c23e",
  "as_of": "2026-07-12T06:00:00",
  "computed_at": "2026-07-12T07:30:00",
  "source_obs_dates": [
    "2026-07-04",
    "2026-07-09"
  ],
  "producer": {
    "name": "example-producer",
    "version": "1.0.0",
    "commit": "abc1234",
    "config_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "model_sha256": null,
    "run_manifest_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "data_access": "stac-cog"
  },
  "ndvi_observations": [
    {
      "obs_date": "2026-07-04",
      "median": 0.71,
      "p10": 0.62,
      "p90": 0.8,
      "usable_share": 0.9,
      "n_px_total": 60,
      "n_px_interior": 44,
      "n_px_valid": 40,
      "interior_buffer_m": 10.0,
      "mixed_px_share": 0.27,
      "cloud_px_share": 0.05,
      "shadow_px_share": 0.02,
      "cloud_flag": false,
      "temporal_outlier": false,
      "mask_layers": [
        "scl",
        "dilation_2px"
      ]
    },
    {
      "obs_date": "2026-07-09",
      "median": 0.74,
      "p10": 0.66,
      "p90": 0.81,
      "usable_share": 0.95,
      "n_px_total": 60,
      "n_px_interior": 44,
      "n_px_valid": 42,
      "interior_buffer_m": 10.0,
      "mixed_px_share": 0.27,
      "cloud_px_share": 0.0,
      "shadow_px_share": 0.0,
      "cloud_flag": false,
      "temporal_outlier": false,
      "mask_layers": [
        "scl",
        "dilation_2px"
      ]
    }
  ],
  "stage_estimate": {
    "method": "example_causal_v1",
    "status": "estimated",
    "bbch_min": 60,
    "bbch_max": 69,
    "greenup_date": "2026-05-06",
    "greenup_date_ci_days": [
      -3,
      4
    ],
    "last_clear_obs_date": "2026-07-09",
    "n_clear_obs": 9,
    "longest_gap_days": 10.0
  },
  "crop_plausibility": {
    "season_year": 2026,
    "cutoff_doy": 190,
    "p_maize": 0.93,
    "prediction_set": [
      "maize"
    ],
    "alpha": 0.1,
    "coverage_guarantee": false,
    "aoa_fraction": 0.97,
    "n_px_interior": 44,
    "decision": "agreement",
    "transfer_validated": false,
    "training_overlap_m": 1200.0
  },
  "events": {
    "data_sufficiency": "s2",
    "bare_soil_now": false,
    "bare_soil_since": null,
    "harvest_detected": false,
    "harvest_date": null,
    "harvest_evidence": "",
    "confidence": 0.7,
    "greenup_date": "2026-05-06"
  }
}
```

## Only what was observed before the decision

A document is rejected as a whole when any of these fails (`core.parcel_features.validate`; every reason is listed):

1. it does not match the schema (unknown field, wrong type, share outside [0, 1], unknown `schema_version`);
2. `as_of` is later than the decision moment of the context or on another day (the document is keyed by parcel and
   decision day and may be computed at or before the decision moment);
3. any observation date (`source_obs_dates`, `ndvi_observations[].obs_date`, `stage_estimate.last_clear_obs_date`,
   `greenup_date`, `bare_soil_since`, `harvest_date`) is later than the **earlier** of the document's `as_of` and the
   decision moment. A date alone stands for the end of that day, so an observation on the decision day passes only
   when it carries a time at or before the decision moment;
4. the end of the crop-feature window (`season_year` and `cutoff_doy`) is after the decision moment;
5. `computed_at` is earlier than the latest source observation, a `ndvi_observations` date is missing from
   `source_obs_dates`, pixel counts are inconsistent, or a stage interval is empty or missing where its status needs one;
6. when the parcel is known: `parcel_id` differs, or `geometry_sha256` differs from the hash of the parcel's geometry.

Offsets are dropped and the instants are compared as wall-clock values in the zone of the scenario or parcel.

## Hashes

- **Geometry** (`geometry_sha256`): sha256 of the normalised GeoJSON in EPSG:4326: a Polygon or MultiPolygon (a Feature
  is unwrapped), coordinates rounded to 7 decimals, altitude dropped, closing point and repeated points removed,
  exterior ring counter-clockwise, holes clockwise and sorted, every ring starting at its smallest point, serialised
  with sorted keys and no spaces (`core.parcel_features.geometry_sha256`). The same ring written another way gives
  the same hash; a moved vertex does not.
- **Producer** (`producer.config_sha256`, `model_sha256`, `run_manifest_sha256`, `commit`): written by the producer and
  copied unchanged into the provenance of every answer. They identify the producer's configuration, classifier and run
  manifest; this repository does not verify them.
- **Document** (`document_sha256`): sha256 of the canonical JSON of the document (sorted keys, no spaces, ASCII, dates as
  ISO strings), computed on reading. It is stored with the profile and recorded in the provenance of every answer.

## How q uses the features

Thresholds are in `backend/config/parcel_features.yaml`. **All values there are development defaults, not locked and
not measured**; they are reviewed by the agronomist and locked with the protocol. The file is hashed in
`config.config_hashes()` and bound by the protocol lock.

### NDVI observation quality (switch `ndvi_quality.enabled`, on)

For `ndvi_latest` and `ndvi_spatial_contrast` the quality fields of the latest observation cap the grade (the lowest cap
wins; the fields are recorded in the quality row's `detail`; the age and coverage rules apply first and are unchanged):

| Field | At most medium | Low |
|---|---|---|
| `cloud_flag` | true | – |
| `cloud_px_share + shadow_px_share` | above 0.20 | above 0.50 |
| `mixed_px_share` | above 0.30 | above 0.60 |
| valid interior pixels (`n_px_valid`, else `n_px_interior`) | below 30 | below 10 |

An observation with `temporal_outlier: true` is left out of the NDVI summary (latest value, trend) and its date is
named in the quality row. The existing small-parcel rule (area under 0.3 ha) stays. `cloud_flag` and the other fields
are stored per observation; the Statistical API provider (`providers/satellite.py`) does not report them, so for the
fetched series they are empty (`null`) and only a feature provider fills them.

A producer observation replaces the series entry of the same `obs_date` and adds the dates the series lacks.

### Stage conflict (switch `stage_conflict.enabled`, on)

The rule compares **two stage sources**: the stage in use (the farmer-reported stage, or the estimate from the sowing
date when the report is older and less reliable) against the satellite stage interval of `stage_estimate`. It applies
only when the document carries an estimate with `status: estimated` that is at most `max_estimate_age_days` (14) old.

- If the stage in use lies further than `tolerance_bbch` (10 BBCH units) outside `bbch_min`–`bbch_max`, the
  reliability of `phenophase` is **capped at low** and the conflict is recorded: the quality row's `detail.conflicts`,
  `Decision.input_conflicts`, and `provenance.parcel_features.input_conflicts` of every answer.
- The value of the stage is not changed, and the satellite estimate is never a third candidate for the value. Origin
  and age stay those of the source in use.
- Through the existing layers: σ finds the stage below its required level for the advice types that need it
  (`requirements.yaml`), α asks for the stage, π makes passages conditioned on a stage conditional, δ follows σ.
  Nothing outside q has a rule for the conflict.
- Variants without q (V0–V3) see neither the rule nor its effect; `V5-satellite` removes the features.
- When the estimate is `pre_emergence`, `insufficient_data`, stale or absent, nothing happens, and the provenance says
  which (`stage_estimate.comparison`).

Which stage is used when there is no satellite estimate is unchanged: of the reported stage and the estimate from the
sowing date, the one with the higher reliability is used, so a report older than 14 days (low) yields to the estimate
(medium).

### Crop plausibility and field markers (switches `crop_plausibility.enabled`, `field_markers.enabled`, both off)

The consumer side exists and is tested; it is switched off until the producer's classifier and markers are validated.

- **Off** (as shipped): the blocks are recorded in `provenance.parcel_features` (`enabled: false`, with the recorded
  block) and have no effect on any decision. No input is added to the quality profile.
- **On**: `crop_identity` (the declared crop, user-reported) is graded high and capped at low only when the producer
  reports `decision: discrepancy` **and** `transfer_validated: true`; every other decision (`agreement`, `uncertain`,
  `insufficient_resolution`, `out_of_applicability`) is carried and changes nothing. π reads it for the crop check: a
  low grade makes a crop-conditioned passage conditional (the crop check stays a hard check). `field_state`
  (`crop_present`, `bare_soil`, `harvested`) is graded from the producer's `confidence` and `data_sufficiency`; a state
  graded at least medium that contradicts the stage in use (bare soil with a stage at or above BBCH 10; a harvest when
  the advice assumes a standing crop) caps `phenophase` at low and is recorded as a conflict.
- The required inputs R_t are **not** changed by either check; adding them is a protocol decision.

## Provenance

Every answer whose context carries features records `provenance.parcel_features`: schema version, document hash,
geometry hash, parcel id, `as_of`, `computed_at`, the producer block as received, the number of source observations,
what was applied (`ndvi_quality`, `stage_conflict`, `crop_plausibility`, `field_markers`), the input conflicts with
their evidence, the stage estimate with the result of its comparison, and the recorded-only blocks. A run on a variant
without the satellite context records nothing.

## What the producer must deliver for the stage estimate

The satellite stage estimator is not part of this repository and is not available yet; the rule above is dormant
until a document carries `stage_estimate.status: estimated`. The estimator must be **causal**: it may use only
observations dated before the decision moment, so a seasonal analysis that needs the whole season (peak, end of
season) is not usable. It must give an interval, not a point: `bbch_min`–`bbch_max`, with the last clear observation,
the number of clear observations and the longest gap; its class limits and green-up threshold are set on development
parcels and reviewed by an agronomist. Its method and the hash of its configuration are part of the document.
