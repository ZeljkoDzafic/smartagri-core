# Security policy

SmartAgri core can run as a public web app with accounts (`SMARTAGRI_ACCOUNTS=optional`, see
[docs/deployment.md](docs/deployment.md)): it stores email addresses, password hashes, session token hashes and
users' parcels and conversations. Reports about that surface are especially welcome.

## Reporting a vulnerability

Email **zeljkodzafic@gmail.com** with the subject `SmartAgri security`. Please do not open a public issue or pull
request for a vulnerability.

Include what you can of the following: the affected version or commit, the configuration (accounts mode, database,
reverse proxy), steps to reproduce, the impact you expect, and whether the issue is already public.

What to expect:

- an acknowledgement within 7 days;
- an assessment, and a planned fix or the reason for declining, within 30 days;
- a fix released as a new version with a **Security** entry in [CHANGELOG.md](CHANGELOG.md), and credit to the
  reporter unless they prefer otherwise.

This is a project maintained by one person; the times above are targets, not a contractual commitment. Please give
the maintainer a reasonable time to release a fix before any public disclosure.

## Supported versions

| Version | Supported |
|---|---|
| `main` branch and the latest tagged release | yes |
| older releases | no; upgrade to the latest release |

Python 3.12 with `backend/requirements.lock` is the supported environment for a public server (it is what the
container image uses). The Python 3.9 pin set (`backend/constraints-py39.txt`) is kept for development and CI only:
its header lists advisories that cannot be fixed on Python 3.9. Do not run a public server on Python 3.9.

## Scope

In scope:

- the research web app and API (`backend/src/smartagri/research_api/`): accounts, passwords, sessions, cookies, CSRF
  and Origin checks, rate limits, separation of one user's or one anonymous session's parcels from another's,
  email links for confirmation and password reset, purging of anonymous data, account deletion;
- the web settings (`backend/src/smartagri/web_settings/`, `research_api/settings_routes.py`): the separation of one
  user's settings and parcel settings from another's, the administrator role (the operator command `--make-admin` and
  `SMARTAGRI_ADMINS`, including any way to obtain the role by registering an address first) and the endpoints that need it,
  the validation of every value against the registry, its default limits and the administrator's limits, the CSRF and
  rate limits of the write endpoints, and the append-only history;
- the client address behind a reverse proxy (`SMARTAGRI_TRUSTED_PROXIES`, `research_api/proxy.py`): any way to make the app
  count a request under an address that the proxy did not see;
- the request guards (`research_api/guards.py`): the body size and JSON limits, the security headers and the
  Content-Security-Policy;
- the container image (`Dockerfile`) and the configuration it documents;
- storage (`backend/src/smartagri/store.py`) and the external-cache handling (`backend/src/smartagri/cache.py`);
- pinned dependencies with a known vulnerability that affects this code (`backend/requirements.lock`);
- disclosure of secrets (API keys, SMTP credentials) through logs, responses or the provenance export.

Out of scope:

- a web setting that makes the advice agronomically worse inside the range an administrator allowed: the ranges are
  validation bounds and the recommended values come from cited sources, but no setting is an agronomic approval;

- the blind rating endpoints (`/api/eval/`), which by design are outside accounts and the CSRF checks; the deployment
  guide states that blind rating is run locally and not on a public server;
- a server run with `SMARTAGRI_ACCOUNTS=off` and exposed to the internet: that mode is local single-user use and
  shows every parcel to everyone who can reach it;
- vulnerabilities in third-party services (Open-Meteo, Copernicus Data Space, tile servers, language model
  providers) or in a reverse proxy configured differently from [docs/deployment.md](docs/deployment.md);
- the static presentation website (`website/`), unless it exposes something beyond public static files;
- incorrect or unsafe agronomic advice. That is a correctness problem, not a security vulnerability: please open an
  issue with the parcel, the question and the answer (see [docs/limitations.md](docs/limitations.md)).

## Operator responsibilities

Whoever runs a public server is responsible for TLS, the reverse proxy, backups, keeping the image up to date and the
privacy notice; see [docs/deployment.md](docs/deployment.md) and the Privacy section of [README.md](README.md).
The administrators of the web settings are the accounts that the operator promoted on the server
(`python -m smartagri.research_api --make-admin EMAIL`) and, with SMTP configured, the accounts whose listed address
(`SMARTAGRI_ADMINS`) was confirmed through its mailbox. Without SMTP an address cannot be proven, so listing it grants
nothing: promote the owner with the command before announcing the server, and keep the list short (see
[docs/settings.md](docs/settings.md) and the first-run steps in [docs/deployment.md](docs/deployment.md)). Set
`SMARTAGRI_TRUSTED_PROXIES` to your proxy's address, never to `*`.

## Known gaps

Written down so that nobody assumes otherwise; each is listed in [docs/deployment.md](docs/deployment.md), section 8:

- no limit on outbound provider calls (weather, Sentinel-2) or on language-model spending per visitor;
- no limit on the number of parcels per owner;
- the blind rating endpoints are reachable on a public server (run blind rating locally);
- the web client accepts a tile address set in the browser, but the Content-Security-Policy only lets it load tiles from the
  host the operator configured.
