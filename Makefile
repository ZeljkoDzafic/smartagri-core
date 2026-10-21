# SmartAgri core. Python 3.9+; no Docker needed.
.PHONY: venv test api eval-dev eval-guard eval-lock report

venv:
	cd backend && python3 -m venv .venv && . .venv/bin/activate && pip install -c constraints-py39.txt -e ".[dev,api]"
test:
	cd backend && . .venv/bin/activate && pytest -q
# Minimal research API and client: http://127.0.0.1:8100
api:
	cd backend && . .venv/bin/activate && python -m smartagri.research_api
# Development scenarios under every variant, then the report tables.
eval-dev:
	cd backend && . .venv/bin/activate && python -m smartagri.evalkit run --set dev && python -m smartagri.evalkit report
# Leakage guard: n-gram overlap between test scenario texts and the corpus (needs the test set, published after the lock).
eval-guard:
	cd backend && . .venv/bin/activate && python -m smartagri.evalkit guard --set test
# Protocol lock: sha256 of scenarios, corpus, config, prompts and the rater guide.
eval-lock:
	cd backend && . .venv/bin/activate && python -m smartagri.evalkit lock --set test $(if $(SNAPSHOT),--cache-snapshot $(SNAPSHOT))
report:
	cd backend && . .venv/bin/activate && python -m smartagri.evalkit report
