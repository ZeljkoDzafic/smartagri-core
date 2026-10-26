# Architecture decision records

Short records of decisions that shape the code. Each one states the context, the decision, its consequences and
where the decision can be seen in the code. A record is not edited after it is accepted; a later decision that
changes it gets a new record that supersedes it.

| No. | Decision | Status |
|---|---|---|
| [0001](0001-deterministic-decision-before-generation.md) | Deterministic decision layers before any text generation | Accepted |
| [0002](0002-numbers-from-code.md) | Agronomic numbers come from code, never from a language model | Accepted |
| [0003](0003-offline-first-no-keys.md) | Offline first; no keys required | Accepted |
| [0004](0004-sqlite-default-postgresql-optional.md) | SQLite by default, PostgreSQL optional | Accepted |
| [0005](0005-vanilla-js-client-without-build.md) | A plain JavaScript client without a build step | Accepted |
