# 0004. SQLite by default, PostgreSQL optional

- Status: Accepted
- Date: 2026-10-21

## Context

Local research use, tests and CI need storage with no server to install. A public deployment with several processes
and accounts benefits from a database server, and dense retrieval can use a vector index.

## Decision

`store.py` (`make_store`) uses SQLite unless `DATABASE_URL` names a PostgreSQL database. The SQLite file is
`SMARTAGRI_DB` or `./smartagri.sqlite`; tests use SQLite in memory. Records are stored as JSON with key columns, so
both back ends share one schema. With PostgreSQL and `EMBEDDINGS_PROVIDER=fastembed`, passage vectors live in
pgvector (`retrieval/embed.py`, `pgvector_ranker`). The PostgreSQL driver is an optional extra (`pip install
-e ".[pg]"`).

## Consequences

- No database server is needed to run, test or evaluate.
- Storage tests run on both back ends when `TEST_DATABASE_URL` is set (`tests/conftest.py`); CI currently runs them
  on SQLite only, so the PostgreSQL path is tested locally, not in CI.
- A public server on SQLite is limited to one host; the deployment guide covers backups for both back ends
  ([deployment.md](../deployment.md)).
