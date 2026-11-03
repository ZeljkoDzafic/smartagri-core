# SmartAgri core. Python 3.9+; no Docker needed.
.PHONY: coverage-core venv test api eval-dev eval-guard eval-lock report

venv:
	cd backend && python3 -m venv .venv && . .venv/bin/activate && pip install --upgrade pip setuptools && pip install -c constraints-py39.txt -e ".[dev,api]"
test:
	cd backend && . .venv/bin/activate && pytest -q
# Minimal research API and client: http://127.0.0.1:8100
api:
	cd backend && . .venv/bin/activate && python -m smartagri.research_api
# Development scenarios under every variant in a fresh database, then the report of the dev set.
eval-dev:
	cd backend && . .venv/bin/activate && rm -f eval-dev.sqlite && SMARTAGRI_DB=eval-dev.sqlite python -m smartagri.evalkit run --set dev && SMARTAGRI_DB=eval-dev.sqlite python -m smartagri.evalkit report --set dev
# Leakage guard: n-gram overlap between test scenario texts and the corpus (needs the test set, published after the lock).
eval-guard:
	cd backend && . .venv/bin/activate && python -m smartagri.evalkit guard --set test
# Protocol lock: sha256 of scenarios, corpus, config, prompts, rater guide and analysis plan, plus code and environment.
# The test set needs the external-cache snapshot: make eval-lock SNAPSHOT=snapshot.tar
eval-lock:
	cd backend && . .venv/bin/activate && python -m smartagri.evalkit lock --set test --cache-snapshot $(SNAPSHOT)
report:
	cd backend && . .venv/bin/activate && python -m smartagri.evalkit report --set $(or $(SET),dev)
# Branch coverage of the decision core (core/); fails below the threshold. CI runs the same two commands.
coverage-core:
	cd backend && . .venv/bin/activate && pip install -q "coverage>=7" && coverage run --branch --source=src/smartagri/core -m pytest -q && coverage report --include='src/smartagri/core/*' --fail-under=90
