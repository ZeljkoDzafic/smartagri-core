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

With `SMARTAGRI_ACCOUNTS=off` the local user is the administrator. With `SMARTAGRI_ACCOUNTS=optional` an account is an
administrator in exactly two cases:

1. **The operator promoted it on the server.** `python -m smartagri.research_api --make-admin EMAIL` is run by whoever
   controls the server (in the container: `docker exec -it smartagri python -m smartagri.research_api --make-admin EMAIL`).
   It never works over HTTP. The grant is stored in the database and written to the audit log (level `admin_role`,
   actor `operator (server command)`).
2. **Its address is listed in `SMARTAGRI_ADMINS` and was confirmed through that mailbox** (SMTP configured; see
   [deployment.md](deployment.md)). Listing an address grants nothing by itself: an account that nobody confirmed through
   its mailbox, which is every account on a server without SMTP, is never an administrator because its address is listed.

Why: without SMTP a server cannot tell who owns an address, so "register the administrator account first" would hand the
role to whoever registers the listed address first (the audit that found this reproduced it: a sign-up with the owner's
address got the role and locked the owner out).

What the command does, and what happens when the address is already taken:

| Situation | `--make-admin EMAIL` |
|---|---|
| no such account | creates it (asks for a password; `--password-stdin` reads it from standard input) and marks it as confirmed by the operator |
| an account that was never confirmed through its mailbox (someone signed up with the address first) | **takes it over**: asks for a new password, the old password stops working, every session and pending link of the account ends; then promotes it |
| an account confirmed through its mailbox | adds the role and changes nothing else |
| any existing account with `--reset-password` | also replaces the password and ends its sessions (an administrator who lost the password on a server without email) |

`python -m smartagri.research_api --revoke-admin EMAIL` removes the role and ends the account's sessions. An address that is
still listed in `SMARTAGRI_ADMINS` and confirmed through its mailbox stays an administrator until it is removed from the
list; the command says so.

Sign-up with an address listed in `SMARTAGRI_ADMINS`:

- **SMTP off:** refused with the answer for a taken address (409). The owner does not have to be first: nobody can take the
  address, and the operator creates the account with the command above.
- **SMTP on:** the sign-up is accepted like any other, but the mail that goes to that address carries a link that **sets the
  password** instead of a "confirm" link, and an account listed as an administrator cannot be confirmed by the ordinary
  link. Whoever signed up first with someone else's address therefore cannot keep their password: the mailbox owner's link
  replaces it. An owner who never saw the mail uses "forgot password" (it ends the same way).

| Variable | Meaning |
|---|---|
| `SMARTAGRI_ACCOUNTS` | `off` (default; the local user is the administrator) or `optional` |
| `SMARTAGRI_ADMINS` | comma-separated email addresses that may become administrators by confirming the mailbox (mode `optional` only, compared without regard to case); the operator command does not need it |

Administrator endpoints (global values, limits, the log of every level, versions of those levels) answer 403 to
everyone else.

## Limits set by the administrator

For every parameter the administrator sets:

- whether users (and parcels) may override it at all ("user-editable"). The default comes from the registry:
  agronomic values (irrigation, fertilisation, field operations, phenology, soil, crop coefficients, optional
  inputs) are open to users; the structure of the decision model (quality thresholds, required inputs per advice
  type, asking, parcel features) and the irrigation-quantity safety gate are administrator-only until opened;
- the allowed range (`min`, `max`) and, for lists and tables, the number of rows and a range per numeric column.

### Three nested ranges

Every numeric value has three ranges, one inside the other:

| Range | Meaning | Who sets it |
|---|---|---|
| **physical bounds** | what the quantity can be at all (a share is between 0 and 1; wind up to 40 m/s) | the registry; no setting changes it |
| **default limit** | what is accepted until the administrator sets a limit for that parameter; a value outside it is refused | the registry; the administrator may narrow it or widen it up to the physical bounds |
| **recommended range** | a value between this range and the limit is accepted with a warning | the registry |

The physical bounds alone were too wide to protect anything (a wind limit for spraying of 40 m/s, a rain wait of 0 mm that
means "always wait", a soil-sensor band of 0.01-0.02). The default limits are narrower on purpose, and the file default is
always inside the recommended range, so resetting never produces a warning.

Where a range comes from, stated for every range (`range_basis` in the API):

- **source**: the cited document gives a range. Used for the largest net depth per irrigation (15-70 mm, FAO Training
  Manual 4, Table 4), the available water capacity per texture (FAO-56 Table 19, a range per texture), the single crop
  coefficient (0.30-1.20, the maize values of FAO-56 Table 12) and the nitrogen share of four fertilisers (the
  stoichiometric maximum of the pure compound; the limit is that maximum). The default limit is the source range widened
  by a quarter of its width on each side, rounded outward.
- **development**: no source gives a range, so both ranges are a conservative band around the default in the file, called a
  **development limit**, not a citation. Around a positive default the recommended range is the default -30 % to +30 % and
  the limit is half to double; for stages (BBCH), temperatures, pH and NDVI differences the band is an absolute distance
  (recommended +-5 stages, limit +-15; +-2 and +-5 degrees C; and so on); a table column takes the band around the smallest
  and the largest value in its rows. The bands are computed from the files, so a changed default moves its band. They are
  not agronomic advice: an agronomist should replace them where a source exists, by giving the declaration a
  `recommended` range (see below).

The client shows the allowed range, the recommended range and whether it is a source or a development band, and warns while
typing when a value leaves the recommended range (with the source for a source range, and "no source is claimed" for a
development band). The same warnings are returned by the API after a save.

A value outside the allowed range is refused, at every level including the global one; the administrator's range can
only narrow the physical bounds. A value inside the range but outside the recommended range is accepted with a warning
that names the source where there is one. A user value that was valid when saved and falls outside a limit set later is
ignored in the effective value and reported as ignored. A limit cannot be set so that the current global value falls
outside it.

Cross-parameter relations are checked on every write (for example the cloud-share limit for "high" may not exceed the
one for "medium"). Tables carry their own rules: ordered rows, a catch-all last row, contiguous ranges.

### "Custom settings applied"

Every answer that was computed with at least one value that differs from the files shows **Custom settings applied** on
the answer card and in the "Why?" panel: the number of values that differ and how many of them are outside the recommended
range. The "Why?" panel lists the values with their level and marks those outside the recommended range. An answer from the
files alone shows no notice. The same facts are in `provenance.settings` (`n_overrides`, `outside_recommended`).

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
 "ignored": [], "outside_recommended": [], "defaults": "config files (hashes in config_hashes)"}
```

The files' hashes plus this block reconstruct every value the answer used. With no overrides the block says so
(`n_overrides: 0`) and the decision is byte-identical to the one computed from the files; this is tested against stored
digests of every development scenario and every variant (`backend/tests/golden_dev/`; ids and timestamps removed; the
file is rewritten only by `python tests/golden_dev/update.py`, run on purpose when a decision is meant to change). Two
requests that run at the same moment with different settings each see only their own (tested).

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
| `GET /api/settings[?parcel_id=]` | the registry with defaults, physical bounds (`hard`), the bounds that apply now (`bounds`), the default limit (`default_limit`), the recommended range (`recommended`) and where it comes from (`range_basis`), source, status, the layers and the effective value of every parameter, the capabilities of the caller |
| `GET /api/settings/protocol` | the locked protocol files, read only, with the reason |
| `PUT /api/settings/user`, `/global`, `/parcels/{id}` | set (`{"values": {key: value}, "reason": "", "base_version": n}`); a `null` value removes the override |
| `POST /api/settings/user/reset`, `/global/reset`, `/parcels/{id}/reset` | remove overrides (`{"keys": [...]}` or `{"all": true}`) |
| `GET /api/settings/versions?scope=&parcel_id=` | versions of a level |
| `POST /api/settings/restore` | `{"scope", "parcel_id", "version": n \| "default", "keys": [...]}` |
| `GET /api/settings/audit?scope=&parcel_id=&param=&who=&since=&until=&action=&limit=&offset=` | the audit log (administrator: also `scope=admin_role`, the operator's grants and revocations) |
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
   a range; then give the declaration `recommended` (and, if the default limit should not be the source range widened by a
   quarter, `limit`), in the shape of the value (a pair for a number, a dictionary per key or column). Without them the
   registry derives a development band around the file default.
3. Add the source to `SOURCES` if it is new. Do not claim a source that was not opened; use status `development` or
   `no source` and say so.
4. Run `pytest backend/tests/test_web_settings.py`. The coverage test names any leaf without an entry; the
   catalogue test requires both languages for the client strings (`static/i18n.js`).
5. A change of a default value in a YAML file changes the file hashes and the protocol lock; the settings code does not.

Changing the shape of a file (a key renamed or removed) leaves stored overrides for the old key; they are ignored and
reported, never applied to a different key.
