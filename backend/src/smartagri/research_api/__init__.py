"""Minimal research API and client of the research prototype. RESEARCH-PUBLIC.

It exposes the core path only: maize parcels, the input profile (weather, Sentinel-2) with the quality layer q,
the advisory conversation through `pipeline.run.advise` under a chosen variant (V0-V5), the provenance of every run,
the LLM status and the blind rating of evaluation runs. It imports nothing from the product (accounts, regions,
scope, crop packs, activity log, sensors, ...). The experiment itself does not run through this API: evalkit calls
`pipeline.run.advise` directly, so evaluation results never depend on this module.

    pip install -e ".[api]"
    python -m smartagri.research_api            # http://127.0.0.1:8100 (local research use, no accounts)

Optional accounts for a public deployment (SMARTAGRI_ACCOUNTS=optional) live in `auth.py`, written for this module;
they do not change the evaluation, the blind rating protocol or anything the experiment reads.
"""
