# Contributing

Thank you for considering a contribution. SmartAgri core is a research prototype whose evaluation depends on
locked files, so some changes are welcome at any time and some need a discussion first.

By participating you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md). Security problems are not reported in
public issues; see [SECURITY.md](SECURITY.md).

## What helps most

- Bug reports with the smallest input that reproduces them (a parcel, a question, the variant and the output).
- Tests for behaviour that is described in the docs but not yet tested.
- Corrections of documentation that does not match the code (cite the file and line).
- Agronomic review of the development values in `backend/config/` and of the corpus passages marked
  `verify: true`, with the source that supports a change (see [docs/limitations.md](docs/limitations.md)).

## Development setup

Python 3.12 is recommended; Python 3.9 is supported. No Docker, network access or API keys are needed.

```bash
cd backend
python3.12 -m venv .venv && . .venv/bin/activate
python -m pip install --upgrade pip setuptools
pip install -c requirements.lock -e ".[dev,api,ingest]"     # Python 3.9: -c constraints-py39.txt
export LLM_PROVIDER=template EMBEDDINGS_PROVIDER=none SMARTAGRI_OFFLINE=1
ruff check src tests
pytest -q
python -m smartagri.evalkit guard --set dev > /dev/null
python ../examples/advise_one_parcel.py
```

These are the checks CI runs (`.github/workflows/ci.yml`). A pull request should pass all of them.

## Rules for changes

1. **Numbers come from code.** Agronomic quantities (ET0, Kc, ETc, depths, doses) are computed by the tools in
   `backend/src/smartagri/core/tools/` and covered by tests. A language model may phrase an answer but never
   computes or invents a number ([ADR 0002](docs/adr/0002-numbers-from-code.md)).
2. **The core never branches on a variant name.** Behaviour is switched by the flags in
   `backend/config/variants.yaml`, so that each rung of the ablation ladder stays comparable.
3. **No network or keys in tests.** Tests run with `SMARTAGRI_OFFLINE=1`; provider calls are answered by fakes or
   by the external cache ([ADR 0003](docs/adr/0003-offline-first-no-keys.md)).
4. **Locked files.** `backend/config/`, `backend/corpus/`, the scenario sets, the generator prompt and
   `docs/RATER_GUIDE.md` are hashed by the protocol lock (see [docs/reproducibility.md](docs/reproducibility.md)).
   A change to any of them changes the protocol fingerprint. Open an issue before changing them, state why, and
   expect such a change to be held back once a protocol has been locked for an evaluation.
5. **Test scenarios stay out.** Held-out test scenarios are not added to the repository, the corpus or the index
   before their protocol is locked; `evalkit guard` checks this for the development set in CI.
6. **Python 3.9 compatibility** for `backend/src/` (no `match`, no `X | Y` type unions at run time) as long as 3.9 is
   in the CI matrix.
7. **Style.** `ruff` with `backend/ruff.toml`; English for code, comments, docs and commit messages.

## Pull requests

- One topic per pull request; describe what changes and how it was checked.
- Update `CHANGELOG.md` under **Unreleased** for anything a user or a reader of results would notice.
- If a change affects a documented behaviour, update the matching file in `docs/` or `README.md` in the same pull
  request.
- Commit messages follow the `type(scope): summary` form used in the history (`feat`, `fix`, `docs`, `ci`, `chore`).

## Licence of contributions

Code contributions are accepted under the MIT licence of the repository (`LICENSE`). Contributions to the corpus
must state the source and its terms; see [NOTICE](NOTICE) and `backend/corpus/manifest.yaml`.
