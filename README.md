# SmartAgri core

[![ci](https://github.com/ZeljkoDzafic/smartagri-core/actions/workflows/ci.yml/badge.svg)](https://github.com/ZeljkoDzafic/smartagri-core/actions/workflows/ci.yml)

SmartAgri is an open, testable core for **active, uncertainty-aware agronomic advice**. It answers a farmer's
question about one parcel (maize) and decides, before any text is generated, whether it may advise at all: recommend,
give a conditional answer, ask a follow-up question, or abstain (with a referral to the extension service when the
question is out of scope or the corpus does not cover it).

The decision is made by explicit, deterministic layers; a language model (optional) only phrases the answer.

- **C** the decision context: parcel, agronomic inputs, Open-Meteo weather and Sentinel-2 L2A NDVI;
- **π** applicability of each knowledge passage (deterministic filter over passage metadata: crop, stage, region,
  date, source type);
- **q** quality of each input (origin, age, coverage, reliability);
- **σ** sufficiency of the inputs for the requested type of advice;
- **α** choice of the next question;
- **δ** the decision policy (recommend, conditional, ask, abstain, refer);
- **γ** grounding checks of the answer (numbers come from tools, sentences must be supported by passages).

Agronomic numbers are computed in code (FAO-56: ETc = Kc × ET0, water balance, gross dose = net / efficiency), never
by the language model.

## Contents

| Path | What |
|---|---|
| `backend/src/smartagri/core/` | decision model π, q, σ, α, δ, FAO-56 tools, grounding |
| `backend/src/smartagri/retrieval/` | corpus loading, BM25 + vector retrieval with rank fusion, corpus ingest and coverage |
| `backend/src/smartagri/pipeline/`, `providers/`, `llm/` | answer generation and judge, weather and satellite adapters, LLM providers |
| `backend/src/smartagri/evalkit/` | `python -m smartagri.evalkit run / report / export / guard / sweep / lock` |
| `backend/src/smartagri/research_api/` | minimal HTTP API and the web app (map drawing, profile, weather and NDVI, water balance, advice, provenance, evaluation overview, blind rating) |
| `backend/config/` | rules, thresholds, variants, question bank, Kc table (locked with the evaluation protocol) |
| `backend/corpus/` | corpus manifest (licence per document) and passages |
| `backend/eval/scenarios/dev/` | development scenarios; held-out test scenarios are published only after the protocol lock |
| `docs/` | architecture overview, evaluation protocol, rater guide |
| `website/`, `tools/check_presentation_site.py`, `wrangler.jsonc` | static presentation site, its check and its Cloudflare deployment |
| `Dockerfile`, `docs/deployment.md` | container image and guide for a public deployment of the web app with accounts |

## Install and test

Python 3.9 or newer. Docker is not required.

```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -c constraints-py39.txt -e ".[dev,api]"      # Python 3.12: -c requirements.lock
pytest -q                                                # SQLite, offline; no keys needed
```

`.env.example` lists the optional settings: LLM provider, Copernicus credentials, offline mode and the answer
language (`SMARTAGRI_LOCALE`, default `en`). Without any of
them the system uses the deterministic template generator and works without network access to models.

## Run

```bash
cd backend && . .venv/bin/activate
python -m smartagri.research_api            # http://127.0.0.1:8100 — local use, no accounts
```

Locally there are no accounts and no cookies: everyone who can reach the server sees every parcel, as a single-user
research tool should. For a public server, see [Accounts](#accounts) and [`docs/deployment.md`](docs/deployment.md).

## Web app

![SmartAgri web app: the question "When should I irrigate?" and an answer card with a conditional recommendation, its follow-up question, the reasoning, the calculations and the data used with their reliability](website/assets/images/web-advice.png)

Open `http://127.0.0.1:8100`. Draw a parcel on the map (or paste or import a GeoJSON polygon), fetch its profile and
see each input with its origin, age and reliability (q), ask a question under any variant V0–V5, answer the
follow-up question, and open "Why?" to see the π, q, σ, α, δ and γ decisions and the provenance hashes ("Download
provenance (JSON)" saves the whole answer with its decisions, sources, inputs and hashes). The parcel page also shows
the stored weather and Sentinel-2 NDVI series with their source and age, and a daily FAO-56 water balance (ET0, Kc,
ETc = Kc × ET0, rainfall, root-zone deficit) computed in code by the core tools; a missing series stays empty. The
read-only Evaluation page shows what `python -m smartagri.evalkit report` computes from the stored runs (development
runs are labelled as such), the leakage guard counts and the protocol lock; it is not linked from the rating screen.

Answers are in English by default. `SMARTAGRI_LOCALE=sr-Latn` switches the answers to the local language (Latin
script); a browser can also choose it in Settings (sent as `X-SmartAgri-Lang`). Questions are recognised in English
and in the local language. Sources are quoted in their original language: the passages of the published corpus are
short paraphrases in Serbian, so source titles and excerpts appear in Serbian. Evaluation runs never go through the
API and always use the default locale, so the answer language does not change any result. The VC chat (a free LLM
conversation with the same data and sources) answers in the language of the message and needs `LLM_PROVIDER`. The
blind rating screen shows only the blinded item and the rubric, in the wording of the rater guide.

The client has no build step and loads nothing from a CDN; Leaflet 1.9.4 is vendored with its licence
(`research_api/static/vendor/leaflet/`). OpenStreetMap tiles are its only external request:
`SMARTAGRI_TILE_URL` sets another tile server (`none` turns tiles off; drawing still works) and
`SMARTAGRI_TILE_ATTRIBUTION` its attribution. Light and dark themes follow the system or the settings sheet.

## Accounts

Accounts are optional and off by default. `SMARTAGRI_ACCOUNTS` selects the mode:

| Mode | Behaviour |
|---|---|
| `off` (default) | Local single-user use, unchanged: no accounts, no cookies, every parcel is visible to everyone who can reach the server. |
| `optional` | For a public server. Anyone can draw a parcel and ask for advice without an account, but to **save** a parcel they create an account or sign in. Until then the parcel and its conversations are temporary: they belong to the browser session (an anonymous, HttpOnly session cookie that ends when the browser closes; the server keeps only its hash) and are deleted after `SMARTAGRI_ANON_TTL_HOURS` (default 24) without activity. Signing up or signing in saves that session's parcels to the account. Each user sees only their own parcels, and each anonymous session only its own. |

With accounts on, the sidebar shows **Sign in** (or the signed-in email, with Sign out and Delete account). For an
anonymous visitor every parcel is marked **Not saved**, with a **Save parcel** action and the note "Temporary — this
parcel is kept only for this browser session. Create an account to save it."; leaving the page with unsaved parcels
asks for confirmation. Accounts use an email address and a
password (at least 10 characters, stored as a scrypt hash). Email confirmation and password reset are available only
when SMTP is configured; without SMTP an account works as soon as it is created.

Protection: rate limits on every sign-in, sign-up and reset endpoint, login throttling per email and per address,
generic error messages, HttpOnly + SameSite=Lax cookies (Secure on https, host-only), sessions that expire
(`SMARTAGRI_SESSION_DAYS`, default 30) and end on sign-out, and a CSRF check (double-submit token and Origin) on every
state-changing request. The blind rating screen and its endpoints do not depend on accounts at all, and evaluation
runs never go through the API.

Parcels stored while accounts were off have no owner; with accounts on they are not shown to anyone until the
operator gives them to an account: `python -m smartagri.research_api --assign-unowned you@example.org`.

| Variable | Meaning |
|---|---|
| `SMARTAGRI_ACCOUNTS` | `off` (default) or `optional` |
| `SMARTAGRI_PUBLIC_URL` | public address, e.g. `https://app.smartagri.rs.ba`; used for email links, the Origin check and Secure cookies |
| `SMARTAGRI_ANON_TTL_HOURS` | hours without activity after which anonymous (not saved) parcels are deleted (default 24); purged lazily on requests and by `python -m smartagri.research_api --purge-anonymous` |
| `SMARTAGRI_SESSION_DAYS` | session lifetime in days (default 30) |
| `SMARTAGRI_COOKIE_SECURE` | `1` forces Secure cookies (automatic on https) |
| `SMARTAGRI_AUTH_RATE_FACTOR` | multiplies the per-address rate limits (default 1), e.g. many users behind one NAT |
| `SMARTAGRI_SMTP_HOST`, `_PORT`, `_TLS`, `_USER`, `_PASSWORD`, `_FROM` | outgoing email; confirmation and reset are on only when host, sender and `SMARTAGRI_PUBLIC_URL` are set |

### Privacy

With accounts on, the server stores: the email address and a password hash of each account; hashes of session and
one-time link tokens (never the tokens); the hash of each anonymous session token that created a parcel, with the
time of its last activity; and the parcels themselves (name, boundary, agronomic inputs), their data profiles, conversations and answers. Three cookies
are set, all strictly necessary and first-party: `sa_session` (sign-in), `sa_browser` (anonymous ownership) and
`sa_csrf` (request check); `sa_browser` is a session cookie and ends when the browser closes. There is no analytics and no tracking. The browser loads map tiles from the configured tile
server (OpenStreetMap by default), which sees the visitor's address; the server sends parcel coordinates to
Open-Meteo and, when configured, to Copernicus Data Space, and questions with parcel data to a language model only
when `LLM_PROVIDER` is set. **Delete account** removes the account, its sessions and links, and its parcels with their
profiles, conversations and answers. Anonymous parcels, with their profiles, conversations and answers, are deleted
automatically after `SMARTAGRI_ANON_TTL_HOURS` (default 24) without activity; signing out starts a new, empty
anonymous session. Whoever runs a public server is responsible for its privacy
notice and its backups, which keep deleted data until they expire.

## Website

A static presentation of the project lives in [`website/`](website/). It is deployed to Cloudflare as static assets
of a Worker (`wrangler.jsonc`, workflow `Deploy website to Cloudflare`), currently at
<https://smartagri-core.calm-silence-b9f5.workers.dev>, with the custom domain `smartagri.rs.ba` to follow. GitHub
Pages remains an alternative (workflow `Deploy website to GitHub Pages`, run by hand). See
[`website/README.md`](website/README.md).

## Evaluation

`evalkit` runs an ablation ladder of variants V0–V5 (each rung adds one layer) and the LLM baseline VC over scenario
sets, and supports blind rating, bootstrap intervals, rater agreement, a leakage guard and a protocol lock.
See [`docs/evaluation.md`](docs/evaluation.md).

```bash
python -m smartagri.evalkit run --set dev && python -m smartagri.evalkit report
```

## Corpus licences

`backend/corpus/manifest.yaml` gives the source, URL and licence of every document. The published passages are short
paraphrases with citations, or the author's own notes. A document whose licence does not allow redistribution is
published as metadata only (title, URL, licence); the corpus hash recorded in every run lets you check a locally
rebuilt corpus.

## Data sources and standards

FAO Irrigation and Drainage Paper 56 (crop coefficients, ET0, water balance), BBCH growth stages, Open-Meteo
(forecast, historical and previous-runs APIs), Copernicus Data Space Ecosystem (Sentinel-2 L2A, Statistical API),
OpenStreetMap. Each keeps its own licence and terms.

## Licence

MIT (`LICENSE`). Cite with `CITATION.cff`. A commercial product built on this core is developed separately; it is
not needed to run, check or reproduce anything here.
