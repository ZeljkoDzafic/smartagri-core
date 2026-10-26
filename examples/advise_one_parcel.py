"""Advise on one parcel, offline, with the deterministic template generator.

The script uses the same Python entry point as the web app (`smartagri.research_api.service.ResearchService`):

1. create a maize parcel (a small polygon) with a fixed decision date;
2. build its data profile from fixture data: a synthetic Open-Meteo daily series and a recorded Sentinel-2
   Statistical API response (backend/tests/fixtures/cdse_statistics.json) are placed in the provider cache, and
   offline mode makes the providers read only that cache, so nothing is requested from the network;
3. ask one question under variant V5 (in the web app's answer language, English unless SMARTAGRI_LOCALE is set) and print the act, the policy reason, the inputs with their reliability,
   the sources with their applicability and the provenance hashes.

Run from the repository root after the editable install (see README.md):

    LLM_PROVIDER=template EMBEDDINGS_PROVIDER=none SMARTAGRI_OFFLINE=1 python examples/advise_one_parcel.py

The weather numbers below are invented for the example; they are not observations.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# Offline, template generator, BM25 only: no network, no keys, no model downloads.
os.environ["SMARTAGRI_OFFLINE"] = "1"
os.environ.setdefault("LLM_PROVIDER", "template")
os.environ.setdefault("EMBEDDINGS_PROVIDER", "none")
# The satellite adapter is active only when credentials are set. These placeholders are never sent anywhere:
# in offline mode the adapter answers from the cache seeded below, or reports the input as missing.
os.environ.setdefault("CDSE_CLIENT_ID", "offline-example")
os.environ.setdefault("CDSE_CLIENT_SECRET", "offline-example")

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if (BACKEND / "src").is_dir():
    sys.path.insert(0, str(BACKEND / "src"))      # also works without the editable install

from smartagri import i18n  # noqa: E402
from smartagri.providers import satellite, weather  # noqa: E402
from smartagri.providers.base import request_hash  # noqa: E402
from smartagri.research_api import locale as answer_locale  # noqa: E402
from smartagri.research_api.service import ResearchService  # noqa: E402
from smartagri.store import SqliteStore  # noqa: E402

AS_OF = datetime.fromisoformat("2026-07-12T06:00:00+02:00")     # decision moment (in the past: archive endpoint)
PARCEL = {
    "name": "Example parcel",
    "geometry": {"type": "Polygon", "coordinates": [[[19.800, 45.300], [19.802, 45.300], [19.802, 45.3015],
                                                     [19.800, 45.3015], [19.800, 45.300]]]},
    "sowing_date": "2026-04-20",
    "irrigation_available": "yes",
    "irrigation_system_type": "sprinkler",
    "soil_texture": "loam",
    "bbch": 63,
    "pinned_as_of": AS_OF.isoformat(),
}
QUESTION = "Should I irrigate the maize this week?"


def synthetic_open_meteo(as_of: date) -> dict:
    """A daily series in the Open-Meteo response shape: 92 past days and 7 forecast days (invented values)."""
    days = [as_of - timedelta(days=weather.PAST_DAYS) + timedelta(days=i)
            for i in range(weather.PAST_DAYS + weather.FORECAST_DAYS)]
    n = len(days)
    return {"daily": {
        "time": [d.isoformat() for d in days],
        "temperature_2m_max": [31.0] * n,
        "temperature_2m_min": [17.0] * n,
        "precipitation_sum": [0.0 if i % 9 else 6.0 for i in range(n)],
        "wind_speed_10m_max": [3.0] * n,
        "et0_fao_evapotranspiration": [5.2] * n,
    }}


def seed_cache(store, parcel: dict) -> None:
    """Put the fixture responses where the providers look first; offline mode never looks further."""
    lat, lon = parcel["centroid"]["lat"], parcel["centroid"]["lon"]
    req = weather.build_request(lat, lon, AS_OF)
    store.cache_put(request_hash("open-meteo", req["key"]), "open-meteo", req["key"], synthetic_open_meteo(AS_OF.date()))
    fixture = BACKEND / "tests" / "fixtures" / "cdse_statistics.json"
    if fixture.is_file():
        sreq = satellite.build_request(parcel["geometry"], AS_OF)
        store.cache_put(request_hash("cdse-statistical", sreq), "cdse-statistical", sreq,
                        json.loads(fixture.read_text(encoding="utf-8")))


def main() -> int:
    svc = ResearchService(SqliteStore(":memory:"))
    parcel = svc.create_parcel(PARCEL)
    seed_cache(svc.store, parcel)
    # The answer language of a web request (English unless SMARTAGRI_LOCALE says otherwise). Outside a request the
    # core's default locale applies, which is the one evaluation runs use.
    answer_locale.ensure_english_catalogue()
    with i18n.use(answer_locale.configured()):
        profile = svc.refresh_profile(parcel["id"])
        run = svc.chat(parcel["id"], {"text": QUESTION, "variant": "V5"})

    answer, decisions, prov = run["answer"], run["decisions"], run["provenance"]
    policy = decisions["policy"]
    print("parcel      %s, %.2f ha, region %s" % (parcel["name"], parcel["area_ha"], parcel["region_class"]))
    print("profile     weather: %s, satellite: %s" % (profile["weather"]["status"], profile["satellite"]["status"]))
    print("question    %s" % QUESTION)
    print("advice type %s" % run["advice_type"])
    print("act         %s (reason: %s, quantity allowed: %s)" % (policy["act"], policy["reason_code"],
                                                                  policy["allow_quantity"]))
    print("summary     %s" % answer["summary"])
    if answer.get("referral"):
        print("referral    %s" % answer["referral"])
    if answer.get("next_question"):
        print("next q.     %s" % answer["next_question"]["text"])
    print("\ninputs (q)")
    for row in profile["quality"]:
        print("  %-26s %-12s %-10s %s" % (row["input"], row["origin"], row["reliability"], row["value_text"]))
    print("\nsources (pi)")
    for src in answer["sources"]:
        print("  %-28s %s" % (src["passage_id"], src["applicability"]))
    print("\nprovenance")
    print("  as_of        %s" % prov["as_of"])
    print("  corpus_hash  %s" % prov["corpus_hash"])
    print("  model        %s" % prov["model"])
    for name, digest in sorted(prov["config_hashes"].items()):
        print("  config %-12s %s" % (name, digest[:16]))
    print("  scene_dates  %s" % (", ".join(prov["scene_dates"]) or "-"))
    return 0 if policy["act"] in ("recommend", "conditional", "ask", "abstain") else 1


if __name__ == "__main__":
    sys.exit(main())
