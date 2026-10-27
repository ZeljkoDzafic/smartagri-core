# Web settings

Every agronomic parameter that lives in a configuration file of the decision core can be set through the web app:
by a user for themselves, for one of their parcels, and by an administrator for everyone. The files stay the
starting values and are never rewritten; the settings are stored in the database and applied on top of the files
for the duration of one web request.

This page describes the levels, the administrator role, the limits, the history, the guarantee that evaluation is
not affected, the HTTP API and how to add a parameter. The code is in `backend/src/smartagri/web_settings/`
(registry and service), `backend/src/smartagri/research_api/settings_routes.py` (HTTP) and
`backend/src/smartagri/research_api/static/settings.js` (client).

## Levels and precedence

| Level | Who sets it | Applies to |
|---|---|---|
| file default | nobody (the YAML files in `backend/config/`) | everyone, when nothing above is set |
| **global** | an administrator | every user who has not set their own value |
| **user** | a signed-in user | all of that user's parcels |
| **parcel** | the owner of the parcel | that parcel only |

The effective value is the parcel's value, else the user's, else the global one, else the file default.

- A visitor who is not signed in cannot save anything. They get the global values, see the effective values read
  only, and are told to create an account.
- With `SMARTAGRI_ACCOUNTS=off` (local single-user use) the local user is also the administrator; there is no
  anonymous visitor.
- A user can only read and write their own settings and the settings of their own parcels. A parcel of another user
  is answered exactly like a missing parcel (404).

## Administrator role

With `SMARTAGRI_ACCOUNTS=optional` the administrators are the accounts whose email address is listed in
`SMARTAGRI_ADMINS` (comma-separated, compared without regard to case). With email confirmation switched on
(SMTP configured) the address must also be confirmed. Without SMTP an address cannot be verified: register the
administrator account before the server is reachable by others (a second sign-up with the same address is refused),
and keep the list short.

| Variable | Meaning |
|---|---|
| `SMARTAGRI_ACCOUNTS` | `off` (default; the local user is the administrator) or `optional` |
| `SMARTAGRI_ADMINS` | comma-separated email addresses of the administrators (mode `optional` only) |

Administrator endpoints (global values, limits, the log of every level, versions of those levels) answer 403 to
everyone else.

## Limits set by the administrator

For every parameter the administrator sets:

- whether users (and parcels) may override it at all ("user-editable"). The default comes from the registry:
  agronomic values (irrigation, fertilisation, field operations, phenology, soil, crop coefficients, optional
  inputs) are open to users; the structure of the decision model (quality thresholds, required inputs per advice
  type, asking, parcel features) and the irrigation-quantity safety gate are administrator-only until opened;
- the allowed range (`min`, `max`) and, for lists and tables, the number of rows and a range per numeric column.

A value outside the allowed range is refused, at every level including the global one; the administrator's range can
only narrow the registry's own bounds. A value inside the range but outside the **recommended** values of its source
is accepted with a warning that names the source. A user value that was valid when saved and falls outside a limit
set later is ignored in the effective value and reported as ignored. A limit cannot be set so that the current global
value falls outside it.

Cross-parameter relations are checked on every write (for example the cloud-share limit for "high" may not exceed the
one for "medium"). Tables carry their own rules: ordered rows, a catch-all last row, contiguous ranges.

## Source and status

Each parameter shows where its value comes from and how well that is established:

| Status | Meaning |
|---|---|
| verified | the value agrees with the cited source |
| partly verified | the value is inside the source's range, or only part of the group of values is covered |
| disputed | the value disagrees with the cited source (a code change is needed to fix it) |
| no source | the review of the constants found no external source or could not verify it; the value awaits agronomist review |
| development | a development value that was not part of the review; it awaits agronomist review and no source is claimed |

The status is the outcome of a comparison of the constants with the cited documents (FAO Irrigation and Drainage
Paper 56, FAO Irrigation Water Management Training Manual 4, and others listed in the registry); it is not an
agronomic approval. The citation and its link are stored with the parameter in
`web_settings/registry.py`, never a source that was not opened.

## Evaluation is isolated

`evalkit`, the protocol lock, the blind rating screen and its endpoints read **only the YAML files**. The effective
settings are carried in a context variable (`config.use_overlay`) that is entered by the research API only, once per
request that computes an answer (profile, advice, free conversation, series, water balance). Nothing global is
mutated, no thread other than the request's sees it, and without an overlay `config.load()` returns the cached file
data itself. The file hashes in `config.config_hashes()` and in the protocol lock are unchanged. A test fails if any
module under `core/`, `evalkit/`, `pipeline/`, `retrieval/` or `providers/` refers to the overlay or to the settings
package.

Every web answer records the settings it was computed with, in `provenance.settings`, in the "Why?" panel and in the
JSON export (`settings_used`):

```json
{"version": "g1.u2.p0", "hash": "<sha256 of the overrides>", "layers": {"global": 1, "user": 2, "parcel": 0},
 "n_overrides": 1, "snapshot": {"rules.irrigation.max_single_net_mm": {"value": 40, "layer": "user"}},
 "ignored": [], "defaults": "config files (hashes in config_hashes)"}
```

The files' hashes plus this block reconstruct every value the answer used. With no overrides the block says so
(`n_overrides: 0`) and the decision is byte-identical to the one computed from the files; this is tested on every
development scenario and every variant.

Settings that act when a profile is built (the base temperature of the growing-degree-day sum) apply when the parcel
profile is refreshed; the decision parameters apply to the next answer.

## History

- **Audit log** (append-only; the database refuses UPDATE and DELETE): who, when, level, parameter, old value, new
  value, action and reason, one row per parameter changed. A user sees the log of their own settings and of their own
  parcels; an administrator sees every level and can filter by user, parameter, action and date.
- **Versions**: every change writes a version, the whole set of that level afterwards. **Restore** goes back to a
  previous version (the whole set or one parameter) or to the file default (the whole level or one parameter). A
  restore is a new version; nothing is deleted. A restored set is validated again against the current registry and
  limits.
- Changes of the global level and of the limits need a reason. A write can carry `base_version`; when the level has
  changed since, the answer is 409.
- Deleting an account removes the user's current settings; the history keeps only the opaque user id.

## HTTP API

All under `/api/settings`. State-changing requests carry the CSRF token and Origin checks of the accounts mode (and an
Origin check in the local mode) and are rate limited per user.

| Request | Purpose |
|---|---|
| `GET /api/settings[?parcel_id=]` | the registry with defaults, bounds, recommended values, source, status, the layers and the effective value of every parameter, the capabilities of the caller |
| `GET /api/settings/protocol` | the locked protocol files, read only, with the reason |
| `PUT /api/settings/user`, `/global`, `/parcels/{id}` | set (`{"values": {key: value}, "reason": "", "base_version": n}`); a `null` value removes the override |
| `POST /api/settings/user/reset`, `/global/reset`, `/parcels/{id}/reset` | remove overrides (`{"keys": [...]}` or `{"all": true}`) |
| `GET /api/settings/versions?scope=&parcel_id=` | versions of a level |
| `POST /api/settings/restore` | `{"scope", "parcel_id", "version": n \| "default", "keys": [...]}` |
| `GET /api/settings/audit?scope=&parcel_id=&param=&who=&since=&until=&action=&limit=&offset=` | the audit log |
| `GET/PUT /api/settings/limits` | administrator: user-editable switch and ranges |

A refused write answers 400 with `{"detail": "Some values were refused.", "errors": [{"key", "code", "params"}]}`:
generic text, and a code the client turns into a message. Unknown keys are refused.

## Which parameters are editable

The registry covers every leaf of `rules.yaml`, `kc_maize.yaml`, `thresholds.yaml`, `asking.yaml`,
`requirements.yaml` and `parcel_features.yaml` (about 210 parameters; lists, maps and tables are one parameter each
and are edited as a whole, with their shape validated). A test fails when a YAML key has no registry entry.

Shown but not editable:

- `parcel_features.schema_version` (the version of the data contract the validator enforces) and the four
  `status` labels of `parcel_features.yaml` (a recorded label, read by no rule);
- `asking.inputs.<input>.user_obtainable` for the inputs that have no question text in the file: making them
  askable needs a text first, which is a file edit;
- the **protocol files** `variants.yaml`, `analysis.yaml`, `evaluation.yaml` and `vocab.yaml`: they define the
  experiment (and the controlled vocabulary the corpus is checked against) and are locked. They are listed read-only
  in the settings view.

Not in any file, so not settable here (each needs a code change): the depletion fractions per soil-water class
(`DEPLETION_BY_STATUS` in `core/tools/water_balance.py`), the small-parcel limit (`SMALL_PARCEL_HA` in
`core/quality.py`), the minimum share for the NDVI trend (`core/tools/ndvi_stats.py`), the factor of 5 for heavy
rain in the decision core (the 72 h window card reads its own value from `rules.yaml`), and the two-day horizon of
"irrigate soon". The open agronomy issues listed in [limitations.md](limitations.md) (soil-texture-dependent bands of
the sensor, a nitrogen cap in kg N/ha, interpolation of Kc through the late stage, a soil-temperature check for
sowing) cannot be fixed by a setting either; they need code changes.

## Adding a parameter

1. Add the key to its YAML file with its default (the file is the only place a default lives).
2. Add a `Spec` to `SPECS` in `web_settings/registry.py`: key path (a `*` matches every key at that place), kind
   (`bool`, `int`, `float`, `str`, `enum`, `pair`, `list`, `map`, `table`, `groups`), group, label in English and
   Serbian, unit, bounds, columns for a table, the source key and status, a note, and whether users may change it by
   default. Put a specific declaration before a wildcard one. A recommended range is given only where the source gives
   a range.
3. Add the source to `SOURCES` if it is new. Do not claim a source that was not opened; use status `development` or
   `no source` and say so.
4. Run `pytest backend/tests/test_web_settings.py`. The coverage test names any leaf without an entry; the
   catalogue test requires both languages for the client strings (`static/i18n.js`).
5. A change of a default value in a YAML file changes the file hashes and the protocol lock; the settings code does not.

Changing the shape of a file (a key renamed or removed) leaves stored overrides for the old key; they are ignored and
reported, never applied to a different key.
