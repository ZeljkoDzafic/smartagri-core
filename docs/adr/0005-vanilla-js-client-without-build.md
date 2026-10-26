# 0005. A plain JavaScript client without a build step

- Status: Accepted
- Date: 2026-10-21

## Context

The web app is a research tool: it should be readable and modifiable by someone who knows HTML and JavaScript, run
from a Python install without Node.js, and load nothing from third-party CDNs (privacy, offline use, a stable
artefact).

## Decision

The client is static HTML, CSS and plain JavaScript in `backend/src/smartagri/research_api/static/`, served by the
same FastAPI process as the API. There is no bundler, transpiler or package manager. The only library, Leaflet
1.9.4, is vendored with its licence (`static/vendor/leaflet/`). Map tiles are the only external request and can be
changed or switched off (`SMARTAGRI_TILE_URL`). Interface text comes from a catalogue in `static/i18n.js`.

## Consequences

- `pip install` is the whole setup; the files the browser runs are the files in the repository.
- The client is shipped as package data of the Python package (`backend/pyproject.toml`).
- Without a type checker or a module bundler, the client relies on the API tests (`tests/test_research_api.py`) and
  manual checks; there are no browser tests in CI.
- Leaflet updates are manual; see [NOTICE](../../NOTICE).
