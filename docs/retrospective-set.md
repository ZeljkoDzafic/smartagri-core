# Retrospective set: pair format, rules and the rain-wait outcome

A retrospective pair is a real parcel at a past decision moment, together with what happened afterwards. The set adds to
the 40 authored scenarios (`docs/protocol.md`) situations that reality has already decided: for some advice types the
outcome can be computed from the realised weather, without anyone's judgement and without the thresholds of the system.
It confirms a direction on real parcels; it does not prove agronomic benefit, and it is not a random sample of parcels.

Status: format and loader only. The selection of pairs, the outcome thresholds, the decision hour and the sources of the
realised weather are decisions of the protocol owner and the agronomist; none is made here.

## 1. Sets, seasons and where the files live

| Set name (`--set`) | Season | Protected |
|---|---|---|
| `retrospective-dev` | 2024 (development: pilot, definitions, sample size) | no |
| `retrospective-test` | 2025 (test: runs only under the locked protocol) | yes, like `test` |

The pairs are JSON files, one per pair, in a folder **outside the repository** (`--scenarios-dir`, or
`SMARTAGRI_RETRO_DIR/<set name>`). They are never committed; the loader refuses a folder inside the repository. The
loader checks that every pair is of the season of its set, so a 2025 pair cannot be run as development. Everything else
works as for the other sets: `evalkit guard --set retrospective-test --scenarios-dir ...` (n-gram leakage against the
corpus), `evalkit lock`, `evalkit run --locked`, `assign`, `report`. A pair file is hashed by the lock like a scenario
file, so an outcome edited after the lock makes `run --locked` refuse.

## 2. Pair file (`smartagri-retrospective-pair/1`)

| Field | Required | Content |
|---|---|---|
| `schema` | yes | `"smartagri-retrospective-pair/1"` |
| `id` | yes | unique within the folder, e.g. `RET-2025-001` |
| `season` | yes | year; must be the season of the set |
| `parcel_code` | yes | coded parcel (the cluster of the bootstrap); never a name or an exact location in a published file |
| `decision_at` | yes | ISO date-time **with UTC offset**: the moment the system decides |
| `advice_type` | yes | one of the advice types of the system (`irrigation_timing`, ...) |
| `question` | yes | the user's question as it would have been asked |
| `context` | yes | the context record of a scenario file (P, A, W, S, ...) without `as_of` and `Q` (taken from the pair) and without any outcome key |
| `weather_snapshot` | yes | reference to the forecast as issued: `source`, `ref` (cache key or file), `issued_before` (ISO with offset, not after `decision_at`); `model` optional |
| `outcome` | yes | the realised data: `source` (station, hydrometeorological service, reanalysis) and `daily_precip_mm` {`YYYY-MM-DD`: mm or null}; days before the decision day are refused |
| `stratum` | no | stratum label for balanced selection |
| `user_replies` | no | replies the user would have given, taken from a diary written **before** the decision date, never from later knowledge |
| `note` | no | free text (read by the leakage guard) |

Unknown fields are an error. JSON Schema of the file:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "smartagri-retrospective-pair/1",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema", "id", "season", "parcel_code", "decision_at", "advice_type", "question", "context",
               "weather_snapshot", "outcome"],
  "properties": {
    "schema": {"const": "smartagri-retrospective-pair/1"},
    "id": {"type": "string", "minLength": 1},
    "season": {"type": "integer"},
    "parcel_code": {"type": "string", "minLength": 1},
    "decision_at": {"type": "string", "format": "date-time"},
    "advice_type": {"type": "string"},
    "question": {"type": "string"},
    "stratum": {"type": ["string", "null"]},
    "note": {"type": ["string", "null"]},
    "user_replies": {"type": "object"},
    "context": {"type": "object", "not": {"anyOf": [{"required": ["as_of"]}, {"required": ["Q"]}, {"required": ["outcome"]}]}},
    "weather_snapshot": {
      "type": "object",
      "required": ["source", "ref", "issued_before"],
      "properties": {"source": {"type": "string"}, "ref": {"type": "string"}, "model": {"type": "string"},
                     "issued_before": {"type": "string", "format": "date-time"}}
    },
    "outcome": {
      "type": "object",
      "required": ["source", "daily_precip_mm"],
      "properties": {"source": {"type": "string"},
                     "daily_precip_mm": {"type": "object", "minProperties": 1,
                                         "additionalProperties": {"type": ["number", "null"], "minimum": 0}}}
    }
  }
}
```

## 3. Rules that fail loudly

The loader raises an error, and the run does not start, when: a field is unknown or missing; the schema or the season is
wrong; `decision_at` has no UTC offset; the snapshot was issued after the decision; a date of the context (sowing report,
last irrigation, observations, forecast issue time, NDVI observation) is after the decision moment; an outcome date is
before the decision day or a rainfall is negative; the context carries `as_of`, `Q` or an outcome key; two pairs share an
id; the folder is inside the repository or holds no pair. The outcome is stored with the item for the analysis and is never
part of what the system or the rater receives.

## 4. Fixed decision hour

The age of the rain forecast, and with it the reliability grade and the sufficiency of the decision, depends on the hour of
the decision (a forecast run is taken as available 6 h after its start). A protocol can therefore fix one hour:
`evalkit run|lock --decision-hour-utc H` sets the decision moment of every scenario or pair to `H:00` UTC of its own
calendar day (the day in the moment's own offset). Unset by default (the moments are used as written); naive moments
(no UTC offset) and an hour that falls on another local day are refused; the value is part of the lock and recorded in
each item. Sensitivity to the 6 h assumption is a separate analysis.

## 5. Objective outcome of rain-wait advice

`evalkit.retrospective.rain_wait_outcome(advice, decision_date, daily_precip_mm, *, window_days, threshold_mm,
effect_lag_days, include_decision_day)` is a pure function; it fetches nothing. Input contract:

- `advice`: `"wait"` or `"irrigate_now"` (`retrospective.advice_kind(core_action)` maps `wait_for_rain` and
  `irrigate_within_2d`); anything else is not evaluable;
- `daily_precip_mm`: realised rainfall per day from the source named in the pair; a missing or null day is unknown;
- `window_days`, `threshold_mm`, `effect_lag_days`, `include_decision_day`: **decisions, no defaults**. The threshold is set
  by the agronomist who does not rate and must not be taken from `config/rules.yaml` (that would make the measure circular).

Rule: `wait` is contrary when the rain of the `window_days` days after the decision is below `threshold_mm`;
`irrigate_now` is contrary when the rain of the first `effect_lag_days` days reaches it. The result is
`{evaluable, contrary, rain_mm, window, rule, reason}`; incomplete data is `evaluable: false` with the missing days named,
never filled in. The indicator is not K4 or K5: it is an independent check, and its relation to the agronomist's K4/K5 is
reported as agreement, not assumed. It exists for irrigation timing (against rain) only; fertilisation timing, quantities and
scouting have no objective outcome from the weather.
