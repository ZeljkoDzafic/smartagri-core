# Reproducibility

This page describes how to install the core from a clean checkout, run the development evaluation, produce the
report, what the protocol lock records, and how the results tables of a reported experiment are to be reproduced from
a tagged release. The evaluation protocol itself (outcomes, analysis plan, rater design and the full content of the
lock) is in [protocol.md](protocol.md).

## 1. Clean install

Python 3.12 is the recommended and primary environment; Python 3.9 is supported for development. No Docker, network
access or API keys are needed.

```bash
git clone https://github.com/ZeljkoDzafic/smartagri-core.git
cd smartagri-core/backend
python3.12 -m venv .venv && . .venv/bin/activate
python -m pip install --upgrade pip setuptools
pip install -c requirements.lock -e ".[dev,api,ingest]"
```

- `requirements.lock` pins every dependency for Python 3.12 (it is also what the container image and the 3.12 CI
  job use). For Python 3.9 use `-c constraints-py39.txt` instead; its header lists the advisories that remain only
  on 3.9.
- Upgrade pip and setuptools first. An old pip or setuptools (for example the pip 21 that comes with the stock
  Python 3.9 of macOS) cannot perform an editable install from `pyproject.toml`; editable installs need
  setuptools 64 or newer (PEP 660).
- For a tagged release, check out the tag first (`git checkout vX.Y.Z`); the tag, `backend/pyproject.toml`,
  `CITATION.cff` and the `CHANGELOG.md` heading carry the same version.

## 2. Environment

Every command below runs offline with the deterministic template generator:

```bash
export LLM_PROVIDER=template EMBEDDINGS_PROVIDER=none SMARTAGRI_OFFLINE=1
```

`.env.example` (repository root) documents every setting. The code does not read a `.env` file by itself; to use
one, copy `.env.example` to `.env`, edit it and export it into the shell before starting a command, for example
`set -a; . ../.env; set +a` from `backend/`.

`SMARTAGRI_OFFLINE=1` makes every weather and satellite request answer from the external cache only (or report the
input as missing); nothing leaves the machine.

## 3. Checks

```bash
ruff check src tests
pytest -q                                              # SQLite in memory, no keys, no network
python -m smartagri.evalkit guard --set dev > /dev/null  # leakage guard on the development set
python ../examples/advise_one_parcel.py                # one parcel, one question, act and provenance
```

These are the steps of the CI test job (`.github/workflows/ci.yml`).

## 4. Development evaluation and report

```bash
export SMARTAGRI_DB=$PWD/dev-run.sqlite                # a fresh database for this run
python -m smartagri.evalkit run --set dev              # 15 development scenarios under every variant
python -m smartagri.evalkit report                     # automatic measures, JSON
python -m smartagri.evalkit report --format md         # the same measures as Markdown tables
python -m smartagri.evalkit export --out dev-run.json  # items (and ratings, if any) as JSON
```

- Without `SMARTAGRI_DB` the runs go to `smartagri.sqlite` in the current directory (`store.py`), or to PostgreSQL
  when `DATABASE_URL` is set. `report` and `export` refuse a database that holds more than one scenario set unless
  `--set` names one; `--batch` (repeatable) restricts them to given runs. A fresh database per run is still simplest.
- With the template generator, two runs on the same checkout give the same report apart from identifiers, timestamps
  and timings.
- The development set is a regression check: its expectations were written by the developer, and its references
  point to `eval/scenarios/dev/_passages.yaml`. See [limitations.md](limitations.md#evaluation). Its numbers are not
  results of an experiment.
- Report tables are labelled in Serbian (Latin script), the language of the evaluation material.

## 5. What the protocol lock records

`python -m smartagri.evalkit lock --set <set>` writes `backend/eval/protocol-lock.json` (format
`smartagri-protocol-lock/3`, `evalkit/lock.py`; format 1 and 2 locks are still read and are reported as lacking an
environment or a run section: re-lock with this version). For the protected test set `--cache-snapshot` is mandatory, and the lock is refused while source,
config, corpus, rater guide or analysis plan have uncommitted changes. It records:

| Field | Content |
|---|---|
| `files` | sha256 of every scenario file of the set, every corpus file, every `config/*.yaml` file (including `evaluation.yaml`, the pinned model settings, and `analysis.yaml`, the parameters of the analysis plan), the rater guide (`docs/RATER_GUIDE.md`), the analysis plan (`docs/protocol.md`), the VC and judge prompts and the external-cache snapshot |
| `prompt_hash` | sha256 of the generator's system prompt and answer schema |
| `run` | how the protocol is executed: `repeats` per scenario and variant, the `variants` of the lock (null = not restricted) and `decision_hour_utc` (null = decision moments as written in the files). Part of the fingerprint; `run --locked` must use the same values |
| `protocol_sha256` | fingerprint of `files`, `prompt_hash` and `run` |
| `environment` | git commit and uncommitted guarded paths, `src_sha256` (one hash over the source tree `backend/src/smartagri`), sha256 of `requirements.lock`, the Python version, the model settings of `config/evaluation.yaml`, the generator the environment selects, and `ADVICE_GENERATOR`, `LLM_PROVIDER`, `LLM_MODEL`, `LLM_EFFORT`, `EMBEDDINGS_PROVIDER`, `EMBEDDINGS_MODEL`, `GROUNDING_JUDGE`, `JUDGE_MODEL`, `SMARTAGRI_LOCALE` |
| `combined_sha256` | one fingerprint over all of the above |
| `set`, `tag`, `created_at`, `cache_snapshot` | the scenario set, the protocol tag (default `protocol-v1`), the time of locking and the snapshot path |

`lock --check` recomputes everything and lists every difference; `run --set test --locked` refuses to run when
anything differs except the commit itself (committing the lock file moves HEAD; `src_sha256` binds the code). The lock
a locked run uses is the repository's own (`backend/eval/protocol-lock.json`); any other file is accepted only together
with `--lock-sha256`, the sha256 of that file as recorded outside the run (a registration, a release note), and must
match it. Every item stores `lock_sha256` (the sha256 of the lock file), `lock_combined_sha256`, `lock_tag`, `repeats` and
`decision_hour_utc`; `report`, `export`, `assign` and the rating queue refuse to mix items of different locks, or of a
lock and an unlocked run (name the batches of one lock). Retrospective sets (`retrospective-dev`, `retrospective-test`;
[retrospective-set.md](retrospective-set.md)) are locked and run the same way, from a folder outside the repository. A run
whose `--scenarios-dir` holds protected scenarios (the set's own folder or a copy of any of its files) is refused
unless it is that protected set under the lock. Every run additionally stores the config hashes, the corpus hash and
the prompt hash it used, and every item records how it was generated (generator, model, effort) and which model
actually answered, with the provider's request ids.

The external cache can be exported and imported for an offline re-run:

```bash
python -m smartagri.cache export --out snapshot.tar      # after the runs that fetched live data
python -m smartagri.cache import snapshot.tar            # on another machine, then SMARTAGRI_OFFLINE=1
```

## 6. Reproducing the results tables of a reported experiment

The held-out test scenarios are published only after the protocol is locked, and no experiment has been reported
from this repository yet. The intended procedure for a results release is:

1. Check out the release tag and install as in section 1 (`requirements.lock`, Python 3.12).
2. Verify the protocol: `python -m smartagri.evalkit lock --check --set test` must report no differences.
3. Import the locked external-cache snapshot with `python -m smartagri.cache import` and set
   `SMARTAGRI_OFFLINE=1`, so that every weather and satellite input is the one that was locked.
4. Re-run the locked set with the locked repeats: `python -m smartagri.evalkit run --set test --locked --repeats <N>`. Template-generator variants are
   deterministic; runs that use a language model are not, and their published outputs are the reference.
5. Rebuild the tables: `python -m smartagri.evalkit report --set test --batch <id> ... --format md`, with
   `--rater`, `--compare` and `--agreement` as listed in [protocol.md](protocol.md).

Known gap in this version: `report` reads the run database, and there is no command yet that rebuilds the tables
from an exported JSON file (`evalkit export` has no inverse). Until there is, a results release has to provide the
rated items in a form `report` can read; [protocol.md](protocol.md) and the release notes of that release state how.

## 7. Building the package

The release workflow (`.github/workflows/release.yml`) builds the sdist and wheel from `backend/` with Python 3.12
(`python -m build`) after the same checks as CI. The wheel contains the Python package only: the configuration,
the corpus and the scenarios stay in the repository. When running from an installed wheel, point to them with
`SMARTAGRI_CONFIG_DIR` (`config.py`) and `SMARTAGRI_CORPUS_DIR` (`retrieval/corpus.py`).
