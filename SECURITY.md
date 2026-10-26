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
- the container image (`Dockerfile`) and the configuration it documents;
- storage (`backend/src/smartagri/store.py`) and the external-cache handling (`backend/src/smartagri/cache.py`);
- pinned dependencies with a known vulnerability that affects this code (`backend/requirements.lock`);
- disclosure of secrets (API keys, SMTP credentials) through logs, responses or the provenance export.

Out of scope:

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
