from datetime import date

from smartagri.core.grounding import unsupported_numbers
from smartagri.core.tools import (crop_evapotranspiration, estimate_bbch, gross_irrigation, kc_for_bbch,
                                  ndvi_summary, net_irrigation_need)
from smartagri.core.types import NdviObservation


def test_kc_lookup_and_etc():
    assert kc_for_bbch(61) == 1.20 and kc_for_bbch(5) == 0.30 and kc_for_bbch(None) is None
    assert crop_evapotranspiration(61, 30.0).output == {"kc": 1.20, "etc_mm": 36.0}
    assert crop_evapotranspiration(None, 30.0).output is None


def test_gross_irrigation_matches_the_worked_example():
    """Worked example: 20 mm net at 80 % efficiency is 25 mm gross, 250 m3 per hectare."""
    assert gross_irrigation(20.0, 0.80).output == {"gross_mm": 25.0, "m3_per_ha": 250.0}
    assert gross_irrigation(20.0, None).output is None
    assert gross_irrigation(20.0, 1.4).output is None


def test_water_balance_refuses_without_soil_water():
    r = net_irrigation_need(None, 160, 1.0, 0.0)
    assert r.output is None and "soil_water_status" in r.reason
    out = net_irrigation_need("dry", 160, 1.0, 0.0).output
    assert out["net_total_mm"] == 96.0 and out["applications"] == 2 and out["net_mm"] == 48.0
    out = net_irrigation_need("wet", 160, 1.0, 40.0).output
    assert out["net_total_mm"] == 0.0 and out["applications"] == 0


def test_phenology_estimate_is_monotone():
    values = [estimate_bbch(gdd_since_sowing=g).output["bbch"] for g in (0, 100, 300, 500, 700, 900, 1200, 1600)]
    assert values == sorted(values)
    assert estimate_bbch(None, 78).output["method"] == "days"
    assert estimate_bbch(None, None).output is None


def test_ndvi_summary_trend_and_contrast():
    series = [NdviObservation("2026-07-01", 0.80, 0.70, 0.86, 0.9), NdviObservation("2026-07-06", 0.74, 0.55, 0.85, 0.9),
              NdviObservation("2026-07-11", 0.70, 0.45, 0.84, 0.3)]
    out = ndvi_summary(series, date(2026, 7, 12)).output
    assert out["latest_date"] == "2026-07-11" and out["age_days"] == 1
    assert out["spatial_contrast"] == 0.39
    assert out["trend_14d"] == -0.06 and out["trend_count"] == 2   # the cloudy scene is not used for the trend


def test_numbers_must_come_from_a_tool():
    tool = gross_irrigation(20.0, 0.80)
    assert unsupported_numbers("Planirati 25 mm, odnosno 250 m3 po hektaru.", [tool]) == []
    assert unsupported_numbers("Planirati 40 mm vode.", [tool]) == [40.0]


def test_support_check_is_lexical_and_explainable():
    from smartagri.core.grounding import split_sentences, support_check
    src = ["Kukuruz je najosetljiviji na nedostatak vode u periodu metličenja i svilanja."]
    ok, bad, short = support_check(
        ["Kukuruz je u periodu svilanja najosetljiviji na nedostatak vode.",
         "Fungicid treba primeniti odmah zbog pegavosti lista.", "Da."], src)
    assert ok["supported"] and ok["source"] == 0
    assert not bad["supported"] and short["supported"]
    assert split_sentences("Prva rečenica. Druga? Treća!") == ["Prva rečenica.", "Druga?", "Treća!"]


def test_sentence_split_keeps_abbreviations():
    from smartagri.core.grounding import split_sentences
    assert split_sentences("Unesite azot, npr. međuredno. Ne računajte na kišu.") == \
        ["Unesite azot, npr. međuredno.", "Ne računajte na kišu."]
    assert split_sentences("Prinos 9,5 t/ha. Dalje.") == ["Prinos 9,5 t/ha.", "Dalje."]


def test_product_names_map_to_the_nitrogen_catalogue():
    from smartagri.core.quality import product_key
    assert product_key("NPK 15-15-15") == "npk_15_15_15" and product_key("UREA") == "urea" and product_key(None) == ""


def test_sentence_split_keeps_dates():
    from smartagri.core.grounding import split_sentences
    assert split_sentences("Analiza je od 20. 9. 2025. godine. Uzmite je kao orijentaciju.") == \
        ["Analiza je od 20. 9. 2025. godine.", "Uzmite je kao orijentaciju."]
