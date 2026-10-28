"""English catalogue of user-facing strings (spec 017).

Mirrors every table and formatting function of `labels` (same names, same keys) so that code reading them
through `i18n.L()` produces English with identical numbers and logic. `MESSAGES` maps literal sentences of the
default catalogue (keys exactly as written in the code, %-formats included) to English; `i18n.T()` and
`i18n.translate_message()` read it. Completeness is tested in tests/test_locales.py (every key of the default
tables has an English entry, no English string contains local diacritics).

EUDR wording follows the English text of Regulation (EU) 2023/1115 where it exists ("deforestation-free",
"due diligence statement", "relevant commodities", "plot of land", "country of production", Annex I names).
"""
from __future__ import annotations

from typing import Any, Dict, List

from .core.types import to_date

ADVICE_TYPES = {
    "irrigation_timing": "Irrigation: timing",
    "irrigation_amount": "Irrigation: amount",
    "fertilization_plan": "Top-dressing: plan and rate",
    "fertilization_timing": "Top-dressing: timing",
    "field_ops_window": "Weather window for field work",
    "scouting": "Crop condition and field scouting",
    "out_of_scope": "Outside the system's scope",
}
USER_ADVICE_TYPES = ["irrigation_timing", "irrigation_amount", "fertilization_plan", "field_ops_window", "scouting"]

ACTS = {"recommend": "Recommendation", "conditional": "Conditional recommendation", "ask": "Follow-up question",
        "abstain": "No recommendation"}
RELIABILITY = {"high": "high", "medium": "medium", "low": "low", "missing": "missing", "ungraded": "not graded"}
ORIGIN = {"measured": "measured", "user_reported": "reported by the user", "modeled": "model value",
          "derived": "estimate", "unknown": "unknown"}
APPLICABILITY = {"applicable": "applicable", "conditional": "conditionally applicable", "not_applicable": "not applicable"}

INPUTS = {
    "phenophase": "Growth stage (BBCH)", "sowing_date": "Sowing date", "ndvi_latest": "NDVI, latest observation",
    "ndvi_spatial_contrast": "NDVI, differences within the parcel", "ndvi_trend": "NDVI, change over 14 days",
    "precip_past_7d": "Rainfall, past 7 days", "et0_past_7d": "Reference evapotranspiration, past 7 days",
    "precip_forecast_3d": "Rainfall forecast, 3 days", "precip_forecast_7d": "Rainfall forecast, 7 days",
    "temp_forecast": "Temperature forecast, 7 days", "wind_forecast": "Wind forecast, 7 days",
    "soil_water_status": "Soil water status", "soil_moisture_sensor": "Soil moisture sensor",
    "soil_awc": "Soil water-holding capacity", "soil_analysis": "Soil analysis",
    "irrigation_available": "Irrigation possible", "irrigation_efficiency": "Irrigation system efficiency",
    "previous_fertilization": "Fertiliser applied so far", "yield_target": "Target yield", "operation": "Planned work",
    "advice_type": "Type of advice",
    "irrigation_capacity": "Irrigation system capacity", "previous_crop": "Previous crop",
    "manure": "Manure (last 12 months)", "hybrid_fao": "Hybrid maturity group (FAO)",
    "plant_density": "Plant density", "field_observation": "Field observations (last 7 days)",
}

PREVIOUS_CROPS = [{"value": "maize", "label": "Maize"}, {"value": "wheat", "label": "Wheat"},
                  {"value": "barley", "label": "Barley"}, {"value": "soybean", "label": "Soybean"},
                  {"value": "sunflower", "label": "Sunflower"}, {"value": "sugar_beet", "label": "Sugar beet"},
                  {"value": "alfalfa", "label": "Alfalfa"}, {"value": "clover", "label": "Clover"},
                  {"value": "pea", "label": "Pea"}, {"value": "bean", "label": "Bean"},
                  {"value": "other", "label": "Other"}]
OBSERVATION_KINDS = [{"value": "wilting", "label": "Wilting"}, {"value": "yellowing", "label": "Yellowing leaves"},
                     {"value": "hail", "label": "Hail damage"}, {"value": "lodging", "label": "Lodging"},
                     {"value": "waterlogging", "label": "Waterlogging"}, {"value": "pests", "label": "Pests"},
                     {"value": "disease", "label": "Disease symptoms"}, {"value": "other", "label": "Other"}]
FERTILIZER_PRODUCTS = [{"value": "urea", "label": "Urea"}, {"value": "kan", "label": "CAN (KAN)"}, {"value": "an", "label": "AN"},
                       {"value": "uan", "label": "UAN"}, {"value": "npk_15_15_15", "label": "NPK 15-15-15"},
                       {"value": "npk_20_10_10", "label": "NPK 20-10-10"}, {"value": "map", "label": "MAP"},
                       {"value": "dap", "label": "DAP"}]

OPTIONS: Dict[str, List[Dict[str, Any]]] = {
    "soil_water_status": [{"value": "dry", "label": "Dry"}, {"value": "moist", "label": "Moderately moist"},
                          {"value": "wet", "label": "Wet"}],
    "irrigation_available": [{"value": "yes", "label": "Yes"}, {"value": "no", "label": "No"}],
    "irrigation_efficiency": [{"value": "sprinkler", "label": "Sprinkler"}, {"value": "drip", "label": "Drip"},
                              {"value": "furrow", "label": "Furrow"}],
    "soil_awc": [{"value": "sandy_loam", "label": "Light, sandy"}, {"value": "loam", "label": "Medium, loamy"},
                 {"value": "clay", "label": "Heavy, clayey"}],
    "previous_fertilization": [{"value": "none", "label": "Nothing so far"}, {"value": "partial", "label": "Part of the planned nitrogen"},
                               {"value": "full", "label": "All of the planned nitrogen"}],
    "operation": [{"value": "spraying", "label": "Spraying"}, {"value": "fertilizing", "label": "Top-dressing"},
                  {"value": "cultivation", "label": "Inter-row cultivation"}, {"value": "sowing", "label": "Sowing"}],
    "phenophase": [{"value": 14, "label": "4 leaves"}, {"value": 16, "label": "6 leaves"}, {"value": 18, "label": "8 leaves"},
                   {"value": 34, "label": "Stem elongation"}, {"value": 55, "label": "Tasselling"},
                   {"value": 65, "label": "Silking"}, {"value": 75, "label": "Milk stage"},
                   {"value": 85, "label": "Dough stage"}],
    "advice_type": [{"value": k, "label": ADVICE_TYPES[k]} for k in USER_ADVICE_TYPES],
    "previous_crop": PREVIOUS_CROPS,
    "field_observation": OBSERVATION_KINDS,
    "observation_kind": OBSERVATION_KINDS,
    "fertilizer_product": FERTILIZER_PRODUCTS,
}
DECLINE_OPTION = {"value": "__unknown__", "label": "I don't know"}

VALUE_WORDS = {"dry": "dry", "moist": "moderately moist", "wet": "wet", "yes": "yes", "no": "no",
               "spraying": "spraying", "fertilizing": "top-dressing", "cultivation": "inter-row cultivation", "sowing": "sowing",
               "none": "nothing so far", "partial": "part of the planned nitrogen", "full": "all of the planned nitrogen"}

TEXTURES = {"sand": "sandy", "sandy_loam": "sandy loam", "loam": "loam", "clay_loam": "clay loam", "clay": "clayey"}

CORE_ACTIONS = {
    "full_refill": ("Irrigate with a full application.", "Within the next two days, in the morning or evening."),
    "partial_refill": ("Irrigate with a reduced application.", "Within the next three days; check soil moisture again before that."),
    "irrigate_within_2d": ("Irrigate.", "Within the next two days, in the morning or evening."),
    "recheck_in_3d": ("Do not irrigate now.", "Check soil moisture and the forecast again in three days."),
    "not_needed": ("Irrigation is not needed at the moment.", "Keep an eye on the forecast and the soil."),
    "wait_for_rain": ("Wait for the forecast rain.", "Reassess after the rain, based on the amount that actually fell."),
    "late_season": ("Irrigation is no longer recommended.", "The crop is ripening; water added now does not add to the yield."),
    "not_possible": ("Irrigation is not possible on this parcel.", "Keep an eye on the rain forecast and the crop."),
    "topdress_now": ("Top-dress with nitrogen.", "Now, between the four- and eight-leaf stage, before the forecast rain or with incorporation into the soil."),
    "wait_for_window": ("Wait with top-dressing.", "Until the four-leaf stage."),
    "late_window_caution": ("Top-dressing is still possible, but with care.", "As soon as possible; later application risks crop damage and poorer uptake."),
    "too_late": ("Nitrogen top-dressing is no longer recommended.", "The crop is past the stage at which top-dressing pays off."),
    "no_additional_n": ("No additional nitrogen is needed.", "The planned amount of nitrogen has already been applied."),
    "window_open": ("The planned work can be done.", "On days without rain and strong wind in the forecast."),
    "window_open_dry": ("The planned work can be done.", "No rain is forecast; incorporate the fertiliser into the soil if possible."),
    "window_open_before_rain": ("Do the planned work before the forecast rain.", "On the first dry day of the forecast."),
    "postpone": ("Postpone the planned work.", "Until the forecast shows better conditions."),
    "priority_scouting": ("Walk the parcel, weaker parts first.", "Within the next two to three days."),
    "routine_scouting": ("A routine visit is enough.", "On the usual schedule."),
    "no_satellite_view": ("Walk the parcel on a routine visit.", "There is no usable satellite image to guide the visit."),
    "priority_scouting_event": ("Walk the parcel now, damaged parts first.",
                                "Damage (hail, lodging or waterlogging) was reported in the last seven days."),
}

SCOUTING_CHECKLIST = ["soil moisture and compaction", "evenness of emergence and stand", "leaf colour and damage",
                      "signs of waterlogging or drought", "presence of weeds, pests or disease symptoms"]
NO_DIAGNOSIS = "The cause of the vegetation difference cannot be determined from the satellite image; the image only shows where to look."
REFERRAL = "For this decision, contact the agricultural advisory service or a plant protection specialist."
PLANT_PROTECTION_REFERRAL = ("Pests or disease symptoms were reported. Contact the plant protection service or an "
                             "adviser; the system does not prescribe plant protection products or doses.")
DISCLAIMER = "Decision support, not a binding regulation."

CHECKS = {"crop": "crop", "advice_type": "type of advice", "phenophase": "growth stage", "region": "region",
          "agroecology": "production conditions (irrigation)", "date": "age of the source",
          "weather_consistency": "agreement with the forecast", "soil": "soil type"}
TOOLS = {"etc": "Crop evapotranspiration", "net_irrigation_need": "Net water requirement",
         "gross_irrigation": "Gross irrigation application", "estimate_bbch": "Growth stage estimate",
         "application_time": "Duration of one irrigation"}
RUBRIC = {
    "criteria": [
        {"key": "r1", "label": "Applicability of the proposed action to the crop, stage and region",
         "levels": ["0: not applicable or wrong", "1: partly applicable", "2: applicable"]},
        {"key": "r2", "label": "Account taken of the parcel, weather and crop conditions",
         "levels": ["0: conditions ignored", "1: partly taken into account", "2: taken into account"]},
        {"key": "r3", "label": "Grounding of the key claims in sources and calculations",
         "levels": ["0: ungrounded", "1: partly grounded", "2: grounded"]},
        {"key": "r4", "label": "Concreteness of the next step and handling of missing data",
         "levels": ["0: unclear or made up", "1: partly concrete", "2: concrete and correct"]},
        {"key": "r5", "label": "Correctness of the decision (recommendation, conditional recommendation, question, abstention) and communication of data reliability",
         "levels": ["0: wrong decision", "1: acceptable, with remarks", "2: correct and clearly justified"]},
    ],
    "critical": [
        {"key": "K1", "label": "Quantity or dose without the necessary data"},
        {"key": "K2", "label": "Action contrary to a known parcel or forecast condition"},
        {"key": "K3", "label": "Claim about a cause derived from a vegetation index alone"},
        {"key": "K4", "label": "Premature recommendation: a key datum was missing or unreliable"},
        {"key": "K5", "label": "Unjustified abstention or needless question"},
    ],
}

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def num(value: Any, digits: int = 1) -> str:
    """Same rounding as labels.num; decimal point instead of decimal comma."""
    if value is None:
        return "no data"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int) or float(value).is_integer() and digits <= 1:
        return str(int(round(float(value))))
    return "%.*f" % (digits, float(value))


def option_label(group: str, value: Any) -> str:
    return next((o["label"] for o in OPTIONS.get(group, []) if o["value"] == value), str(value))


def fmt_date(value: Any) -> str:
    d = to_date(value)
    return "no data" if d is None else "%d %s %d" % (d.day, MONTHS[d.month - 1], d.year)


def value_text(name: str, value: Any) -> str:
    """Same branches as labels.value_text."""
    if value is None:
        return "no data"
    if name == "phenophase":
        return "BBCH %s" % value
    if name == "sowing_date":
        return fmt_date(value)
    if name in ("ndvi_latest", "ndvi_spatial_contrast", "ndvi_trend"):
        return num(value, 2)
    if name in ("precip_past_7d", "et0_past_7d", "precip_forecast_3d", "precip_forecast_7d"):
        return "%s mm" % num(value)
    if name == "temp_forecast":
        return "from %s to %s °C" % (num(value.get("tmin")), num(value.get("tmax")))
    if name == "wind_forecast":
        return "up to %s m/s" % num(value)
    if name == "soil_moisture_sensor":
        return "%s %%" % num(float(value) * 100)
    if name == "soil_awc":
        return "%s mm/m" % num(value)
    if name == "irrigation_efficiency":
        return "%s %%" % num(float(value) * 100)
    if name == "yield_target":
        return "%s t/ha" % num(value)
    if name == "soil_analysis":
        if not isinstance(value, dict):
            return "available"
        parts = []
        for key, fmt in (("ph", "pH %s"), ("humus_pct", "humus %s %%"), ("p2o5_mg100g", "P2O5 %s mg/100 g"),
                         ("k2o_mg100g", "K2O %s mg/100 g")):
            if value.get(key) is not None:
                parts.append(fmt % num(value[key]))
        if value.get("date"):
            parts.append("from %s" % fmt_date(value["date"]))
        return ", ".join(parts) or "available"
    if name == "irrigation_capacity":
        return "%s mm/day" % num(value)
    if name == "previous_crop":
        return option_label("previous_crop", value)
    if name == "manure":
        if isinstance(value, dict):
            text = "%s t/ha" % num(value.get("t_ha"))
            return text + (", %s" % fmt_date(value["date"]) if value.get("date") else "")
        return "%s t/ha" % num(value)
    if name == "hybrid_fao":
        return "FAO %s" % num(value)
    if name == "plant_density":
        return "%d plants/ha" % int(round(float(value)))
    if name == "field_observation":
        kinds = value if isinstance(value, (list, tuple)) else [value]
        return ", ".join(option_label("observation_kind", k).lower() for k in kinds) or "none"
    if name == "previous_fertilization":
        if isinstance(value, str):
            return VALUE_WORDS.get(value, value)
        if not value:
            return "nothing so far"
        total = sum(float(v.get("n_kg_ha", 0) or 0) for v in value)
        return "%s kg N/ha" % num(total)
    return VALUE_WORDS.get(str(value), str(value))


GENERIC_ADVICE = {
    "irrigation_timing": "The timing of irrigation depends on the soil water status and the rain forecast.",
    "irrigation_amount": "The amount of water depends on the soil water status, the soil properties and the system efficiency.",
    "fertilization_plan": "The top-dressing plan depends on the growth stage, the fertiliser applied so far and a soil analysis or the target yield.",
    "fertilization_timing": "The timing of top-dressing depends on the growth stage and the rain forecast.",
    "field_ops_window": "A suitable time depends on the kind of work and the forecast of rain, wind and temperature.",
    "scouting": "Scouting is guided by the vegetation differences on the latest usable image.",
}
DOSE_NOTE = ("The system does not yet have a validated nitrogen rate calculation. Set the rate with an adviser based on a soil "
             "analysis, the target yield and the nitrogen already applied.")
QUANTITY_NOTE = ("The parameters of the irrigation amount calculation have not yet been reviewed by an expert. The calculation "
                 "is shown for orientation and is not given as a recommended amount.")
DOSE_BAND = {"low": "a lower rate within the regional recommendation", "medium": "a medium rate within the regional recommendation",
             "high": "a higher rate within the regional recommendation"}
ABSTAIN_REASONS = {
    "out_of_scope": "The question is outside the system's scope: the system does not prescribe plant protection products or doses.",
    "corpus_insufficient": "The knowledge base has no source that applies to this parcel and this question.",
    "outside_validated_scope": "The system gives no recommendation for this parcel: it is outside the validated area.",
}

FRESHNESS = {"fresh": "fresh", "aging": "older", "stale": "outdated", "missing": "missing"}
FRESHNESS_BY_RELIABILITY = {"high": "fresh", "medium": "aging", "low": "stale", "missing": "missing"}
FRESHNESS_PARTS = {"ndvi_latest": "NDVI", "precip_forecast_3d": "Forecast", "phenophase": "Stage",
                   "soil_water_status": "Soil water"}
OPERATIONS_WINDOW = {"spraying": "Spraying", "fertilizing": "Top-dressing", "cultivation": "Inter-row cultivation",
                     "sowing": "Sowing"}
OPERATION_STATUS = {"ok": "go", "caution": "caution", "no": "no"}


def days_text(n: Any) -> str:
    k = int(round(float(n)))
    return "%d %s" % (k, "day" if k == 1 else "days")


def lower_first(text: str) -> str:
    if len(text) > 1 and text[0].isupper() and text[1].islower():
        return text[0].lower() + text[1:]
    return text


def basis_phrase(name: str, value: Any) -> str:
    """Same branches as labels.basis_phrase."""
    if name == "phenophase":
        return "stage BBCH %s" % value
    if name == "precip_forecast_3d":
        return "forecast %s mm over 3 days" % num(value)
    if name == "precip_forecast_7d":
        return "forecast %s mm over 7 days" % num(value)
    if name == "et0_past_7d":
        return "ET0 %s mm over 7 days" % num(value)
    if name == "temp_forecast":
        return "temperature %s" % value_text(name, value)
    if name == "wind_forecast":
        return "wind %s" % value_text(name, value)
    if name == "soil_water_status":
        return "soil %s" % VALUE_WORDS.get(str(value), str(value))
    if name == "irrigation_available":
        return "irrigation possible: %s" % VALUE_WORDS.get(str(value), str(value))
    if name == "operation":
        return "work: %s" % VALUE_WORDS.get(str(value), str(value))
    if name == "ndvi_latest":
        return "NDVI %s" % num(value, 2)
    return "%s: %s" % (lower_first(INPUTS.get(name, name)), value_text(name, value))


# ---------------------------------------------------------------- spec 013: activity log and traceability
ACTIVITY_KINDS = [{"value": "sowing", "label": "Sowing"}, {"value": "fertilizing", "label": "Fertilising"},
                  {"value": "spraying", "label": "Spraying (plant protection)"},
                  {"value": "irrigation", "label": "Irrigation"}, {"value": "cultivation", "label": "Tillage"},
                  {"value": "harvest", "label": "Harvest"}, {"value": "scouting", "label": "Scouting and observation"},
                  {"value": "other", "label": "Other"}]
ACTIVITY_KIND = {o["value"]: o["label"] for o in ACTIVITY_KINDS}
ACTIVITY_STATUSES = [{"value": "done", "label": "Done"}, {"value": "planned", "label": "Planned"}]
ACTIVITY_CROPS = PREVIOUS_CROPS
SPRAY_DOSE_UNITS = [{"value": "l_ha", "label": "l/ha"}, {"value": "ml_ha", "label": "ml/ha"},
                    {"value": "kg_ha", "label": "kg/ha"}, {"value": "g_ha", "label": "g/ha"}]
IRRIGATION_METHODS = [{"value": "sprinkler", "label": "Sprinkler"}, {"value": "drip", "label": "Drip"},
                      {"value": "furrow", "label": "Furrow"}, {"value": "other", "label": "Other"}]
SEVERITIES = [{"value": "low", "label": "Slight"}, {"value": "medium", "label": "Moderate"}, {"value": "high", "label": "Severe"}]
ACTIVITY_ORIGIN = "activity log"
ACTIVITY_EVENT_ACTIONS = {"create": "created", "update": "changed", "delete": "deleted"}
ACTIVITY_CSV_HEADERS = ["Date", "End date", "Parcel", "Kind of work", "Status", "Details", "Performed by",
                        "Entered by", "Note", "Warnings", "Demo", "Record ID"]
ACTIVITY_WARNINGS = {
    "phi": "Harvest {harvest} is {days} after spraying with “{product}” ({spray}), and the recorded pre-harvest interval is {phi}.",
    "wind_forecast": ("For the spraying day ({date}) the stored weather data ({source}) show wind up to {wind} m/s, "
                      "above the {limit} m/s limit for spraying."),
    "wind_reported": "The wind recorded during spraying ({wind} m/s) is above the {limit} m/s limit for spraying.",
    "future_date": "The date of the work marked as done ({date}) is after today ({today}); check the date or mark the work as planned.",
    "crop_mismatch": "The sown crop ({crop}) differs from the parcel's crop ({parcel_crop}).",
}
# Field labels and units of activities.FIELDS (same keys), used by activities.fields_for().
ACTIVITY_FIELD_LABELS = {
    "sowing": {"crop": "Crop", "hybrid": "Hybrid or variety", "fao": "Maturity group (FAO)", "seed_rate_kg_ha": "Seed rate",
               "density_plants_ha": "Sowing density"},
    "fertilizing": {"product": "Fertiliser", "amount_kg_ha": "Amount", "n_kg_ha": "Nitrogen (if known)"},
    "spraying": {"product": "Product (trade name)", "active_substance": "Active substance", "dose": "Amount applied",
                 "dose_unit": "Unit of amount", "target": "Target (pest, disease, weed)", "phi_days": "Pre-harvest interval",
                 "wind_ms": "Wind during spraying", "weather_note": "Weather during spraying"},
    "irrigation": {"mm": "Amount of water", "method": "Method"},
    "cultivation": {"operation": "Kind of tillage", "depth_cm": "Depth"},
    "harvest": {"yield_t_ha": "Yield", "moisture_pct": "Grain moisture", "quantity_t": "Total quantity", "lot_id": "Lot ID"},
    "scouting": {"observation": "Observation", "severity": "Severity"},
    "other": {"text": "Description"},
}
UNITS = {"biljaka/ha": "plants/ha", "dana": "days"}

# ---------------------------------------------------------------- spec 014: EUDR documentation
EUDR_DISCLAIMER = ("This document helps to prepare the data for a due diligence statement under Regulation (EU) 2023/1115; "
                   "it is neither legal advice nor a submitted statement. The operator is responsible for the accuracy of the "
                   "data and for submitting the statement to the EU information system (TRACES).")
EUDR_CUTOFF_STATEMENT = ("I declare that the land of this plot has not been subject to deforestation (conversion of forest to "
                         "agricultural use) after 31 December 2020 and that the commodity has been produced in accordance with "
                         "the relevant legislation of the country of production.")
EUDR_COMMODITIES = [{"value": "soya", "label": "Soya"}, {"value": "cattle", "label": "Cattle"},
                    {"value": "cocoa", "label": "Cocoa"}, {"value": "coffee", "label": "Coffee"},
                    {"value": "oil_palm", "label": "Oil palm"}, {"value": "rubber", "label": "Rubber"},
                    {"value": "wood", "label": "Wood"}]
EUDR_COMMODITY = {o["value"]: o["label"] for o in EUDR_COMMODITIES}
EUDR_CHECKS = {
    "geolocation": "Geolocation (WGS84, 6 decimals; a point below 4 ha, a polygon from 4 ha)",
    "area": "Area of the plot",
    "country": "Country of production (ISO 3166-1 alpha-2)",
    "commodity": "Relevant commodity in the scope of the EUDR",
    "production_start": "Start of the production period (sowing)",
    "production_end": "End of the production period (harvest)",
    "cutoff_attestation": "Statement on land use after 31 December 2020",
    "deforestation_check": "Deforestation check against an external data set (not automated)",
    "producer_name": "Name of the producer",
}
EUDR_PERIOD_STATUS = {"complete": "complete", "planned_harvest": "harvest planned", "in_progress": "in progress",
                      "unknown": "unknown"}
EUDR_REFERENCE_TITLES = {
    "regulation": "Regulation (EU) 2023/1115 on deforestation-free products",
    "amendment": "Regulation (EU) 2025/2650 (amendments and postponed application)",
    "geojson_guidance": "EUDR information system: GeoJSON file description",
}
STATEMENT_STATUS = {"draft": "draft"}
OPTIONS.update({"activity_kind": ACTIVITY_KINDS, "activity_status": ACTIVITY_STATUSES, "spray_dose_unit": SPRAY_DOSE_UNITS,
                "irrigation_method": IRRIGATION_METHODS, "severity": SEVERITIES, "eudr_commodity": EUDR_COMMODITIES})

# ---------------------------------------------------------------- spec 011: roles
ROLE_LABELS = {"owner": "owner", "agronomist": "agronomist", "worker": "worker", "inspector": "inspector"}

# ---------------------------------------------------------------- questions of config/asking.yaml (question_sr, how_to_obtain_sr)
QUESTIONS = {
    "soil_water_status": ("How moist is the soil at a depth of 20–30 cm: dry, moderately moist or wet?",
                          "Dig with a spade to 30 cm in two or three places and squeeze a clod in your hand: if it crumbles, "
                          "it is dry; if it holds its shape without traces of water, it is moderately moist; if it leaves "
                          "moisture on your palm, it is wet."),
    "irrigation_available": ("Can you irrigate this parcel?", ""),
    "irrigation_efficiency": ("Which irrigation system do you use (sprinkler, drip, furrow)?",
                              "The type of system is enough; the efficiency is estimated from the type."),
    "soil_awc": ("What type of soil does the parcel have: light sandy, medium loamy or heavy clayey?",
                 "If you have a soil analysis, the texture is given in the report."),
    "phenophase": ("What stage is the maize at now: how many developed leaves does it have, or have tasselling or silking begun?",
                   "Count the fully developed leaves on a few plants, or say whether tassels and silks are visible."),
    "previous_fertilization": ("Which fertiliser and how much have you applied on this parcel so far this season?", ""),
    "yield_target": ("What grain yield do you realistically expect on this parcel (t/ha)?",
                     "The average of the last three years will do."),
    "soil_analysis": ("Do you have a soil analysis for this parcel, and from which year?",
                      "If you do not, sampling and analysis are done in a laboratory; until then the plan is given without a rate."),
    "operation": ("Which work are you planning: spraying, top-dressing, inter-row cultivation or sowing?", ""),
}

# ---------------------------------------------------------------- e-mails (spec 011)
EMAIL = {
    "hello_name": "Hello %s,",
    "hello": "Hello,",
    "verify_body": "thank you for creating an Open Crop Manager account. Confirm your e-mail address by opening the link below. "
                   "The link is valid for 48 hours.",
    "verify_ignore": "If you did not create the account, ignore this message.",
    "verify_subject": "Open Crop Manager: confirm your e-mail address",
    "verify_button": "Confirm e-mail address",
    "reset_body": "we received a request for a new password for your Open Crop Manager account. Set the new password using the link "
                  "below. The link is valid for 1 hour and can be used only once.",
    "reset_ignore": "If you did not ask for a new password, ignore this message; your old password still works.",
    "reset_subject": "Open Crop Manager: new password",
    "reset_button": "Set a new password",
    "invite_body": "%s invites you to join the organisation “%s” on Open Crop Manager, with the role: %s. "
                   "Accept the invitation using the link below. The link is valid for 7 days.",
    "invite_owner": "The owner",
    "invite_ignore": "If you are not expecting this invitation, ignore this message.",
    "invite_subject": "Open Crop Manager: invitation to the organisation %s",
    "invite_button": "Accept invitation",
    "button_fallback": "If the button does not work, open this link:",
    "footer": "Open Crop Manager · maize advisor",
}

# ---------------------------------------------------------------- English questions (spec 017): local query for retrieval
# The corpus is in the local language. An English question is mapped to its advice type (pipeline/intent_en.py) and
# retrieval searches with this canonical local question; the user's own text is kept as the shown question.
LOCAL_QUERIES = {          # no crop word: stated conditions (pipeline/run.py) are read from the user's text only
    "irrigation_timing": "Da li da navodnjavam sada?",
    "irrigation_amount": "Koliko vode da dam pri navodnjavanju?",
    "fertilization_plan": "Koliko azota da dam u prihrani?",
    "fertilization_timing": "Kada da obavim prihranu azotom?",
    "field_ops_window": "Da li mogu ovih dana da obavim radove na parceli?",
    "scouting": "Koji deo parcele da obiđem prvo?",
    "out_of_scope": "Koje sredstvo za zaštitu bilja da koristim?",
}

# ---------------------------------------------------------------- literal sentences (i18n.T, i18n.translate_message)
MESSAGES: Dict[str, str] = {
    # ---- pipeline/generate.py
    "nije zadovoljeno: ": "not met: ",
    "nije proverljivo: ": "cannot be checked: ",
    "Bruto norma %s mm po navodnjavanju, odnosno %s m³ po hektaru.": "Gross application %s mm per irrigation, i.e. %s m³ per hectare.",
    " Ukupan deficit pokriti u %d navodnjavanja.": " Cover the total deficit in %d irrigations.",
    "Ako je odgovor „%s”: %s %s": "If the answer is “%s”: %s %s",
    "Faza razvoja: BBCH %s (pouzdanost: %s).": "Growth stage: BBCH %s (reliability: %s).",
    "Faza razvoja: BBCH %s.": "Growth stage: BBCH %s.",
    "Stanje vode u zemljištu procenjeno je kao %s jer je parcela navodnjavana %s sa %s mm (procena).":
        "The soil water status was estimated as %s because the parcel was irrigated on %s with %s mm (estimate).",
    "Stanje vode u zemljištu procenjeno je kao %s prema prijavljenom venjenju; potvrdite ga na njivi.":
        "The soil water status was estimated as %s from the reported wilting; confirm it in the field.",
    "Poslednji upotrebljiv snimak je star %s dana, sa %s %% upotrebljivih piksela.":
        "The latest usable image is %s days old, with %s %% usable pixels.",
    "Prognoza padavina za naredna tri dana: %s mm.": "Rainfall forecast for the next three days: %s mm.",
    "Referentna evapotranspiracija u prethodnih sedam dana: %s mm; padavine: %s mm.":
        "Reference evapotranspiration over the past seven days: %s mm; rainfall: %s mm.",
    "Stanje vode u zemljištu procenjeno je kao %s jer je parcela navodnjavana %s sa %s mm (procena, pouzdanost: %s).":
        "The soil water status was estimated as %s because the parcel was irrigated on %s with %s mm (estimate, reliability: %s).",
    "Stanje vode u zemljištu procenjeno je kao %s prema prijavljenom venjenju (pouzdanost: %s); potvrdite ga na njivi.":
        "The soil water status was estimated as %s from the reported wilting (reliability: %s); confirm it in the field.",
    "Stanje vode u zemljištu prema vašem navodu: %s.": "Soil water status as you reported it: %s.",
    "Prognoza padavina za narednih sedam dana: %s mm.": "Rainfall forecast for the next seven days: %s mm.",
    "Dosadašnje đubrenje: %s.": "Fertiliser applied so far: %s.",
    "preduseva i stajnjaka": "the previous crop and manure",
    "preduseva": "the previous crop",
    "stajnjaka": "manure",
    "Zbog %s računa se sa delom azota iz zemljišta, pa je preporučeni opseg doze niži.":
        "Because of %s, part of the nitrogen is expected to come from the soil, so the recommended rate band is lower.",
    "Najjači prognozirani vetar u narednih sedam dana: %s m/s.": "Strongest forecast wind over the next seven days: %s m/s.",
    "Prognozirana temperatura: %s.": "Forecast temperature: %s.",
    "Poslednji upotrebljiv snimak je star %s dana, sa %s %% upotrebljivih piksela (pouzdanost: %s).":
        "The latest usable image is %s days old, with %s %% usable pixels (reliability: %s).",
    "Razlika između bujnijih i slabijih delova parcele (NDVI): %s.": "Difference between stronger and weaker parts of the parcel (NDVI): %s.",
    "Promena indeksa u poslednjih 14 dana: %s.": "Change of the index over the last 14 days: %s.",
    "pH zemljišta (%s) je van opsega %s–%s; proverite sa savetodavcem potrebu za kalcifikacijom ili korekcijom pH.":
        "Soil pH (%s) is outside the range %s–%s; check with an adviser whether liming or pH correction is needed.",
    "Faza razvoja je procenjena iz datuma setve; potvrdite je na njivi.": "The growth stage was estimated from the sowing date; confirm it in the field.",
    "%s: niska pouzdanost (%s).": "%s: low reliability (%s).",
    "Nema upotrebljivog satelitskog snimka; savet se ne oslanja na satelitske podatke.":
        "There is no usable satellite image; the advice does not rely on satellite data.",
    "Izvori se razlikuju; prednost je data izvoru koji je primenljiv na ovu parcelu.":
        "The sources differ; the source that applies to this parcel was given priority.",
    "Izvori se razlikuju u jednom delu saveta; oba stava su navedena među izvorima.":
        "The sources differ on one part of the advice; both positions are listed among the sources.",
    "Deo izvora je samo uslovno primenljiv na ovu parcelu; uslovi su navedeni uz izvor.":
        "Some sources apply to this parcel only conditionally; the conditions are listed with the source.",
    "Odlučilo: ": "Decided by: ",
    "Odlučilo: nijedan podatak o parceli": "Decided by: no parcel data",
    "nedostaje: ": "missing: ",
    "Sistem jednu normu daje za oko %s dana.": "The system delivers one application in about %s days.",
    "Na terenu proverite: ": "Check in the field: ",
    "Orijentaciono: ": "For orientation: ",
    "Odluka zavisi od jednog podatka koji nedostaje: %s.": "The decision depends on one missing datum: %s.",
    "Količinu ili dozu nije moguće odrediti; nedostaje: %s.": "The amount or rate cannot be determined; missing: %s.",
    "Nije poznato: %s.": "Not known: %s.",
    "Podatak koji nedostaje ne menja ovu odluku, pa ga ne tražimo.": "The missing datum does not change this decision, so we do not ask for it.",
    "Primenljivi izvori se ne slažu u ovoj odluci; oba stava su navedena, a odluku proverite sa savetodavcem.":
        "The applicable sources disagree on this decision; both positions are listed, and you should check the decision with an adviser.",
    "Izvori %s preporučuju: %s.": "Sources %s recommend: %s.",
    "Savet se oslanja na podatke niske pouzdanosti: %s; proverite ih pre odluke.":
        "The advice relies on data of low reliability: %s; check them before deciding.",
    "Pre preporuke potreban je jedan podatak: %s.": "One datum is needed before a recommendation: %s.",
    "Količina ili doza se ne navodi dok ovaj podatak nije poznat.": "No amount or rate is given until this datum is known.",
    "Nema dovoljno pouzdanih podataka za preporuku; nedostaje: %s.": "There are not enough reliable data for a recommendation; missing: %s.",
    "Osvežite podatke o parceli kasnije ili se obratite savetodavnoj službi.":
        "Refresh the parcel data later or contact the advisory service.",
    "Do novog upotrebljivog snimka obilazite parcelu po uobičajenom rasporedu.":
        "Until a new usable image is available, walk the parcel on the usual schedule.",
    # ---- pipeline/field_status.py
    "danas": "today",
    "juče": "yesterday",
    "pre %s": "%s ago",
    "NDVI: nema upotrebljivog snimka": "NDVI: no usable image",
    "%s: nema podatka": "%s: no data",
    "NDVI od danas": "NDVI from today",
    "NDVI star %s": "NDVI %s old",
    ", %s %% piksela": ", %s %% of pixels",
    "Prognoza od danas": "Forecast from today",
    "Prognoza od juče": "Forecast from yesterday",
    "Prognoza stara %s": "Forecast %s old",
    "Faza %s, procena iz setve": "Stage %s, estimated from sowing",
    "Faza %s, prijavljena %s": "Stage %s, reported %s",
    "Faza %s": "Stage %s",
    "%s: %s, procena": "%s: %s, estimate",
    "%s: %s, prijavljeno %s": "%s: %s, reported %s",
    "%s: %s": "%s: %s",
    "nema podatka": "no data",
    "%s: nema prognoze vetra ili padavina za ovaj dan.": "%s: no wind or rain forecast for this day.",
    "vetar do %s m/s je iznad granice od %s m/s": "wind up to %s m/s is above the %s m/s limit",
    "vetar do %s m/s je blizu granice od %s m/s (zanošenje)": "wind up to %s m/s is close to the %s m/s limit (drift)",
    "padavine %s mm su iznad %s mm": "rain %s mm is above %s mm",
    "kiša narednog dana (%s mm) može sprati sredstvo": "rain the next day (%s mm) may wash off the product",
    "vetar do %s m/s, padavine %s mm": "wind up to %s m/s, rain %s mm",
    "%s: nema prognoze padavina za ovaj dan.": "%s: no rain forecast for this day.",
    "jake padavine (%s mm) ispiraju đubrivo i otežavaju prolaz": "heavy rain (%s mm) washes out fertiliser and makes access difficult",
    "padavine istog dana (%s mm); bolje rasturiti pre kiše": "rain the same day (%s mm); better to spread before the rain",
    "suvo, a kiša narednog dana (%s mm) pomaže unošenje đubriva": "dry, and rain the next day (%s mm) helps to incorporate the fertiliser",
    "padavine %s mm; đubrivo uneti u zemljište ako je moguće": "rain %s mm; incorporate the fertiliser into the soil if possible",
    "jake padavine (%s mm), zemljište je prevlažno za obradu": "heavy rain (%s mm), the soil is too wet for tillage",
    "padavine %s mm; proveriti da li je zemljište dovoljno suvo": "rain %s mm; check that the soil is dry enough",
    "padavine %s mm": "rain %s mm",
    "%s: nema prognoze minimalne temperature za ovaj dan.": "%s: no minimum temperature forecast for this day.",
    "najniža temperatura %s °C, rizik od mraza": "lowest temperature %s °C, risk of frost",
    "najniža temperatura %s °C, blizu mraza": "lowest temperature %s °C, close to frost",
    "najniža temperatura %s °C": "lowest temperature %s °C",
    "jake padavine (%s mm)": "heavy rain (%s mm)",
    "%s: %s.": "%s: %s.",
    "Nema prognoze vremena za ovu parcelu; osvežite podatke.": "There is no weather forecast for this parcel; refresh the data.",
    "Podaci o parceli još nisu pribavljeni.": "The parcel data have not been fetched yet.",
    "Prognoza pokriva samo %s od narednih %s dana.": "The forecast covers only %s of the next %s days.",
    # ---- pipeline/profile.py, providers, geo (stored or raised as finished text)
    "U poslednjih 90 dana nema upotrebljivog snimka bez oblaka.": "There is no usable cloud-free image in the last 90 days.",
    "Satelitski servis nije podešen (CDSE_CLIENT_ID i CDSE_CLIENT_SECRET).":
        "The satellite service is not configured (CDSE_CLIENT_ID and CDSE_CLIENT_SECRET).",
    "Prijava na satelitski servis nije uspela: KeyError": "Signing in to the satellite service failed: KeyError",
    "Prijava na satelitski servis nije uspela": "Signing in to the satellite service failed",
    "Satelitski servis nije dostupan": "The satellite service is not available",
    "Meteorološki servis nije dostupan": "The weather service is not available",
    "nepoznata greška": "unknown error",
    "Režim bez mreže: traženi odgovor nije u kešu (%s).": "Offline mode: the requested response is not in the cache (%s).",
    "Prognoza izdata pre trenutka odluke nije dostupna (%s).": "A forecast issued before the decision time is not available (%s).",
    "Podatak u kešu pribavljen je posle trenutka odluke (%s).": "The cached datum was fetched after the decision time (%s).",
    "Demo podaci: sintetička NDVI serija, samo za prikaz.": "Demo data: synthetic NDVI series, for display only.",
    "DEMO: sintetički NDVI (nije Sentinel-2)": "DEMO: synthetic NDVI (not Sentinel-2)",
    "Parcela je manja od 0,3 ha; satelitski podaci su manje pouzdani zbog malog broja piksela.":
        "The parcel is smaller than 0.3 ha; satellite data are less reliable because of the small number of pixels.",
    "Geometrija mora biti GeoJSON poligon.": "The geometry must be a GeoJSON polygon.",
    "Poligon sa rupama nije podržan; ucrtajte jednu zatvorenu liniju.": "Polygons with holes are not supported; draw one closed line.",
    "Poligon nije zatvoren: prva i poslednja tačka moraju biti iste.": "The polygon is not closed: the first and the last point must be the same.",
    "Poligon mora imati najmanje tri temena.": "The polygon must have at least three vertices.",
    "Poligon nema površinu.": "The polygon has no area.",
    "Poligon seče sam sebe; ucrtajte granicu bez ukrštanja.": "The polygon intersects itself; draw a boundary without crossings.",
    "Površina parcele je %.2f ha; podržan je opseg od %.2f do %.0f ha.": "The parcel area is %s ha; the supported range is %s to %s ha.",
    "Koordinate poligona nisu ispravne.": "The polygon coordinates are not valid.",
    "Poligon ima previše temena (najviše %d).": "The polygon has too many vertices (at most %d).",
    "Polje %s nije ispravno.": "The field %s is not valid.",
    "Neispravan datum u polju %s (očekuje se GGGG-MM-DD).": "Invalid date in the field %s (expected YYYY-MM-DD).",
    "BBCH mora biti ceo broj od 0 do 99.": "BBCH must be a whole number from 0 to 99.",
    "Koordinate moraju biti geografska dužina i širina (WGS84).": "Coordinates must be longitude and latitude (WGS84).",
    # ---- api/service.py
    "Kapacitet sistema (mm/dan)": "System capacity (mm/day)",
    "Količina poslednjeg navodnjavanja (mm)": "Amount of the last irrigation (mm)",
    "Količina stajnjaka (t/ha)": "Amount of manure (t/ha)",
    "Grupa zrenja (FAO)": "Maturity group (FAO)",
    "Gustina sklopa (biljaka/ha)": "Plant density (plants/ha)",
    "Datum poslednjeg navodnjavanja": "Date of the last irrigation",
    "Datum unošenja stajnjaka": "Date of manure application",
    "pH": "pH",
    "Humus (%)": "Humus (%)",
    "P2O5 (mg/100 g)": "P2O5 (mg/100 g)",
    "K2O (mg/100 g)": "K2O (mg/100 g)",
    "%s: očekuje se broj.": "%s: a number is expected.",
    "%s: vrednost mora biti između %s i %s.": "%s: the value must be between %s and %s.",
    "%s: očekuje se ceo broj.": "%s: a whole number is expected.",
    "%s: očekuje se datum u obliku GGGG-MM-DD.": "%s: a date in the form YYYY-MM-DD is expected.",
    "%s: očekuje se lista zapisa.": "%s: a list of records is expected.",
    "%s: nepoznato polje %s.": "%s: unknown field %s.",
    "Predusev: nepoznata vrednost %s.": "Previous crop: unknown value %s.",
    "Zapis o đubrenju": "Fertiliser record",
    "Zapis o đubrenju: naziv đubriva je obavezan.": "Fertiliser record: the fertiliser name is required.",
    "Zapis o đubrenju, datum": "Fertiliser record, date",
    "Zapis o đubrenju, količina (kg/ha)": "Fertiliser record, amount (kg/ha)",
    "Zapis o đubrenju, azot (kg N/ha)": "Fertiliser record, nitrogen (kg N/ha)",
    "Zapažanje": "Observation",
    "Zapažanje: nepoznata vrsta %s.": "Observation: unknown kind %s.",
    "Zapažanje: napomena mora biti tekst.": "Observation: the note must be text.",
    "Zapažanje, datum": "Observation, date",
    "Analiza zemljišta: očekuje se zapis.": "Soil analysis: a record is expected.",
    "Analiza zemljišta: nepoznato polje %s.": "Soil analysis: unknown field %s.",
    "Analiza zemljišta, datum": "Soil analysis, date",
    "Analiza zemljišta, %s": "Soil analysis, %s",
    "Analiza zemljišta: nepoznat nivo %s.": "Soil analysis: unknown level %s.",
    "Naziv parcele je obavezan.": "The parcel name is required.",
    "Parcela nije pronađena.": "Parcel not found.",
    "Nepoznato polje: %s.": "Unknown field: %s.",
    "Nepoznata varijanta: %s.": "Unknown variant: %s.",
    "Razgovor nije pronađen.": "Conversation not found.",
    "Nisam razumeo odgovor. Izaberite jednu od ponuđenih opcija ili napišite „ne znam”.":
        "I did not understand the answer. Choose one of the options offered or write “I don't know”.",
    "Nema otvorenog pitanja na koje se ovaj odgovor odnosi.": "There is no open question this answer refers to.",
    "Nepoznata vrsta saveta.": "Unknown type of advice.",
    # spec 037: owner correction of the parcel jurisdiction
    "Nepoznata oznaka države.": "Unknown country code.",
    "Nepoznata oznaka entiteta ili oblasti.": "Unknown entity or region code.",
    "Nepoznata vremenska zona.": "Unknown time zone.",
    "Pitanje je prazno.": "The question is empty.",
    "Poruka je prazna.": "The message is empty.",
    "Poruka je predugačka (najviše 2000 znakova).": "The message is too long (at most 2000 characters).",
    "AI razgovor nije podešen: %s.": "AI chat is not configured: %s.",
    "AI razgovor nije podešen (LLM_PROVIDER).": "AI chat is not configured (LLM_PROVIDER).",
    "AI model nije odgovorio: %s.": "The AI model did not answer: %s.",
    "Odgovor nije pronađen.": "Answer not found.",
    "Na šta se pitanje odnosi?": "What is the question about?",
    "Nisam siguran na koju vrstu saveta se pitanje odnosi.": "I am not sure which type of advice the question is about.",
    "Stavka za ocenjivanje nije pronađena.": "Rating item not found.",
    # ---- api/auth.py, accounts
    "Niste prijavljeni.": "You are not signed in.",
    "Niste član nijedne organizacije.": "You are not a member of any organisation.",
    "Vaša uloga u organizaciji ne dozvoljava ovu radnju.": "Your role in the organisation does not allow this action.",
    "Ovaj deo je dostupan samo istraživačima.": "This part is available to researchers only.",
    "Zahtev je odbijen: nedostaje zaglavlje X-Requested-With: smartagri.": "Request refused: the X-Requested-With: smartagri header is missing.",
    "Ako nalog postoji i nije potvrđen, poslali smo novu vezu za potvrdu.":
        "If the account exists and is not confirmed, we have sent a new confirmation link.",
    "Ako nalog sa ovom e-adresom postoji, poslali smo vezu za novu lozinku.":
        "If an account with this e-mail address exists, we have sent a link for a new password.",
    "Pogrešna e-adresa ili lozinka.": "Wrong e-mail address or password.",
    "E-adresa još nije potvrđena. Proverite poštu ili zatražite novu vezu za potvrdu.":
        "The e-mail address is not confirmed yet. Check your mail or ask for a new confirmation link.",
    "Veza nije važeća ili je istekla. Zatražite novu.": "The link is not valid or has expired. Ask for a new one.",
    "Previše pokušaja. Pokušajte ponovo kasnije.": "Too many attempts. Try again later.",
    "Najviše 500 parcela u jednom zahtevu.": "At most 500 parcels per request.",               # spec 056
    "Vrsta naloga mora biti farm ili advisor.": "The account type must be farm or advisor.",   # spec 056
    "Unesite ispravnu e-adresu.": "Enter a valid e-mail address.",
    "Ime je obavezno (najviše 100 znakova).": "The name is required (at most 100 characters).",
    "Naziv organizacije je obavezan (najviše 100 znakova).": "The organisation name is required (at most 100 characters).",
    "Nalog sa ovom e-adresom već postoji. Prijavite se ili zatražite novu lozinku.":
        "An account with this e-mail address already exists. Sign in or ask for a new password.",
    "Nepoznata uloga. Dozvoljeno: owner, agronomist, worker, inspector.": "Unknown role. Allowed: owner, agronomist, worker, inspector.",
    "Niste član ove organizacije.": "You are not a member of this organisation.",
    "Organizacija mora imati bar jednog vlasnika.": "The organisation must have at least one owner.",
    "Član nije pronađen.": "Member not found.",
    "Poziv nije pronađen.": "Invitation not found.",
    "Korisnik sa ovom e-adresom je već član organizacije.": "A user with this e-mail address is already a member of the organisation.",
    "Trenutna lozinka nije ispravna.": "The current password is not correct.",
    "Za novi nalog unesite ime i lozinku.": "For a new account, enter a name and a password.",
    "Dostignut je dnevni broj AI razgovora za vašu organizaciju (%d). Pokušajte ponovo sutra.":
        "Your organisation has reached its daily number of AI chats (%d). Try again tomorrow.",
    "Samo vlasnik može da uklanja članove.": "Only an owner can remove members.",
    "Lozinka mora imati najmanje %d znakova.": "The password must have at least %d characters.",
    "Lozinka je predugačka (najviše %d znakova).": "The password is too long (at most %d characters).",
    "Ova lozinka je previše česta. Izaberite drugu.": "This password is too common. Choose another one.",
    "Lozinka ne sme biti ista kao e-adresa.": "The password must not be the same as the e-mail address.",
    "Nepoznat jezik. Dozvoljeno: sr-Latn, sr-Cyrl, en.": "Unknown language. Allowed: sr-Latn, sr-Cyrl, en.",
    # ---- activities.py
    "%s: očekuje se tekst.": "%s: text is expected.",
    "%s: najviše %d znakova.": "%s: at most %d characters.",
    "%s: dozvoljena su slova, cifre i znakovi . _ / - (najviše 64).": "%s: letters, digits and the characters . _ / - are allowed (at most 64).",
    "%s: nepoznata vrednost %s.": "%s: unknown value %s.",
    "Nepoznata vrsta rada: %s.": "Unknown kind of work: %s.",
    "%s: detalji moraju biti zapis (objekat).": "%s: details must be a record (object).",
    "%s: polje „%s” je obavezno.": "%s: the field “%s” is required.",
    "%s, %s": "%s, %s",
    "Vrsta rada se ne menja; obrišite zapis i unesite novi.": "The kind of work cannot be changed; delete the entry and enter a new one.",
    "Vrsta rada je obavezna.": "The kind of work is required.",
    "Datum": "Date",
    "Datum završetka": "End date",
    "Datum završetka ne može biti pre datuma početka.": "The end date cannot be before the start date.",
    "Nepoznat status: %s.": "Unknown status: %s.",
    "Izvršio": "Performed by",
    "Napomena": "Note",
    "Od": "From",
    "Do": "To",
    "prognoza od %s": "forecast from %s",
    "profil od %s": "profile from %s",
    "%s kg/ha semena": "%s kg/ha of seed",
    "%s, %s kg/ha": "%s, %s kg/ha",
    " (%s kg N/ha%s)": " (%s kg N/ha%s)",
    ", iz kataloga": ", from the catalogue",
    "%s, %s %s": "%s, %s %s",
    "a. m. ": "a.s. ",
    "cilj: ": "target: ",
    "karenca ": "pre-harvest interval ",
    "vetar %s m/s": "wind %s m/s",
    "%s mm": "%s mm",
    "dubina %s cm": "depth %s cm",
    "lot ": "lot ",
    "%s t/ha": "%s t/ha",
    "vlaga %s %%": "moisture %s %%",
    "ukupno %s t": "total %s t",
    "da": "yes",
    "dnevnik-radova": "activity-log",
    # ---- api/records.py
    "Zapis u dnevniku radova nije pronađen.": "Activity log entry not found.",
    "Radnik može da menja samo zapise koje je sam uneo.": "A worker can change only the entries they recorded.",
    "Lot nije pronađen.": "Lot not found.",
    "Karenca nije upisana.": "No pre-harvest interval was recorded.",
    "Karenca je ispoštovana.": "The pre-harvest interval was respected.",
    "korisnik": "user",
    "procena iz koordinata": "estimate from coordinates",
    "Zemlja: očekuje se dvoslovna oznaka ISO 3166-1 (npr. BA).": "Country: a two-letter ISO 3166-1 code is expected (e.g. BA).",
    "%s: očekuje se da ili ne (true/false).": "%s: yes or no (true/false) is expected.",
    "Geometrija parcele nije upotrebljiva za EUDR: %s": "The parcel geometry cannot be used for the EUDR: %s",
    "Izaberite bar jednu parcelu (parcel_ids).": "Choose at least one parcel (parcel_ids).",
    "Operater: očekuje se zapis {name, address, eori}.": "Operator: a record {name, address, eori} is expected.",
    "Operater: nepoznato polje %s.": "Operator: unknown field %s.",
    "Operater: naziv i adresa su obavezni.": "Operator: name and address are required.",
    "Operater: EORI broj počinje dvoslovnom oznakom zemlje i ima najviše 17 znakova.":
        "Operator: an EORI number starts with a two-letter country code and has at most 17 characters.",
    "Roba: nepoznata vrednost %s (dozvoljeno: %s).": "Commodity: unknown value %s (allowed: %s).",
    "HS oznaka: očekuje se 4 do 10 cifara (npr. 1201 90).": "HS code: 4 to 10 digits are expected (e.g. 1201 90).",
    "Količina: očekuje se pozitivan broj.": "Quantity: a positive number is expected.",
    "Jedinica količine: kg ili t.": "Unit of quantity: kg or t.",
    "Lotovi: očekuje se lista oznaka.": "Lots: a list of IDs is expected.",
    "nije navedena": "not given",
    "Parcela „%s”: kultura (%s) ne odgovara robi „%s”.": "Parcel “%s”: the crop (%s) does not match the commodity “%s”.",
    "Parcela „%s”, nedostaje: %s.": "Parcel “%s”, missing: %s.",
    "Lot %s potiče i sa parcela koje nisu u izjavi: %s.": "Lot %s also comes from parcels that are not in the statement: %s.",
    "Lot %s je planiran (žetva/berba još nije upisana kao obavljena).": "Lot %s is planned (the harvest is not yet recorded as done).",
    "Lot %s: %s": "Lot %s: %s",
    "nacrt": "draft",
    "Izjava nije pronađena.": "Statement not found.",
    # ---- eudr.py
    "Poligon posle zaokruživanja na 6 decimala ima manje od tri temena.": "After rounding to 6 decimals the polygon has fewer than three vertices.",
    "Parcela ima manje od 4 ha: geolokacija je jedna tačka unutar parcele (WGS84, 6 decimala).":
        "The plot has less than 4 ha: the geolocation is one point inside the plot (WGS84, 6 decimals).",
    "Parcela ima 4 ha ili više: geolokacija je poligon granice parcele (WGS84, 6 decimala).":
        "The plot has 4 ha or more: the geolocation is the polygon of the plot boundary (WGS84, 6 decimals).",
    "neispravna koordinata %r": "invalid coordinate %s",
    "koordinata van opsega WGS84 %r": "coordinate outside the WGS84 range %s",
    "više od 6 decimala u %r": "more than 6 decimals in %s",
    "prsten ima manje od 4 pozicije": "the ring has fewer than 4 positions",
    "prsten nije zatvoren": "the ring is not closed",
    "poligon sa rupama nije podržan": "polygons with holes are not supported",
    "tip geometrije %s nije dozvoljen": "geometry type %s is not allowed",
    "Soja je roba iz Priloga I Uredbe (EU) 2023/1115.": "Soya is a relevant commodity listed in Annex I to Regulation (EU) 2023/1115.",
    "Ova kultura nije roba iz Priloga I Uredbe (EU) 2023/1115 (relevantne su soja, goveda, kakao, kafa, uljana palma, kaučuk i drvo); izjava o dužnoj pažnji za nju nije potrebna.":
        "This crop is not a relevant commodity listed in Annex I to Regulation (EU) 2023/1115 (the relevant commodities are "
        "cattle, cocoa, coffee, oil palm, rubber, soya and wood); no due diligence statement is needed for it.",
    "dnevnik radova": "activity log",
    "podaci parcele": "parcel data",
    "Predlog iz koordinata: %s; potvrdite zemlju.": "Suggested from the coordinates: %s; confirm the country.",
    "Unesite zemlju proizvodnje.": "Enter the country of production.",
    "Žetva/berba je planirana za %s.": "The harvest is planned for %s.",
    "Sistem ne proverava krčenje šuma automatski; upišite da li je provera urađena i kojim izvorom.":
        "The system does not check deforestation automatically; record whether a check was done and with which source.",
    "HS oznaka %s ne odgovara tarifnim oznakama robe „%s” iz Priloga I (%s).":
        "HS code %s does not match the tariff headings of the commodity “%s” in Annex I (%s).",
    # ---- eudr_pdf.py
    "nije navedeno": "not given",
    "Font iz SMARTAGRI_PDF_FONT ne postoji: %s.": "The font from SMARTAGRI_PDF_FONT does not exist: %s.",
    "PDF nije moguće napraviti: na serveru nema fonta sa srpskim slovima (DejaVu Sans).":
        "The PDF cannot be created: the server has no font with the required characters (DejaVu Sans).",
    "PDF nije moguće napraviti: biblioteka reportlab nije instalirana.": "The PDF cannot be created: the reportlab library is not installed.",
    "Nacrt izjave o dužnoj pažnji (EUDR)": "Draft due diligence statement (EUDR)",
    "Oznaka: %s · status: nacrt · napravljeno: %s": "Reference: %s · status: draft · created: %s",
    "Uredba (EU) 2023/1115, izmenjena Uredbom (EU) 2025/2650; primena od %s (srednji i veliki operateri), od %s (mikro i mali operateri).":
        "Regulation (EU) 2023/1115, as amended by Regulation (EU) 2025/2650; applies from %s (medium-sized and large "
        "operators) and from %s (micro and small operators).",
    "Operater": "Operator",
    "Naziv": "Name",
    "Adresa": "Address",
    "EORI": "EORI",
    "Roba": "Commodity",
    "HS oznaka": "HS code",
    "Količina (neto masa)": "Quantity (net mass)",
    "Lotovi": "Lots",
    "%s kg": "%s kg",
    "Parcele (mesta proizvodnje)": "Plots of land (places of production)",
    "Parcela": "Plot",
    "Zemlja": "Country",
    "Površina (ha)": "Area (ha)",
    "Geolokacija": "Geolocation",
    "Period proizvodnje": "Production period",
    "Izjava 31. 12. 2020.": "Statement 31 Dec 2020",
    "tačka": "point",
    "poligon": "polygon",
    "%s – %s": "%s – %s",
    "da, %s": "yes, %s",
    "ne": "no",
    "Koordinate (WGS84, geografska širina, dužina; 6 decimala)": "Coordinates (WGS84, latitude, longitude; 6 decimals)",
    "%s · %s": "%s · %s",
    "Sledljivost lotova": "Lot traceability",
    "Lot %s (%s)": "Lot %s (%s)",
    "planiran": "planned",
    "ubran": "harvested",
    "Rad": "Work",
    "Detalji": "Details",
    " (planirano)": " (planned)",
    "Parcela: %s": "Plot: %s",
    "Upozorenje: %s": "Warning: %s",
    "Kontrolna lista": "Checklist",
    "Stavka": "Item",
    "Stanje": "Status",
    "u redu": "OK",
    "nedostaje": "missing",
    "nije upisano": "not recorded",
    "Upozorenja": "Warnings",
    "Provera krčenja šuma prema spoljnim skupovima podataka nije automatizovana u sistemu Open Crop Manager; izjave o korišćenju zemljišta su navodi korisnika. GeoJSON za informacioni sistem EU: /api/eudr/statements/%s.geojson.":
        "The deforestation check against external data sets is not automated in Open Crop Manager; statements on land use are the "
        "user's declarations. GeoJSON for the EU information system: /api/eudr/statements/%s.geojson.",
    "Open Crop Manager · %s · nacrt, nije podneta izjava · strana %d": "Open Crop Manager · %s · draft, not a submitted statement · page %d",
    # ---- pipeline/ai_chat.py
    "Deo odgovora je uklonjen jer nije potkrepljen podacima parcele ni izvorima.":
        "Part of the answer was removed because it is not supported by the parcel data or the sources.",
    "Ne mogu da dam potkrepljen odgovor na osnovu podataka ove parcele i dostupnih izvora.":
        "I cannot give a supported answer based on this parcel's data and the available sources.",
    "Niska pouzdanost podataka: %s.": "Low data reliability: %s.",
    "Prevod na engleski nije prošao proveru; prikazan je odgovor na lokalnom jeziku.":
        "The English translation did not pass the checks; the answer is shown in the local language.",
    "Prevod odgovora nije prošao proveru; prikazan je odgovor na lokalnom jeziku.":
        "The translation of the answer did not pass the checks; the answer is shown in the local language.",
    "AI razgovor nije podešen. Podesite LLM_PROVIDER (claude-cli, anthropic, openai, deepseek, kimi, mistral, ollama, lmstudio ili openai-compatible).":
        "AI chat is not configured. Set LLM_PROVIDER (claude-cli, anthropic, openai, deepseek, kimi, mistral, ollama, lmstudio or openai-compatible).",
}

# ---------------------------------------------------------------- spec 018: alerts and notifications
ALERT_KINDS = [{"value": "frost", "label": "Frost in the forecast"}, {"value": "heavy_rain", "label": "Heavy rain in the forecast"},
               {"value": "spray_window", "label": "Spraying window"}, {"value": "stale_data", "label": "Outdated data"},
               {"value": "eudr_missing", "label": "EUDR: incomplete record"}]
ALERT_CHANNELS = [{"value": "email", "label": "E-mail"}, {"value": "push", "label": "Push notification"},
                  {"value": "inapp", "label": "In the app"}]
ALERT_STATUS = {"active": "active", "updated": "updated", "withdrawn": "withdrawn", "expired": "expired"}
ALERT_TEXTS = {
    "kind.test": "Test notification",
    "frost.title": "Frost possible: {parcel}",
    "frost.body": ("Frost possible on {date} on the plot {parcel}: lowest forecast temperature {tmin} °C "
                   "(forecast of {issued}, reliability {reliability})."),
    "heavy_rain.title": "Heavy rain in the forecast: {parcel}",
    "heavy_rain.body": ("Heavy rain in the forecast for {date} on the plot {parcel}: {rain} mm, more than {limit} mm "
                        "(forecast of {issued}, reliability {reliability})."),
    "spray_window.title": "Spraying window opens: {parcel}",
    "spray_window.body": ("A spraying window opens on {date} on the plot {parcel}: wind up to {wind} m/s, rainfall {rain} mm "
                          "(forecast of {issued}, reliability {reliability})."),
    "stale_data.title": "Outdated data: {parcel}",
    "stale_data.body": "The data item “{source}” of the plot {parcel} is outdated ({age}); the plot profile is from {as_of}.",
    "eudr_missing.title": "EUDR record incomplete: {parcel}",
    "eudr_missing.body": "The EUDR record of the plot {parcel} is missing: {items}.",
    "test.title": "Test notification",
    "test.body": "This is an Open Crop Manager test notification. Alerts for your account arrive through this channel.",
    "status.updated": "Updated from a newer forecast.",
    "status.withdrawn": "Withdrawn: a newer forecast no longer shows this.",
    "status.expired": "Expired.",
    "issued": "{date} at {time}",
    "unknown": "unknown",
    "age_days": "{days} old",
    "email.subject": "Open Crop Manager: {title}",
    "email.hello": "Hello {name},",
    "email.button": "Open the plot",
    "email.button_test": "Open Open Crop Manager",
    "email.note": ("The alert states data the system already holds and is not advice. The limits are development values "
                   "still being reviewed by the agronomist."),
    "email.prefs": "Alert settings: {url}",
    "email.unsubscribe": "You receive this message because e-mail alerts are switched on for your account in the organisation {org}.",
    "email.unsubscribe_link": "Unsubscribe from all e-mail alerts",
    "email.footer": "Open Crop Manager · alerts",
    "digest.subject": "Open Crop Manager: alert summary ({count})",
    "digest.intro": "Alert summary for the organisation {org}:",
    "digest.button": "Open the alerts",
    "digest.withdrawn": "{title} (withdrawn)",
    "digest.parcel": "Plot {parcel}",
    "digest.other": "Other",
}
MESSAGES.update({
    # ---- spec 018: alerts, organisation settings, LLM bridge status
    "Upozorenje nije pronađeno.": "Alert not found.",
    "Nepoznato podešavanje: %s.": "Unknown setting: %s.",
    "Nepoznata vrsta upozorenja: %s.": "Unknown alert kind: %s.",
    "Nepoznat kanal obaveštenja: %s.": "Unknown notification channel: %s.",
    "Vreme mora biti u obliku HH:MM.": "The time must be in the form HH:MM.",
    "Lista parcela nije ispravna.": "The list of plots is not valid.",
    "Vrednost mora biti da ili ne (true/false).": "The value must be yes or no (true/false).",
    "Nepoznata vremenska zona: %s.": "Unknown time zone: %s.",
    "Veza za odjavu nije važeća ili je istekla.": "The unsubscribe link is not valid or has expired.",
    "Odjava je sprovedena: upozorenja e-poštom su isključena.": "Done: e-mail alerts are switched off.",
    "Push obaveštenja nisu podešena na serveru (nedostaje VAPID ključ).":
        "Push notifications are not set up on the server (the VAPID key is missing).",
    "Pretplata za push obaveštenja nije ispravna.": "The push subscription is not valid.",
    "Pretplata nije pronađena.": "Subscription not found.",
    "Previše probnih obaveštenja. Pokušajte ponovo za sat vremena.": "Too many test notifications. Try again in an hour.",
    "AI razgovor trenutno nije dostupan: veza sa AI posrednikom (bridge) nije uspostavljena.":
        "AI chat is not available right now: the connection to the AI bridge could not be made.",
})

# ---- Costs, revenue and gross margin (spec 022): label tables (same keys as economics.SR) and messages.
ECONOMICS: Dict[str, Any] = {
    "cost_kinds": {"input": "Inputs (materials)", "labour": "Labour", "machinery": "Machinery", "service": "Services",
                   "other": "Other", "overhead": "Overheads", "correction": "Correction"},
    "price_kinds": {"input": "Input (material)", "service": "Service", "labour": "Labour", "machinery": "Machinery",
                    "sale": "Sale (price per unit)"},
    "units": {"kg": "kg", "g": "g", "t": "t", "l": "l", "ml": "ml", "m3": "m³", "h": "h", "ha": "ha", "piece": "pcs"},
    "split_rules": {"quantity": "in proportion to the harvested quantity", "area": "in proportion to the area",
                    "manual": "shares entered by hand"},
    "price_sources": {"price_list": "from the price list", "manual": "entered by hand"},
    "revenue_sources": {"sales": "sales", "price_list": "harvested quantity × sale price from the price list"},
    "harvest_sources": {"quantity_t": "total quantity from the harvest", "yield_x_area": "yield × area"},
    "missing": {
        "no_harvest": "No harvest recorded; revenue is unknown.",
        "harvest_planned": "The harvest is only planned; planned work does not count as revenue.",
        "no_harvest_quantity": "Neither a yield nor a total quantity is recorded for the harvest.",
        "no_price": "No sale price entered (neither a sale nor a sale price in the price list).",
        "activities_without_costs": "Work without recorded costs: %s.",
        "no_area": "The parcel area is unknown; per-hectare values are not computed.",
        "revenue_partial": "Revenue is not known for every parcel (%d of %d).",
    },
    "flags": {
        "area_changed": "The parcel area changed after costs were recorded (%s); quantities use the area at the time of entry.",
        "demo": "Example prices (demo): the amounts are illustrative, not market prices.",
        "planned_costs": "Costs of planned work (%s) are not included.",
    },
    "formula": {"manual_amount": "amount entered", "water": "%s mm × %s ha × 10 m³/(mm·ha) = %s m³"},
    "csv_headers": ["Parcel", "Crop", "Area (ha)", "Total costs", "Costs per ha", "Revenue", "Revenue per ha",
                    "Gross margin", "Gross margin per ha", "Overheads (share)", "Margin after overheads", "Complete",
                    "Missing", "Currency", "Demo"],
    "csv_line_headers": ["Date", "Work", "Cost kind", "Item", "Quantity", "Unit", "Price", "Price source", "Amount",
                         "Currency", "Calculation", "Note", "Demo", "ID"],
    "total_crop": "Total: %s",
    "total_farm": "Farm total",
    "overheads": "Farm overheads",
    "yes": "yes", "no": "no", "unknown": "not entered",
    "vat_note": "Amounts are net, without value added tax; the system computes no tax.",
    "statement": "The report contains data entered by the user; it is not an accounting or tax document.",
    "demo_note": "Example prices: demo amounts are illustrative and are not market prices.",
}
for _sr, _en in {
    "Iz ovog unosa dnevnika ne može se izračunati količina; unesite količinu i jedinicu.":
        "No quantity can be computed from this log entry; enter a quantity and a unit.",
    "%s: očekuje se broj.": "%s: a number is expected.",
    "%s: najviše %d decimala.": "%s: at most %d decimals.",
    "%s: vrednost ne može biti negativna.": "%s: the value cannot be negative.",
    "%s: vrednost mora biti veća od nule.": "%s: the value must be greater than zero.",
    "Nepoznata jedinica: %s. Dozvoljeno: %s.": "Unknown unit: %s. Allowed: %s.",
    "Jedinica cene (%s) ne odgovara jedinici količine (%s); sistem ne pretvara masu u zapreminu ni obrnuto.":
        "The price unit (%s) does not match the quantity unit (%s); the system never converts mass to volume or back.",
    "Raspodela nije moguća: zbir osnovica je nula.": "Allocation is not possible: the bases sum to zero.",
    "Udeo je naveden za parcelu koja nije deo prodaje.": "A share was given for a parcel that is not part of the sale.",
    "Prihod nije moguće raspodeliti: nedostaju i količine i površine parcela.":
        "The revenue cannot be split: both the quantities and the areas of the parcels are missing.",
    "Očekuje se JSON objekat.": "A JSON object is expected.",
    "Sezona: očekuje se godina (npr. 2026).": "Season: a year is expected (e.g. 2026).",
    "Naziv": "Name", "Stavka": "Item", "Napomena": "Note", "Datum": "Date", "Oznaka lota": "Lot ID",
    "Nepoznato polje: %s.": "Unknown field: %s.",
    "%s: očekuje se tekst.": "%s: text is expected.",
    "%s: najviše %d znakova.": "%s: at most %d characters.",
    "Organizacija nije pronađena.": "Organisation not found.",
    "Valuta organizacije nije izabrana. Vlasnik je bira (RSD, BAM ili EUR) na stranici Troškovi.":
        "The organisation's currency has not been chosen. The owner chooses it (RSD, BAM or EUR) on the Costs page.",
    "Stavka cenovnika nije pronađena.": "Price list item not found.",
    "Cena": "Price", "Važi od": "Valid from",
    "Prodajna cena se unosi po toni (t).": "A sale price is entered per tonne (t).",
    "Stavka sa ovim nazivom već postoji u cenovniku; dodajte novu cenu postojećoj stavci.":
        "An item with this name is already in the price list; add a new price to the existing item.",
    "price_id: očekuje se oznaka stavke cenovnika.": "price_id: a price list item ID is expected.",
    "Zapis u dnevniku radova nije pronađen.": "Activity log entry not found.",
    "Trošak nije pronađen.": "Cost not found.",
    "Prodaja nije pronađena.": "Sale not found.",
    "Kupac": "Buyer",
    "%s: polje je obavezno.": "%s: the field is required.",
    "%s: očekuje se datum u obliku GGGG-MM-DD.": "%s: a date in the form YYYY-MM-DD is expected.",
    "Valuta %s ne odgovara valuti organizacije (%s); preračunavanje valuta ne postoji.":
        "Currency %s does not match the organisation's currency (%s); there is no currency conversion.",
    "Nepoznata valuta. Dozvoljeno: %s.": "Unknown currency. Allowed: %s.",
    "Valuta se ne može promeniti jer već postoje cene, troškovi ili prodaje.":
        "The currency cannot be changed because prices, costs or sales already exist.",
    "Nepoznata vrsta stavke cenovnika: %s.": "Unknown kind of price list item: %s.",
    "Nepoznata kultura: %s.": "Unknown crop: %s.",
    "Stavka cenovnika „%s” nije odgovarajuće vrste za ovaj trošak.":
        "The price list item \"%s\" is not of a suitable kind for this cost.",
    "Stavka „%s” nema cenu koja važi na dan %s.": "The item \"%s\" has no price valid on %s.",
    "Nepoznata vrsta troška: %s.": "Unknown kind of cost: %s.",
    "Navedite lot ili bar jednu parcelu prodaje.": "Give a lot or at least one parcel of the sale.",
    "Prodata količina (t)": "Quantity sold (t)",
    "Cena po toni": "Price per tonne",
    "Udeli: očekuje se lista {parcel_id, share}.": "Shares: a list of {parcel_id, share} is expected.",
    "Količina": "Quantity",
    "Za trošak inputa potrebna je cena: izaberite stavku iz cenovnika ili unesite cenu.":
        "An input cost needs a price: choose a price list item or enter a price.",
    "Lot %s nema upisanu obavljenu žetvu; planirana žetva se ne računa.":
        "Lot %s has no completed harvest recorded; a planned harvest does not count.",
    "Unesite prodatu količinu (t).": "Enter the quantity sold (t).",
    "Sati": "Hours",
    "Površina parcele nije poznata; unesite količinu.": "The parcel area is unknown; enter a quantity.",
    "Cena po satu": "Price per hour",
    "Iznos": "Amount",
    "Cena rada i mehanizacije unosi se po satu (h).": "Labour and machinery prices are entered per hour (h).",
    "Ispravka mora imati napomenu.": "A correction needs a note.",
    "Naziv: polje je obavezno.": "Name: the field is required.",
    "Troškovi i bruto marža, sezona %s": "Costs and gross margin, season %s",
    "Open Crop Manager · troškovi %s · strana %d": "Open Crop Manager · costs %s · page %d",
    "Parcele, kulture i gazdinstvo": "Parcels, crops and farm",
    "Bruto marža = prihod − varijabilni troškovi. Vrednost koja nije poznata prikazana je kao „nije uneto”, nikad kao "
    "nula; parcela sa nepotpunim podacima ima precenjenu maržu.":
        "Gross margin = revenue − variable costs. A value that is not known is shown as \"not entered\", never as zero; "
        "a parcel with incomplete data has an overstated margin.",
    "Organizacija: %s · valuta: %s · napravljeno: %s": "Organisation: %s · currency: %s · generated: %s",
    "Filter kulture: %s": "Crop filter: %s",
    "Valutu menja vlasnik na stranici Troškovi (PATCH /api/economics/settings), jer se tamo proverava da li već "
    "postoje cene, troškovi ili prodaje.":
        "The owner changes the currency on the Costs page (PATCH /api/economics/settings), where the check for existing "
        "prices, costs or sales is made.",
}.items():
    MESSAGES.setdefault(_sr, _en)
del _sr, _en

# ---- Sensors and soil analyses (spec 020): label tables (same values as labels.py) and messages.
TEXTURE_CLASSES = [{"value": "sand", "label": "Sand (sandy)"}, {"value": "sandy_loam", "label": "Sandy loam"},
                   {"value": "loam", "label": "Loam"}, {"value": "clay_loam", "label": "Clay loam"},
                   {"value": "clay", "label": "Clay (clayey)"}, {"value": "loamy_sand", "label": "Loamy sand"},
                   {"value": "silt_loam", "label": "Silt loam"},
                   {"value": "silty_loam", "label": "Silt loam (code silty_loam)"},
                   {"value": "silt", "label": "Silt"}, {"value": "sandy_clay_loam", "label": "Sandy clay loam"},
                   {"value": "silty_clay_loam", "label": "Silty clay loam"},
                   {"value": "sandy_clay", "label": "Sandy clay"}, {"value": "silty_clay", "label": "Silty clay"}]
SENSOR_TYPES = [{"value": "capacitance", "label": "Capacitance"}, {"value": "tdr", "label": "TDR"},
                {"value": "fdr", "label": "FDR"}, {"value": "tensiometer_converted", "label": "Tensiometer (converted to VWC)"},
                {"value": "other", "label": "Other"}]
VWC_UNITS = [{"value": "m3m3", "label": "m³/m³"}, {"value": "pct", "label": "% by volume"}]
NUTRIENT_FORMS = [{"value": "oxide", "label": "Oxide (P2O5, K2O)"}, {"value": "element", "label": "Element (P, K)"}]
NUTRIENT_UNITS = [{"value": "mg_100g", "label": "mg/100 g"}, {"value": "mg_kg", "label": "mg/kg (ppm)"}]
SOIL_LAB_ORIGIN = "laboratory analysis"
SENSOR_ORIGIN = "sensor"
for _sr, _en in {
    "vreme merenja": "time of measurement",
    "oznaka senzora": "sensor id",
    "dubina (cm)": "depth (cm)",
    "vlažnost (m³/m³)": "moisture (m³/m³)",
    "vlažnost (%)": "moisture (%)",
    "temperatura zemljišta (°C)": "soil temperature (°C)",
    "napon baterije (V)": "battery voltage (V)",
    "parcela": "plot",
    "uređaj": "device",
    "datum uzorkovanja": "sampling date",
    "laboratorija": "laboratory",
    "pH u H2O": "pH in H2O",
    "pH u KCl": "pH in KCl",
    "humus (%)": "humus (%)",
    "P2O5 (mg/100 g)": "P2O5 (mg/100 g)",
    "K2O (mg/100 g)": "K2O (mg/100 g)",
    "N-min (kg/ha)": "N-min (kg/ha)",
    "tekstura": "texture",
    "dubina uzorka od (cm)": "sample depth from (cm)",
    "dubina uzorka do (cm)": "sample depth to (cm)",
    "pesak (%)": "sand (%)",
    "prah (%)": "silt (%)",
    "glina (%)": "clay (%)",
    "CaCO3 (%)": "CaCO3 (%)",
    "datum postavljanja": "installation date",
    "datum premeštanja": "date of the move",
    "Vreme nije prepoznato; očekuje se na primer 2026-07-14 05:00 ili 14.07.2026 05:00.":
        "The time was not recognised; expected for example 2026-07-14 05:00 or 14.07.2026 05:00.",
    "Vreme nema vremensku zonu; navedite je (na primer 2026-07-14T05:00:00+02:00 ili Z).":
        "The time has no time zone; state it (for example 2026-07-14T05:00:00+02:00 or Z).",
    "Nepoznata vremenska zona.": "Unknown time zone.",
    "Vreme merenja je u budućnosti.": "The time of measurement is in the future.",
    "Isto merenje (senzor i vreme) već postoji; preskočeno.": "The same reading (sensor and time) already exists; skipped.",
    "Isto merenje (senzor i vreme) ponavlja se u fajlu; preskočeno.":
        "The same reading (sensor and time) is repeated in the file; skipped.",
    "Navedite tačno jednu vrednost vlažnosti: vwc_m3m3 ili vwc_pct.": "Give exactly one moisture value: vwc_m3m3 or vwc_pct.",
    "Senzor nije registrovan; navedite parcelu i dubinu.": "The sensor is not registered; give the plot and the depth.",
    "Ovaj API ključ nema pristup toj parceli.": "This API key has no access to that plot.",
    "Parcela ili uređaj nije pronađen.": "Plot or device not found.",
    "Senzor je u to vreme bio na drugoj parceli.": "At that time the sensor was on another plot.",
    "Oznaka senzora: 1 do 64 znaka (slova, brojevi, tačka, crtica, donja crta).":
        "Sensor id: 1 to 64 characters (letters, digits, dot, hyphen, underscore).",
    "Parcela nije pronađena u organizaciji.": "Plot not found in the organisation.",
    "Više parcela ima isti naziv; navedite id parcele.": "Several plots have the same name; give the plot id.",
    "Nepoznata klasa teksture.": "Unknown texture class.",
    "Nepoznata jedinica.": "Unknown unit.",
    "Dubina uzorka „do” mora biti veća od dubine „od”.": "The sample depth \"to\" must be greater than the depth \"from\".",
    "Zbir peska, praha i gline mora biti oko 100 %.": "Sand, silt and clay must add up to about 100 %.",
    "Stavka mora biti objekat.": "An item must be an object.",
    "Neispravna vrednost: %s.": "Invalid value: %s.",
    "Nedostaje vrednost: %s.": "Missing value: %s.",
    "Nije broj: %s.": "Not a number: %s.",
    "%s: datum je u budućnosti.": "%s: the date is in the future.",
    "Kolona nije pronađena u fajlu: %s.": "Column not found in the file: %s.",
    "%s: tekst je predugačak (najviše %s znakova).": "%s: the text is too long (at most %s characters).",
    "Fajl je prazan.": "The file is empty.",
    "Prvi red mora da sadrži nazive kolona (najmanje dve kolone).":
        "The first row must contain the column names (at least two columns).",
    "Nazivi kolona u prvom redu moraju biti različiti.": "The column names in the first row must be different.",
    "Fajl nema nijedan red sa podacima.": "The file has no data rows.",
    "Fajl nije u kodnom rasporedu UTF-8. Sačuvajte ga kao „CSV UTF-8” i pokušajte ponovo.":
        "The file is not UTF-8 encoded. Save it as \"CSV UTF-8\" and try again.",
    "Fajl ima previše redova (najviše %s).": "The file has too many rows (at most %s).",
    "Granice suvo/umereno/vlažno za očitavanje senzora (%s i %s m³/m³) iste su za svako zemljište; za peskovito "
    "zemljište su previsoke, za glinovito preniske. Tumačite uz pregled zemljišta.":
        "The dry/moist/wet limits for a sensor reading (%s and %s m³/m³) are the same for every soil; they are too high "
        "for sandy soil and too low for clayey soil. Interpret together with a look at the soil.",
    "Senzor nije označen kao kalibrisan za ovo zemljište; pouzdanost se ocenjuje kao za svako mereno očitavanje.":
        "The sensor is not marked as calibrated for this soil; its reliability is graded like any measured reading.",
    "senzor %s, %s cm": "sensor %s, %s cm",
    "Fajl je prevelik (najviše %s MB).": "The file is too large (at most %s MB).",
    "Naziv uređaja je obavezan.": "The device name is required.",
    "Senzori: očekuje se lista zapisa.": "Sensors: a list of records is expected.",
    "Telo zahteva mora imati listu „readings”.": "The request body must contain a list \"readings\".",
    "Naziv ključa je obavezan.": "The key name is required.",
    "Naziv ključa je predugačak (najviše 120 znakova).": "The key name is too long (at most 120 characters).",
    "Parcele: očekuje se lista.": "Plots: a list is expected.",
    "Previše merenja u jednom zahtevu (najviše %s).": "Too many readings in one request (at most %s).",
    "Oznaka senzora se ponavlja: %s.": "Sensor id repeated: %s.",
    "Senzor %s već pripada drugom uređaju.": "Sensor %s already belongs to another device.",
    "Nepoznata vrsta senzora: %s.": "Unknown sensor type: %s.",
    "Datum premeštanja ne može biti pre poslednjeg postavljanja uređaja.":
        "The date of the move cannot be before the device's last installation.",
    "Za ovu klasu teksture model nema vrednost vodnog kapaciteta (PVK); tekstura parcele nije promenjena.":
        "The model has no available water capacity (AWC) for this texture class; the plot's texture was not changed.",
    "Očekuje se zapis.": "A record is expected.",
    "Analiza zemljišta nije pronađena.": "Soil analysis not found.",
    "Uređaj nije pronađen.": "Device not found.",
    "Uvoz nije pronađen.": "Import not found.",
    "API ključ nije pronađen.": "API key not found.",
    "Nedostaje ili je neispravan API ključ.": "Missing or invalid API key.",
    "Previše zahteva za ovaj API ključ ili adresu. Pokušajte ponovo za minut.":
        "Too many requests for this API key or address. Try again in a minute.",
    "Očekuje se multipart/form-data sa poljem „file” (CSV).": "multipart/form-data with a field \"file\" (CSV) is expected.",
    "Mapiranje kolona mora biti JSON objekat.": "The column mapping must be a JSON object.",
}.items():
    MESSAGES.setdefault(_sr, _en)
del _sr, _en

# ---- Photo observations and the symptom description (spec 023): messages, labels and the privacy notice.
for _sr, _en in {
    "AI opis, nije dijagnoza": "AI description, not a diagnosis",
    "Obratite se lokalnoj prognozno-izveštajnoj ili savetodavnoj službi za zaštitu bilja.":
        "Contact your local plant-protection forecasting or advisory service.",
    "Deo opisa je uklonjen jer je sadržao preparat ili dozu.":
        "Part of the description was removed because it named a product or a dose.",
    "Opis trenutno nije dostupan. Pokušajte ponovo kasnije.":
        "The description is not available right now. Please try again later.",
    "Opis je prikazan na lokalnom jeziku jer prevod nije mogao biti proveren.":
        "The description is shown in the local language because the translation could not be verified.",
    "Opis fotografije nije dostupan sa trenutnim AI podešavanjem.":
        "Photo description is not available with the current AI configuration.",
    "Slanje fotografija AI servisu nije uključeno za ovu organizaciju. Vlasnik ga može uključiti u "
    "podešavanjima organizacije.":
        "Sending photos to an AI service is not enabled for this organisation. The owner can enable it in the "
        "organisation settings.",
    "Obrada fotografija nije dostupna na serveru (nedostaje biblioteka Pillow).":
        "Photo processing is not available on the server (the Pillow library is missing).",
    "Fotografija je prevelika (najviše %s MB).": "The photo is too large (at most %s MB).",
    "Očekuje se multipart/form-data sa poljem „file” (fotografija).":
        "multipart/form-data with a field \"file\" (photo) is expected.",
    "Fotografija nije pronađena.": "Photo not found.",
    "Unos dnevnika radova nije pronađen na ovoj parceli.": "Activity log entry not found on this plot.",
    "Napomena je predugačka (najviše 2000 znakova).": "The note is too long (at most 2000 characters).",
    "Radnik može menjati i brisati samo fotografije koje je sam dodao.":
        "A worker can change and delete only the photos they added.",
    "Prostor za fotografije organizacije je popunjen (%s MB). Obrišite stare fotografije.":
        "The organisation's photo storage is full (%s MB). Delete old photos.",
    "Previše otpremanja fotografija. Pokušajte ponovo za sat vremena.": "Too many photo uploads. Try again in an hour.",
    "Za uključivanje je potrebna izričita saglasnost vlasnika sa tekstom obaveštenja (consent: true i "
    "notice_version).":
        "Enabling requires the owner's explicit consent to the notice text (consent: true and notice_version).",
    "Tekst obaveštenja je u međuvremenu promenjen; pročitajte ga ponovo i potvrdite.":
        "The notice text has changed in the meantime; read it again and confirm.",
    "Slanje fotografija AI servisu uključuje vlasnik uz saglasnost (PATCH /orgs/current/settings/photos).":
        "Sending photos to an AI service is enabled by the owner with consent (PATCH /orgs/current/settings/photos).",
    "Datum fotografije: očekuje se datum u obliku GGGG-MM-DD.": "Photo date: a date in the form YYYY-MM-DD is expected.",
    "Kada je ova opcija uključena, fotografija koju član organizacije pošalje na opis (dugme „Opiši šta se vidi”) "
    "šalje se AI servisu %s (model %s). Šalje se samo fotografija bez metapodataka (bez lokacije i vremena snimka) i "
    "fiksno uputstvo sa nazivom kulture; nikad naziv parcele, ime vlasnika ili GPS. Servis obrađuje i može čuvati "
    "podatke prema svojim uslovima korišćenja; obrada može biti van EU. Opis se čuva uz fotografiju dok se fotografija "
    "ne obriše. Isključivanjem opcije nijedna nova fotografija ne napušta server.":
        "When this option is on, a photo that a member of the organisation sends for a description (button \"Describe "
        "what is visible\") is sent to the AI service %s (model %s). Only the photo without metadata (no location or "
        "capture time) and a fixed instruction with the crop name are sent; never the plot name, the owner's name or "
        "GPS. The service processes and may keep the data under its own terms of use; processing may take place "
        "outside the EU. The description is kept with the photo until the photo is deleted. When the option is "
        "switched off, no new photo leaves the server.",
    "AI servis sa podrškom za slike trenutno nije podešen na serveru; uključivanje neće slati fotografije dok "
    "administrator ne podesi takav servis.":
        "No AI service with image support is configured on the server; enabling it sends no photos until an "
        "administrator configures such a service.",
    "Format HEIC/HEIF nije podržan na serveru; aplikacija ga pretvara u JPEG pre slanja. Pošaljite JPEG, PNG ili "
    "WebP.":
        "The HEIC/HEIF format is not supported on the server; the app converts it to JPEG before sending. Send a "
        "JPEG, PNG or WebP file.",
    "Fajl nije podržana slika. Dozvoljeni su JPEG, PNG i WebP.":
        "The file is not a supported image. JPEG, PNG and WebP are allowed.",
    "Slika ima previše piksela i nije obrađena.": "The image has too many pixels and was not processed.",
    "Slika je oštećena ili nije čitljiva.": "The image is damaged or cannot be read.",
    "abiotski stres": "abiotic stress",
    "hranljive materije": "nutrients",
    "bolest": "disease",
    "štetočina": "pest",
    "mehaničko oštećenje": "mechanical damage",
    "nepoznato": "unknown",
    "dobar snimak": "good image",
    "snimak ograničeno upotrebljiv": "image of limited use",
    "snimak neupotrebljiv": "image not usable",
    "mala verovatnoća": "low likelihood",
    "srednja verovatnoća": "medium likelihood",
    "velika verovatnoća": "high likelihood",
    "unutar parcele": "inside the plot",
    "izvan parcele": "outside the plot",
    "lokacija nepoznata": "location unknown",
    "vreme snimka": "capture time",
    "vreme snimka je u budućnosti (sat kamere?)": "capture time is in the future (camera clock?)",
    "snimak je star; proverite datum zapažanja": "the photo is old; check the observation date",
    "vreme snimka nepoznato": "capture time unknown",
}.items():
    MESSAGES.setdefault(_sr, _en)
del _sr, _en

# ---- Daily soil water balance (spec 019): sentences of smartagri/water/texts.py and the route error.
for _sr, _en in {
    "Bilans vode u zemljištu nije moguće izračunati.": "The soil water balance cannot be calculated.",
    "Nedostaje vodni kapacitet zemljišta: unesite teksturu zemljišta ili PVK (mm/m).":
        "The soil's available water capacity is missing: enter the soil texture or the AWC (mm/m).",
    "Nedostaje datum setve ili faza razvoja useva.": "The sowing date or the crop growth stage is missing.",
    "Nema sačuvanih podataka o vremenu za ovu parcelu: osvežite podatke parcele.":
        "No stored weather data for this plot: refresh the plot data.",
    "Početak bilansa mora biti pre datuma odluke.": "The start of the balance must be before the decision date.",
    "Kapilarno podizanje vode iz podzemnih voda nije uračunato (CR = 0).":
        "Capillary rise from groundwater is not included (CR = 0).",
    "Oticanje nije modelovano (RO = 0); kiša manja od 0,2 × ET0 smatra se isparenom.":
        "Runoff is not modelled (RO = 0); rain below 0.2 × ET0 is treated as evaporated.",
    "Kada koren raste, novi sloj zemljišta smatra se vlažnim do poljskog vodnog kapaciteta.":
        "When the roots grow, the newly reached soil layer is assumed to be at field capacity.",
    "Evapotranspiracija useva se ne umanjuje pri vodnom stresu (Ks), pa model može precenjivati potrošnju vode.":
        "Crop evapotranspiration is not reduced under water stress (Ks), so the model may overestimate water use.",
    "Prijavljeno stanje ili očitavanje senzora važi kao stanje na kraju tog dana.":
        "A reported status or a sensor reading is taken as the state at the end of that day.",
    "Na početku bilansa zemljište je na poljskom vodnom kapacitetu (Dr = 0).":
        "At the start of the balance the soil is at field capacity (Dr = 0).",
    "Sačuvani podaci o vremenu ne sežu do setve; bilans počinje od najstarijeg sačuvanog dana.":
        "The stored weather does not reach back to sowing; the balance starts on the oldest stored day.",
    "Datum setve nije poznat; za svaki dan koristi se prijavljena faza razvoja.":
        "The sowing date is unknown; the reported growth stage is used for every day.",
    "Efikasnost sistema nije poznata; zabeležena količina vode uzeta je kao neto količina.":
        "The system efficiency is unknown; the logged water amount is used as a net amount.",
    "Zabeležena količina vode smatra se bruto količinom; neto = bruto × efikasnost sistema.":
        "A logged water amount is treated as gross; net = gross × system efficiency.",
    "Dubina korena, PVK prema teksturi i granice stanja vode su razvojne vrednosti koje agronom još nije proverio.":
        "Root depth, AWC by texture and the soil water status limits are development values not yet reviewed by an "
        "agronomist.",
    "Koeficijent useva, dubina korena i p su iz paketa parametara kulture (FAO-56; razvojne vrednosti koje agronom još "
    "nije pregledao); faza se procenjuje prema trajanju faza iz paketa ili se uzima prijavljena faza.":
        "The crop coefficient, root depth and p come from the crop parameter pack (FAO-56; development values not yet "
        "reviewed by an agronomist); the stage is estimated from the pack's stage lengths or the reported stage is used.",
    "Parcela nema navodnjavanje; datum navodnjavanja se ne predlaže.":
        "The plot has no irrigation; no irrigation date is suggested.",
    "Od ove faze razvoja navodnjavanje se ne savetuje.": "From this growth stage on, irrigation is not advised.",
    "U sačuvanim podacima nema prognoze; datum se ne može proceniti.":
        "The stored data hold no forecast; the date cannot be estimated.",
    "Prema modelu, lako pristupačna voda neće biti potrošena u periodu prognoze.":
        "According to the model, the readily available water will not be used up within the forecast period.",
    "Prema modelu, lako pristupačna voda je već potrošena.":
        "According to the model, the readily available water is already used up.",
    "Do tog dana prognozirano je %s mm kiše; datum se može pomeriti.":
        "%s mm of rain is forecast until that day; the date may move.",
    "Efikasnost sistema nije poznata; količina se ne može preračunati u bruto.":
        "The system efficiency is unknown; the amount cannot be converted to gross.",
    "Količinu odredite merenjem ili sa savetodavcem; model još nije proveren.":
        "Determine the amount by measurement or with an adviser; the model has not been validated yet.",
    "početak bilansa": "start of the balance",
    "vaša prijava stanja vode": "your soil water report",
    "očitavanje senzora": "sensor reading",
    "navodnjavanje do poljskog vodnog kapaciteta": "irrigation to field capacity",
    "nedostaje ET0": "ET0 missing",
    "nedostaju padavine": "rainfall missing",
    "za ovu fazu nema koeficijenta useva (Kc)": "no crop coefficient (Kc) for this stage",
    "čeka se novo stanje posle praznine u podacima": "waiting for a new status after a data gap",
    "nema podataka za početak bilansa": "no data for the start of the balance",
    "model bilansa": "water balance model",
    "setva": "sowing",
    "izabrani datum": "chosen date",
    "najstariji sačuvani dan": "oldest stored day",
    "Početak bilansa: očekuje se datum u obliku GGGG-MM-DD.": "Start of the balance: a date in the form YYYY-MM-DD is expected.",
}.items():
    MESSAGES.setdefault(_sr, _en)
del _sr, _en

# ---- Water balance alert (spec 019, a spec 018 kind).
ALERT_KINDS.append({"value": "water_balance_due", "label": "Irrigation due soon (model estimate)"})
ALERT_TEXTS.update({
    "water_balance_due.title": "Irrigation due soon (model estimate): {parcel}",
    "water_balance_due.body": ("According to the water balance model, the readily available water on the plot {parcel} "
                               "will be depleted around {date} (forecast of {issued}, reliability {reliability}). This is "
                               "a model estimate, not a soil moisture measurement."),
})

# ---- spec 026: record reminders (spec 018 kinds)
ALERT_KINDS.extend([{"value": "record_sowing_missing", "label": "Reminder: sowing not recorded"},
                    {"value": "record_density_missing", "label": "Reminder: plant density not recorded"},
                    {"value": "record_harvest_missing", "label": "Reminder: harvest not recorded"}])
ALERT_TEXTS.update({
    "record_sowing_missing.title": "Sowing not recorded: {parcel}",
    "record_sowing_missing.body": "No sowing date is recorded for the plot {parcel} this season. Enter it in the plot "
                                  "data or in the activity log.",
    "record_density_missing.title": "Plant density not recorded: {parcel}",
    "record_density_missing.body": "A growth stage after emergence is reported for the plot {parcel}, but the plant "
                                   "density (plants per hectare) is not recorded. Enter the counted density.",
    "record_harvest_missing.title": "Harvest not recorded: {parcel}",
    "record_harvest_missing.body": "No harvest is recorded for the plot {parcel} sown this season. When the harvest is "
                                   "done, enter it in the activity log (yield, moisture, lot).",
})

# ---- Offline field notes and sync (spec 025): scouting location label and the 409/422 messages of api/offline_support.
ACTIVITY_FIELD_LABELS["scouting"]["location"] = "Place of the observation"
for _sr, _en in {
    "%s: očekuje se mesto {lat, lon, accuracy_m, fixed_at}.": "%s: a place {lat, lon, accuracy_m, fixed_at} is expected.",
    "%s: koordinate ili tačnost van dozvoljenog opsega.": "%s: coordinates or accuracy out of the allowed range.",
    "%s: vreme očitavanja nije u obliku ISO 8601.": "%s: the fix time is not in ISO 8601 form.",
    "Zaglavlje Idempotency-Key: očekuje se oznaka od 8 do 128 znakova (slova, cifre, - ili _).":
        "Idempotency-Key header: a key of 8 to 128 characters (letters, digits, - or _) is expected.",
    "Ključ Idempotency-Key je već upotrebljen za drugačiji zahtev.":
        "The Idempotency-Key was already used for a different request.",
    "Zahtev sa istim ključem Idempotency-Key se još obrađuje; pokušajte ponovo za nekoliko sekundi.":
        "A request with the same Idempotency-Key is still being processed; try again in a few seconds.",
    "Zapis je u međuvremenu izmenjen na serveru; izaberite koju verziju zadržavate.":
        "The entry was changed on the server in the meantime; choose which version to keep.",
    "Zapis je u međuvremenu obrisan na serveru.": "The entry was deleted on the server in the meantime.",
    "Zaglavlje X-Base-Updated-At: očekuje se vreme poslednje izmene zapisa (ISO 8601).":
        "X-Base-Updated-At header: the time of the entry's last change (ISO 8601) is expected.",
}.items():
    MESSAGES.setdefault(_sr, _en)
del _sr, _en

# ---- Advisor workspace (spec 024): messages, review labels, audit actions and CSV headers (smartagri/advisor.py).
for _sr, _en in {
    "Nepoznato ovlašćenje: %s.": "Unknown permission: %s.",
    "Ovlašćenje mora biti da ili ne (true/false).": "A permission must be yes or no (true/false).",
    "Parcele veze: očekuje se lista oznaka parcela ili null (sve parcele).":
        "Plots of the link: a list of plot ids or null (all plots) is expected.",
    "Pregled parcela je osnovni deo veze i ne može se isključiti; vezu možete opozvati.":
        "Viewing plots is the basic part of a link and cannot be switched off; you can revoke the link.",
    "Za beleške savetnika potreban je i pregled AI saveta.": "Adviser notes also require viewing AI advice.",
    "Datum isteka: očekuje se datum u obliku GGGG-MM-DD.": "Expiry date: a date in the form YYYY-MM-DD is expected.",
    "Datum isteka mora biti posle današnjeg dana.": "The expiry date must be after today.",
    "Veza može trajati najviše %s dana.": "A link can last at most %s days.",
    "Savetnik u pilotu ne sme da upisuje doze ni sredstva za zaštitu bilja. Uklonite dozu ili naziv sredstva i "
    "pošaljite ponovo.":
        "In the pilot an adviser may not write rates or plant protection products. Remove the rate or the product "
        "name and send again.",
    "Tekst beleške je obavezan.": "The note text is required.",
    "Tekst je predugačak (najviše %s znakova).": "The text is too long (at most %s characters).",
    "Naslov preporuke je obavezan.": "The recommendation title is required.",
    "Naslov je predugačak (najviše %s znakova).": "The title is too long (at most %s characters).",
    "Nepoznata vrsta pregleda. Dozvoljeno: reviewed, note, correction, flagged.":
        "Unknown kind of review. Allowed: reviewed, note, correction, flagged.",
    "Ova stranica je dostupna samo savetodavnim organizacijama.": "This page is available to advisory organisations only.",
    "Ova radnja je dostupna samo gazdinstvima.": "This action is available to farms only.",
    "Gazdinstvo nije pronađeno.": "Farm not found.",
    "Gazdinstvo nije dalo ovo ovlašćenje vašoj organizaciji.": "The farm has not given your organisation this permission.",
    "Veza sa savetnikom nije pronađena.": "Adviser link not found.",
    "Između ove dve organizacije već postoji otvorena veza.": "An open link between these two organisations already exists.",
    "Ova radnja nije moguća u trenutnom stanju veze.": "This action is not possible in the link's current state.",
    "Organizacija sa ovom oznakom ili e-adresom nije pronađena.": "No organisation with this id or e-mail address was found.",
    "Organizacija ne može da se poveže sama sa sobom.": "An organisation cannot link to itself.",
    "Preporuka nije pronađena.": "Recommendation not found.",
    "Nijedno izabrano gazdinstvo nije dalo ovlašćenje za preporuke.":
        "None of the selected farms has given permission for recommendations.",
    "Previše zahteva. Pokušajte ponovo kasnije.": "Too many requests. Please try again later.",
    "Datum: očekuje se datum u obliku GGGG-MM-DD.": "Date: a date in the form YYYY-MM-DD is expected.",
    "Savetnik je pregledao ovaj savet": "An adviser has reviewed this advice",
    "Beleška savetnika": "Adviser's note",
    "Ispravka savetnika": "Adviser's correction",
    "Savetnik je označio ovaj savet za proveru": "An adviser has flagged this advice for checking",
    "zahtev za vezu": "link request",
    "veza prihvaćena": "link accepted",
    "zahtev odbijen": "request declined",
    "ovlašćenja promenjena": "permissions changed",
    "veza opozvana": "link revoked",
    "veza istekla": "link expired",
    "savetnik je prekinuo vezu": "adviser ended the link",
    "pregled portfolija": "portfolio viewed",
    "pregled parcela": "plots viewed",
    "pregled parcele": "plot viewed",
    "pregled dnevnika radova": "activity log viewed",
    "pregled AI saveta": "AI advice viewed",
    "pregled troškova": "costs viewed",
    "pregled liste za pregled": "review queue viewed",
    "savet pregledan": "advice reviewed",
    "beleška uz savet": "note on advice",
    "ispravka saveta": "correction of advice",
    "savet označen za proveru": "advice flagged for checking",
    "preporuka poslata": "recommendation sent",
    "Vreme": "Time",
    "Savetodavna organizacija": "Advisory organisation",
    "Gazdinstvo": "Farm",
    "Korisnik": "User",
    "Radnja": "Action",
    "Vrsta objekta": "Object type",
    "Objekat": "Object",
    "Parcela": "Plot",
}.items():
    MESSAGES.setdefault(_sr, _en)
del _sr, _en

# Spec 030 (atlas and symptom key): API messages of atlas/texts.MSG.
for _sr, _en in {
    "Unos atlasa nije pronađen.": "Atlas entry not found.",
    "Slika nije pronađena.": "Image not found.",
    "Za ovu radnju potrebno je ovlašćenje urednika atlasa.": "This action needs the atlas editor permission.",
    "Za ovu radnju potrebno je ovlašćenje recenzenta atlasa.": "This action needs the atlas reviewer permission.",
    "Unos ne može objaviti osoba koja ga je poslednja menjala (pravilo dve osobe).":
        "The entry cannot be published by the person who last changed it (two-person rule).",
    "Unos atlasa nije ispravan.": "The atlas entry is not valid.",
    "Uvoz nije ispravan: očekuje se JSON niz unosa ili CSV sa zaglavljem.":
        "The import is not valid: a JSON array of entries or a CSV file with a header is expected.",
    "Uvoz je prevelik.": "The import is too large.",
    "Uvoz ima previše redova.": "The import has too many rows.",
    "Izbor simptoma nije ispravan.": "The symptom selection is not valid.",
    "Nepoznata kultura.": "Unknown crop.",
    "Izaberite bar jedan simptom.": "Select at least one symptom.",
    "Licenca slike nije dozvoljena ili nedostaju podaci o autoru i izvoru.":
        "The image licence is not allowed or the author and source details are missing.",
    "Slika se može preuzeti samo sa dozvoljenih adresa (https).": "An image can be fetched only from allowed addresses (https).",
    "Sliku nije moguće preuzeti sa izvora.": "The image could not be fetched from the source.",
    "Ključ simptoma trenutno nije dostupan.": "The symptom key is not available at the moment.",
    "Unos nije u stanju koje dozvoljava ovu radnju.": "The entry is not in a state that allows this action.",
    "Obrada slika nije dostupna na ovom serveru.": "Image processing is not available on this server.",
}.items():
    MESSAGES.setdefault(_sr, _en)
del _sr, _en

# Spec 027: farms, field crops and per-field access (messages raised as finished default-locale text).
MESSAGES.update({
    "Za ovu parcelu imate samo pravo čitanja.": "You have read-only access to this parcel.",
    "Vlasnik i agronom imaju pristup svim parcelama.": "Owners and agronomists have access to all parcels.",
    "Pristup parcelama: dozvoljeno all ili listed.": "Parcel access: allowed values are all or listed.",
    "Pravo na parceli: dozvoljeno read ili edit.": "Parcel right: allowed values are read or edit.",
    "Očekuje se zapis {field_scope, grants}.": "Expected a record {field_scope, grants}.",
    "Gazdinstvo nije pronađeno.": "Farm not found.",
    "Naziv gazdinstva je obavezan (najviše 100 znakova).": "The farm name is required (at most 100 characters).",
    "Gazdinstvo sa tim nazivom već postoji.": "A farm with this name already exists.",
    "Gazdinstvo ima parcele; premestite ih pre brisanja.": "The farm has parcels; move them before deleting it.",
    "Podrazumevano gazdinstvo ne može da se obriše; prvo izaberite drugo podrazumevano gazdinstvo.":
        "The default farm cannot be deleted; first choose another default farm.",
    "Tačno jedno gazdinstvo mora biti podrazumevano; izaberite drugo gazdinstvo kao podrazumevano.":
        "Exactly one farm must be the default; choose another farm as the default.",
    "Opis gazdinstva: najviše 1000 znakova.": "Farm description: at most 1000 characters.",
    "Premeštanje parcele u drugo gazdinstvo može samo vlasnik ili agronom.":
        "Only an owner or an agronomist can move a parcel to another farm.",
    "Opis polja: očekuje se zapis.": "Field description: a record is expected.",
    "Opis polja, %s: nepoznata vrednost %s.": "Field description, %s: unknown value %s.",
    "Opis polja, %s: najviše %d znakova.": "Field description, %s: at most %d characters.",
    "Nepoznata kultura: %s.": "Unknown crop: %s.",
    "Zapis o usevu nije pronađen.": "Crop record not found.",
    "Sezona mora biti godina (npr. 2026).": "The season must be a year (e.g. 2026).",
    "Veza sa dnevnikom radova: zapis nije pronađen.": "Link to the activity log: entry not found.",
    "Datum mora biti u obliku GGGG-MM-DD.": "The date must have the form YYYY-MM-DD.",
    "Datum početka (setve ili sadnje) je obavezan.": "The start date (sowing or planting) is required.",
    "Datum završetka ne može biti pre datuma početka.": "The end date cannot be before the start date.",
    "Period se preklapa sa drugim glavnim usevom na ovoj parceli (%s – %s).":
        "The period overlaps another main crop on this parcel (%s – %s).",
    "Za ovu kulturu se ne upisuje grupa zrenja.": "No maturity group is recorded for this crop.",
    "Grupa zrenja (FAO): očekuje se ceo broj između 100 i 900.": "Maturity group (FAO): a whole number between 100 and 900 is expected.",
    "Grupa zrenja soje: dozvoljeno %s.": "Soybean maturity group: allowed %s.",
    "Planirana norma setve: očekuje se broj.": "Planned seeding rate: a number is expected.",
    "Planirana norma setve: jedinica za ovu kulturu je %s.": "Planned seeding rate: the unit for this crop is %s.",
    "Planirana norma setve: vrednost izvan dozvoljenog opsega.": "Planned seeding rate: value outside the allowed range.",
    "Međuredni razmak (cm): vrednost između %s i %s.": "Row spacing (cm): a value between %s and %s.",
    "Veze sa dnevnikom radova: očekuje se lista.": "Links to the activity log: a list is expected.",
    "Očekuje se zapis o usevu.": "A crop record is expected.",
    "%s: očekuje se tekst.": "%s: text is expected.",
    "%s: najviše %d znakova.": "%s: at most %d characters.",
    "%s: očekuje se lista oznaka.": "%s: a list of tags is expected.",
    "%s: oznaka je predugačka.": "%s: a tag is too long.",
    "%s: previše oznaka.": "%s: too many tags.",
    "%s: nepoznata vrednost %s.": "%s: unknown value %s.",
    "Namena": "Purpose", "Uloga useva": "Crop role", "Status": "Status", "Sorta ili hibrid": "Variety or hybrid",
    "Naziv kulture": "Crop name", "Napomena": "Notes", "Osobine semena": "Seed traits",
    "Opis polja, osobine semena": "Field description, seed traits",
})

# Spec 028: structured scouting surveys (messages raised or shown as finished default-locale text).
MESSAGES.update({
    "Pregled useva nije pronađen.": "Scouting survey not found.",
    "Radnik može menjati samo svoje preglede useva dok ih agronom ne pregleda.": "A worker can change only their own scouting surveys until the agronomist has reviewed them.",
    "Radnik može brisati samo svoje nacrte pregleda.": "A worker can delete only their own draft surveys.",
    "Pregled je već označen kao pregledan; menja ga samo vlasnik ili agronom.": "The survey has already been reviewed; only the owner or the agronomist can change it.",
    "Pregledati se može samo podnet pregled useva.": "Only a submitted survey can be reviewed.",
    "Unos atlasa nije pronađen ili nije objavljen.": "Atlas entry not found or not published.",
    "Veza sa atlasom nije uključena; upišite naziv zapažanja.": "The atlas link is not enabled; type a name for the observation.",
    "Kultura se ne slaže sa izabranim zapisom o usevu.": "The crop does not match the selected crop record.",
    "Vreme pregleda: očekuje se datum (GGGG-MM-DD) ili datum i vreme (ISO 8601).": "Survey time: a date (YYYY-MM-DD) or a date and time (ISO 8601) is expected.",
    "Način brojanja %s nije predviđen za ovu kulturu.": "Counting method %s is not offered for this crop.",
    "Napomena uz pregled: najviše %d znakova.": "Survey note: at most %d characters.",
    "Izvoz je prevelik; suzite period.": "The export is too large; narrow the period.",
    "Previše izvoza fotografija. Pokušajte ponovo za sat vremena.": "Too many photo exports. Try again in an hour.",
    "Filter datuma: očekuje se datum u obliku GGGG-MM-DD.": "Date filter: a date in the form YYYY-MM-DD is expected.",
    "Komentar: najviše 2000 znakova.": "Comment: at most 2000 characters.",
    "Oznaka klijenta (client_key): 8 do 128 znakova.": "Client key (client_key): 8 to 128 characters.",
    "Napomena uz pregled: očekuje se tekst.": "Survey note: text is expected.",
    "Gustina sklopa: očekuje se način brojanja i uzorci.": "Plant population: a counting method and samples are expected.",
    "Unesite bar jedan uzorak brojanja.": "Enter at least one counting sample.",
    "Glavna faza %d — %s": "Principal stage %d — %s",
    "Datum pregleda je van perioda useva.": "The survey date is outside the crop period.",
    "Malo uzoraka: procena je nesigurna.": "Few samples: the estimate is uncertain.",
    "Uzorak %d: izvan parcele, %s m.": "Sample %d: outside the parcel, %s m.",
    "Izbrojana gustina je izvan opsega koji savetnik koristi; ostaje samo u pregledu.": "The counted population is outside the range the advisor uses; it stays in the survey only.",
    "Ovaj unos atlasa nije naveden za ovu kulturu.": "This atlas entry is not listed for this crop.",
    "Unos atlasa više nije objavljen.": "The atlas entry is no longer published.",
    "podnet": "submitted",
    "prebrojano u polju, broj uzoraka: %d": "counted in the field, number of samples: %d",
    "pregled useva": "scouting survey",
    "Faza razvoja: očekuje se skala i oznaka faze.": "Growth stage: a scale and a stage code are expected.",
    "Faza razvoja nije sa skale ove kulture.": "The growth stage is not from the crop's scale.",
    "%s: vrednost između 0 i 100.": "%s: a value between 0 and 100.",
    "Zapažanje: očekuje se zapis.": "Observation: a record is expected.",
    "Zapažanje: nepoznato polje %s.": "Observation: unknown field %s.",
    "Zapažanje: nepoznata kategorija %s.": "Observation: unknown category %s.",
    "Zapažanje: podvrsta %s nije dozvoljena za ovu kategoriju.": "Observation: subtype %s is not allowed for this category.",
    "Zapažanje: neispravan unos atlasa.": "Observation: invalid atlas entry.",
    "Naziv zapažanja": "Observation name",
    "Zapažanje: izaberite unos atlasa ili upišite naziv.": "Observation: choose an atlas entry or type a name.",
    "Zapažanje: delovi biljke se navode kao lista.": "Observation: plant parts are given as a list.",
    "Zapažanje: deo biljke %s nije na listi za ovu kulturu.": "Observation: plant part %s is not on the list for this crop.",
    "Zapažanje: razvojni stadijum se upisuje samo za štetočine (nepoznata vrednost %s).": "Observation: a life stage is recorded only for pests (unknown value %s).",
    "Zapažanje: nepoznat intenzitet %s.": "Observation: unknown severity %s.",
    "Ocena 0-100": "Score 0-100",
    "Učestalost (% biljaka)": "Incidence (% of plants)",
    "Udeo površine (%)": "Field share (%)",
    "Zapažanje: brojnost se navodi kao vrednost i jedinica.": "Observation: a count is given as a value and a unit.",
    "Zapažanje: brojnost mora biti broj veći ili jednak nuli.": "Observation: the count must be a number of at least zero.",
    "Zapažanje: nepoznata jedinica brojnosti %s.": "Observation: unknown count unit %s.",
    "Zapažanje: fotografije se navode kao lista oznaka.": "Observation: photos are given as a list of ids.",
    "Napomena uz zapažanje": "Observation note",
    "Zapažanja se navode kao lista.": "Observations are given as a list.",
    "Previše zapažanja u jednom pregledu (najviše %d).": "Too many observations in one survey (at most %d).",
    "Zapažanje: oznake zapažanja moraju biti jedinstvene.": "Observation: observation ids must be unique.",
    "Lokacija: očekuju se geografska širina i dužina.": "Location: latitude and longitude are expected.",
    "Lokacija: koordinate su izvan dozvoljenog opsega.": "Location: the coordinates are out of range.",
    "Lokacija: tačnost (m) mora biti broj veći ili jednak nuli.": "Location: the accuracy (m) must be a number of at least zero.",
    "Površina uzorka mora biti veća od nule.": "The sample area must be greater than zero.",
    "Nepoznat način brojanja biljaka.": "Unknown plant counting method.",
    "Previše uzoraka (najviše %d).": "Too many samples (at most %d).",
    "Unesite međuredni razmak.": "Enter the row spacing.",
    "Uzorak: očekuje se zapis.": "Sample: a record is expected.",
    "Broj biljaka u uzorku: ceo broj od 0 do %d.": "Plants in the sample: a whole number from 0 to %d.",
    "Dužina reda (m): vrednost između %s i %s.": "Row length (m): a value between %s and %s.",
    "Površina rama (m²): vrednost između %s i %s.": "Frame area (m²): a value between %s and %s.",
    "Pregled useva nije pronađen na ovoj parceli.": "Scouting survey not found on this parcel.",
})

# Spec 029: season survey reminder and messages raised as finished default-locale text.
ALERT_KINDS.append({"value": "record_season_survey_missing", "label": "Reminder: season survey not submitted"})
ALERT_TEXTS.update({
    "record_season_survey_missing.title": "Season survey not submitted: {parcel}",
    "record_season_survey_missing.body": "The crop on the plot {parcel} has ended its season and has no submitted "
                                         "season survey. The survey is prefilled from the activity log; review it and "
                                         "submit it by {date}.",
})
MESSAGES.update({
    "Izveštaj je predat i zaključan; otvorite ga ponovo za izmene.":
        "The survey is submitted and locked; reopen it to make changes.",
    "Izveštaj nije predat.": "The survey has not been submitted.",
    "Izveštaj još nije sačuvan.": "The survey has not been saved yet.",
    "Izveštaj ne može da se preda bez berbe: upišite datum berbe ili označite da usev nije požnjeven i navedite razlog.":
        "The survey cannot be submitted without a harvest: enter the harvest date or mark the crop as not harvested "
        "and give a reason.",
    "Razlog (usev nije požnjeven): upišite kratak opis, najviše 500 znakova.":
        "Reason (crop not harvested): enter a short description, at most 500 characters.",
    "Očekuje se zapis {sections, not_harvested}.": "Expected a record {sections, not_harvested}.",
    "Sezona: ovaj usev nema sezonu %s.": "Season: this crop has no season %s.",
    "Previše izvoza u kratkom roku; pokušajte ponovo kasnije.": "Too many exports in a short time; try again later.",
    "Izvoz je prevelik; suzite izbor (sezona, gazdinstvo, kultura).":
        "The export is too large; narrow the selection (season, farm, crop).",
    "Imena osoba u izvozu može da uključi samo vlasnik organizacije.":
        "Only the organisation owner can include people's names in the export.",
    "Saglasnost: očekuje se {consent: true, scope, survey_ids?, notice_version}.":
        "Consent: expected {consent: true, scope, survey_ids?, notice_version}.",
    "Tekst obaveštenja o saglasnosti je u međuvremenu promenjen; pročitajte ga ponovo i potvrdite.":
        "The consent notice has changed in the meantime; read it again and confirm.",
    "Obim saglasnosti: dozvoljeno all_from_now ili selected.": "Consent scope: allowed values are all_from_now or selected.",
    "Za saglasnost na izabrane izveštaje navedite bar jedan izveštaj ove organizacije.":
        "For consent to selected surveys, list at least one survey of this organisation.",
    "Saglasnost nije data.": "Consent has not been given.",
    "%s: datum mora biti u obliku GGGG-MM-DD.": "%s: the date must have the form YYYY-MM-DD.",
    "%s: očekuje se broj.": "%s: a number is expected.",
    "%s: očekuje se ceo broj.": "%s: a whole number is expected.",
    "%s: vrednost izvan fizički mogućeg opsega (%s–%s).": "%s: value outside the physically possible range (%s–%s).",
    "%s: polje se ne menja.": "%s: this field cannot be changed.",
    "%s: očekuje se zapis.": "%s: a record is expected.",
    "%s: nepoznato polje %s.": "%s: unknown field %s.",
    "%s: očekuje se lista.": "%s: a list is expected.",
    "%s: previše redova.": "%s: too many rows.",
    "%s, red %d": "%s, row %d",
    "Očekuju se odeljci izveštaja.": "Survey sections are expected.",
    "Nepoznat odeljak izveštaja: %s.": "Unknown survey section: %s.",
    "Izabrana setva ne postoji u listi setvi.": "The selected sowing is not in the list of sowings.",
})

# Spec 032 (agronomy analyses and reference datasets): API messages of analyses/texts.MSG and the service.
MESSAGES.update({
    "Analiza nije pronađena.": "Analysis not found.",
    "Vrsta analize nije ispravna (profit ili alternatives).": "The analysis kind is not valid (profit or alternatives).",
    "Analiza: očekuje se zapis sa pretpostavkama.": "Analysis: a record with assumptions is expected.",
    "%s: unesite nizak, očekivan i visok nivo (nizak ≤ očekivan ≤ visok).":
        "%s: enter a low, expected and high level (low ≤ expected ≤ high).",
    "Najviše %d varijanti u jednoj analizi.": "At most %d alternatives in one analysis.",
    "Unesite bar jednu varijantu.": "Enter at least one alternative.",
    "Osnovna varijanta mora biti jedna od unetih.": "The baseline must be one of the entered alternatives.",
    "%s: tekst ne sme da označava varijantu kao najbolju ili preporučenu.":
        "%s: the text must not mark an alternative as the best or recommended one.",
    "%s: tekst je predugačak ili prazan.": "%s: the text is too long or empty.",
    "Nepoznata promenljiva varijante: %s.": "Unknown variable of the alternative: %s.",
    "Nepoznata jedinica za %s: %s.": "Unknown unit for %s: %s.",
    "Površina (ha) mora biti veća od nule.": "Area (ha) must be greater than zero.",
    "Sezona mora biti godina (npr. 2027).": "Season must be a year (e.g. 2027).",
    "Valuta organizacije nije podešena (Troškovi i marža).": "The organisation currency is not set (Costs and margin).",
    "Dostignut je najveći broj sačuvanih analiza.": "The maximum number of saved analyses has been reached.",
    "Referentni podaci nisu pronađeni ili nisu objavljeni.": "Reference data not found or not published.",
    "Tačka referentnih podataka nije pronađena: %s.": "Reference data point not found: %s.",
    "Skup referentnih podataka nije pronađen.": "Reference dataset not found.",
    "Za ovu radnju potrebno je ovlašćenje urednika referentnih podataka.":
        "This action needs the reference-data editor permission.",
    "Skup ne može objaviti osoba koja ga je poslednja menjala (pravilo dve osobe).":
        "The dataset cannot be published by the person who last changed it (two-person rule).",
    "Skup nije u stanju koje dozvoljava ovu radnju.": "The dataset is not in a state that allows this action.",
    "Uvoz nije ispravan: očekuje se JSON (skup ili niz skupova) ili CSV sa zaglavljem.":
        "The import is not valid: JSON (a dataset or an array of datasets) or a CSV file with a header is expected.",
    "Skup referentnih podataka nije ispravan.": "The reference dataset is not valid.",
    "PDF trenutno nije dostupan na ovom serveru.": "PDF is not available on this server at the moment.",
    "%s: vrednost ne može biti negativna.": "%s: the value cannot be negative.",
    "Grupa troškova": "Cost group",
    "Trošak po ha": "Cost per ha",
    "Naziv varijante": "Alternative name",
    "prinos t/ha": "yield t/ha",
    "razlika troškova po ha": "cost difference per ha",
    "Površina (ha)": "Area (ha)",
    "Naziv analize": "Analysis title",
    "Cena po toni": "Price per tonne",
    "Prinos t/ha": "Yield t/ha",
})

# ---------------------------------------------------------------- specs 034/035: risk models and weather stations
ALERT_KINDS.extend([{"value": "pest_disease_risk", "label": "Disease risk according to a model"},
                    {"value": "pest_phenology", "label": "Pest development according to a model (estimate)"},
                    {"value": "station_stale", "label": "Weather station without data"}])
ALERT_TEXTS.update({
    "pest_disease_risk.title": "Risk according to model {model}: {parcel}",
    "pest_disease_risk.body": ("According to model {model} ({citation}) infection conditions are met for {date} on "
                               "parcel {parcel} (forecast of {issued}). This is the output of a published model that "
                               "has not been validated in Bosnia and Herzegovina, not a diagnosis. For protection "
                               "measures, contact the plant protection service."),
    "pest_phenology.title": "Pest development estimate according to model {model}: {parcel}",
    "pest_phenology.body": ("According to model {model} ({citation}) the estimated event \u201c{event}\u201d falls around "
                            "{date} on parcel {parcel}. Estimate; depends on the accuracy of the first-catch date. For "
                            "protection measures, contact the plant protection service."),
    "station_stale.title": "Weather station without data: {station}",
    "station_stale.body": ("Station {station} has no new data or has a sensor with unchanged values (last data {last} "
                           "UTC, {age} h ago; sensors: {sensors}). Check power, connection and sensors."),
    "event.egg_hatch_avg": "average egg hatch",
    "event.generation_complete": "end of one generation",
    "class.high": "high", "class.extreme": "extreme", "class.marginal": "marginal",
})

# Specs 034/035: messages of weather stations, the weather ingest and the risk models (finished default-locale text).
for _sr, _en in {
    "Čuvanje pristupnih podataka nije podešeno na serveru.": "Storing access credentials is not configured on this server.",
    "Dodela stanice nije pronađena.": "Station assignment not found.",
    "Istorija bakteriozne plamenjače: dozvoljeno %s.": "Fire-blight history: allowed values are %s.",
    "Ključ nema pravo na parcele ove stanice.": "The key has no right to the parcels of this station.",
    "Koordinate stanice nisu ispravne.": "The station coordinates are not valid.",
    "Kraj cvetanja ne može biti pre početka.": "The end of bloom cannot be before its start.",
    "Mapiranje kanala nije ispravno.": "The channel mapping is not valid.",
    "Model rizika nije pronađen.": "Risk model not found.",
    "Model sa neprepisanim parametrima ne može se potvrditi.": "A model with untranscribed parameters cannot be signed off.",
    "Modeli rizika nisu uključeni za ovu organizaciju.": "Risk models are not enabled for this organisation.",
    "Naziv stanice je obavezan.": "The station name is required.",
    "Nedostaju pristupni podaci: %s.": "Access credentials are missing: %s.",
    "Nepoznat način prijema podataka.": "Unknown data delivery method.",
    "Nepoznat proizvođač stanice.": "Unknown station vendor.",
    "Nepoznata promenljiva senzora.": "Unknown sensor variable.",
    "Objavljivanje stanice može da uključi samo vlasnik ili agronom.": "Only an owner or an agronomist can publish a station.",
    "Opseg ključa: dozvoljeno %s.": "Key scope: allowed values are %s.",
    "Oznaka stanice sme imati slova, cifre, tačku, crticu i dvotačku (najviše 64).":
        "The station code may contain letters, digits, dot, hyphen and colon (at most 64).",
    "Polje %s je predugačko (najviše %s znakova).": "The field %s is too long (at most %s characters).",
    "Previše ponovnih proračuna. Pokušajte ponovo kasnije.": "Too many recomputations. Try again later.",
    "Senzori: očekuje se lista (najviše 50).": "Sensors: a list is expected (at most 50).",
    "Stanica nije pronađena.": "Station not found.",
    "Stanica sa tom oznakom već postoji.": "A station with this code already exists.",
    "Status stanice: dozvoljeno active ili inactive.": "Station status: allowed values are active or inactive.",
    "Telo zahteva mora imati listu „observations”.": "The request body must contain a list “observations”.",
    "Visina ili dubina senzora mora biti broj.": "The sensor height or depth must be a number.",
    "Za ovog proizvođača nema adaptera; koristite API ključ ili CSV.":
        "There is no adapter for this vendor; use an API key or CSV.",
    "Za ovu radnju potrebno je ovlašćenje recenzenta modela rizika.": "This action needs the risk-model reviewer permission.",
    "Nepoznat meteorološki model: %s.": "Unknown weather model: %s.",
    "Stavka nije JSON objekat.": "The item is not a JSON object.",
    "Nepoznata ili neispravna oznaka stanice.": "Unknown or invalid station code.",
    "Vreme merenja nije ispravno (GGGG-MM-DDTHH:MM sa zonom).": "The observation time is not valid (YYYY-MM-DDTHH:MM with a zone).",
    "Vreme merenja nema vremensku zonu, a stanica nema zonu loger-a.":
        "The observation time has no time zone and the station has no logger time zone.",
    "Vreme merenja je dvosmisleno ili ne postoji zbog letnjeg računanja vremena.":
        "The observation time is ambiguous or does not exist because of daylight saving time.",
    "Vreme merenja je u budućnosti.": "The observation time is in the future.",
    "Interval merenja mora biti ceo broj minuta od 1 do 1440.": "The interval must be a whole number of minutes from 1 to 1440.",
    "Vrednosti moraju biti brojevi poznatih promenljivih.": "Values must be numbers of known variables.",
    "Stavka nema nijednu vrednost.": "The item has no value.",
    "Telo zahteva mora biti JSON objekat.": "The request body must be a JSON object.",
    "Datum mora biti u obliku GGGG-MM-DD.": "The date must be in the form YYYY-MM-DD.",
    "Nepoznato polje: %s.": "Unknown field: %s.",
    "Previše merenja u jednom zahtevu (najviše %s).": "Too many observations in one request (at most %s).",
}.items():
    MESSAGES.setdefault(_sr, _en)
del _sr, _en

# Spec 059 (any crop): custom crops ("Druga kultura").
MESSAGES.update({
    "Kultura nije pronađena.": "Crop not found.",
    "Arhivirana kultura se ne menja.": "An archived crop cannot be changed.",
    "Kultura „%s” već postoji u organizaciji.": "The crop \"%s\" already exists in the organisation.",
    "Korisnička kultura nije pronađena u ovoj organizaciji.": "The custom crop was not found in this organisation.",
    "Naziv kulture je obavezan.": "The crop name is required.",
    "Naziv kulture može imati najviše %d znakova.": "The crop name may have at most %d characters.",
    "Izaberite analognu kulturu iz FAO-56 ili unesite sopstvene parametre.":
        "Choose an FAO-56 analogue crop or enter your own parameters.",
    "Napomena o izvoru može imati najviše %d znakova.": "The source note may have at most %d characters.",
    "Analogna kultura nije pronađena među kulturama sa FAO-56 parametrima.":
        "The analogue crop was not found among the crops with FAO-56 parameters.",
    "Za sopstvene parametre obavezna je napomena o izvoru (najmanje %d znakova): odakle su koeficijent useva, dubina "
    "korena i p.": "Own parameters need a source note (at least %d characters): where the crop coefficient, root "
                   "depth and p come from.",
    "%s je obavezan broj.": "%s is a required number.",
    "%s mora biti između %s i %s.": "%s must be between %s and %s.",
    "Najmanja dubina korena ne može biti veća od najveće.": "The minimum root depth cannot exceed the maximum.",
    "Nepoznat tip razvoja kulture.": "Unknown development type of the crop.",
})

# ---------------------------------------------------------------- specs 044/045: tasks and inventory (spec 018 kinds)
ALERT_KINDS.extend([{"value": "task_assigned", "label": "Task assigned"},
                    {"value": "task_done", "label": "Task completed"},
                    {"value": "stock_low", "label": "Stock below threshold"},
                    {"value": "stock_expiring", "label": "Lot expiring or expired"}])
ALERT_TEXTS.update({
    "task_assigned.title": "New task: {task}",
    "task_assigned.body": "{by} assigned you the task “{task}” ({kind}) on parcel {parcel}, due {date}.",
    "task_done.title": "Task completed: {task}",
    "task_done.body": "{by} completed the task “{task}” on parcel {parcel}; the entry was added to the activity log. Review and verify it.",
    "stock_low.title": "Stock below threshold: {product}",
    "stock_low.body": "Stock of {product} is {quantity} {unit}, below the threshold of {threshold} {unit}. Information from the inventory records.",
    "stock_expiring.title": "Lot expiring: {product}",
    "stock_expiring.body": "Lot {lot} of {product} ({quantity} {unit} in stock) expires on {date}. Information from the inventory records.",
})

# Specs 042/044/045: messages of crop rotation, tasks and inventory (finished default-locale text -> English).
for _sr, _en in {
    "%s: najviše 6 decimala.": "%s: at most 6 decimals.",
    "Cene unose vlasnik i agronom.": "Prices are entered by the owner and the agronomist.",
    "Detalji rada: očekuje se zapis (objekat).": "Work details: an object is expected.",
    "Drugi nazivi: očekuje se lista od najviše 20 naziva.": "Other names: a list of at most 20 names is expected.",
    "Država registra: dvoslovna oznaka (npr. BA, RS).": "Registry country: a two-letter code (e.g. BA, RS).",
    "Jedinica %s ne može se pretvoriti u %s (masa i zapremina se ne pretvaraju).":
        "Unit %s cannot be converted to %s (mass and volume are never converted).",
    "Jedinica zalihe se ne menja kada postoje kretanja; arhivirajte proizvod i unesite novi.":
        "The stock unit cannot change once movements exist; archive the product and add a new one.",
    "Kontrolna lista: najviše %d stavki.": "Checklist: at most %d items.",
    "Kontrolna lista: očekuje se lista oznaka stavki.": "Checklist: a list of item ids is expected.",
    "Kontrolna lista: očekuje se tekst stavke.": "Checklist: item text is expected.",
    "Korekcija: količina ne može biti nula.": "Adjustment: the quantity cannot be zero.",
    "Kretanje je već poništeno.": "The movement is already voided.",
    "Kretanje nije pronađeno.": "Movement not found.",
    "Lot %s već postoji sa rokom %s.": "Lot %s already exists with expiry date %s.",
    "Lot ne pripada ovom proizvodu.": "The lot does not belong to this product.",
    "Lot nije pronađen.": "Lot not found.",
    "Menja se samo potrošnja označena za proveru; pogrešno kretanje poništite i unesite novo.":
        "Only a use marked for review can be changed; void a wrong movement and enter a new one.",
    "Nepoznata kategorija: %s. Dozvoljeno: %s.": "Unknown category: %s. Allowed: %s.",
    "Nepoznata vrsta kretanja: %s.": "Unknown kind of movement: %s.",
    "Očekuje se {item_id, done}.": "Expected {item_id, done}.",
    "Parcela zadatka se ne menja; otkažite zadatak i napravite novi.":
        "The parcel of a task cannot change; cancel the task and create a new one.",
    "Potrošnja iz dnevnika radova menja se izmenom ili brisanjem unosa u dnevniku.":
        "Use from the activity log is changed by editing or deleting the log entry.",
    "Premeštanje: izaberite dva različita skladišta.": "Transfer: choose two different storage locations.",
    "Proizvod je arhiviran.": "The product is archived.",
    "Proizvod nije pronađen.": "Product not found.",
    "Proizvod sa ovim nazivom već postoji u ovoj kategoriji.": "A product with this name already exists in this category.",
    "Skladište nije pronađeno.": "Storage location not found.",
    "Skladište sa ovim nazivom već postoji.": "A storage location with this name already exists.",
    "Stavka cenovnika nije pronađena.": "Price-list item not found.",
    "Unos dnevnika radova je izmenjen.": "The activity-log entry was changed.",
    "Unos dnevnika radova je obrisan.": "The activity-log entry was deleted.",
    "Upozorenje pre isteka: ceo broj dana između 0 i 365.": "Warn before expiry: a whole number of days between 0 and 365.",
    "Utrošeni proizvod: očekuje se {product_id, quantity, unit}.": "Used product: {product_id, quantity, unit} is expected.",
    "Utrošeni proizvodi: očekuje se lista (najviše 20).": "Used products: a list is expected (at most 20).",
    "Vrsta kretanja: purchase, adjustment ili use (premeštanje ima svoju putanju).":
        "Kind of movement: purchase, adjustment or use (transfers have their own route).",
    "Vrsta rada je određena zadatkom.": "The kind of work is set by the task.",
    "Površina parcele nije poznata; količinu unesite ručno.": "The parcel area is not known; enter the quantity by hand.",
    "Iz unosa dnevnika ne može se izračunati količina; unesite je ručno.":
        "The quantity cannot be computed from the log entry; enter it by hand.",
    "Zadatak nije pronađen.": "Task not found.",
    "Izvršilac mora biti član organizacije koji sme da menja ovu parcelu (vlasnik, agronom ili radnik sa pravom izmene).":
        "The assignee must be a member who may edit this parcel (owner, agronomist or a worker with edit access).",
    "Ova radnja nije moguća u trenutnom statusu zadatka (%s).": "This action is not possible in the task's current status (%s).",
    "Zadatak može da započne ili završi samo izvršilac, vlasnik ili agronom.":
        "Only the assignee, the owner or an agronomist can start or complete the task.",
    "Fotografija je obavezna: priložite je uz unos u dnevniku pre potvrde.":
        "A photo is required: attach it to the log entry before verifying.",
    "Stavka kontrolne liste nije pronađena.": "Checklist item not found.",
    "Raspon sezona nije ispravan (najviše 15 sezona, „od” ne posle „do”).":
        "The season range is not valid (at most 15 seasons, “from” not after “to”).",
    "Sezona mora biti godina (npr. 2026).": "The season must be a year (e.g. 2026).",
    "Naziv zadatka": "Task name", "Rok": "Due date", "Stavka kontrolne liste": "Checklist item",
    "Naziv": "Name", "Napomena": "Note", "Količina": "Quantity", "Datum": "Date", "Razlog": "Reason",
    "Oznaka lota": "Lot code", "Rok upotrebe": "Expiry date", "Dobavljač": "Supplier", "Cena po jedinici": "Unit price",
    "Prag niske zalihe": "Low-stock threshold", "Registarski broj": "Registration number", "Proizvođač": "Manufacturer",
}.items():
    MESSAGES.setdefault(_sr, _en)

# Spec 051 (plant-protection guidance from the registry): API messages of the consent, guidance and registry routes.
for _sr, _en in {
    "Aktivacija traži dve različite osobe (kurator i verifikator).": "Activation needs two different people (curator and verifier).",
    "Aktiviran uvoz se ne menja; ispravka je novi uvoz.": "An activated import is never changed; a correction is a new import.",
    "BBCH mora biti ceo broj 0-99.": "BBCH must be a whole number 0-99.",
    "Cilj (unos atlasa) je obavezan.": "The target (an atlas entry) is required.",
    "Cilj mora biti štetočina, bolest ili korov.": "The target must be a pest, a disease or a weed.",
    "Datoteka je prevelika.": "The file is too large.",
    "Datoteka nije u očekivanom obliku: %s": "The file is not in the expected form: %s",
    "Datum ne može biti u budućnosti.": "The date cannot be in the future.",
    "Demo organizacija ne može da uključi mere zaštite iz registra.": "The demo organisation cannot enable registry protection measures.",
    "Država je obavezna (dvoslovna oznaka).": "The country is required (two-letter code).",
    "EPPO kod cilja ne odgovara unosu atlasa.": "The target's EPPO code does not match the atlas entry.",
    "EPPO kod nije u proverenoj tabeli: %s.": "EPPO code not in the verified table: %s.",
    "Isto lice ne može da unese i potvrdi upotrebu (pravilo četiri oka).": "The same person cannot enter and verify a use (four-eyes rule).",
    "Isto lice ne može da uveze i potvrdi listu (pravilo četiri oka).": "The same person cannot import and verify a list (four-eyes rule).",
    "Isto lice ne potvrđuje dva puta (dve različite osobe).": "The same person cannot confirm twice (two different people).",
    "Jedinica %s nije u rečniku jedinica (koristite other uz doslovan tekst).": "Unit %s is not in the unit vocabulary (use other with the verbatim text).",
    "Kartica više nije važeća.": "The card is no longer valid.",
    "Mere zaštite iz registra uključuje samo vlasnik organizacije.": "Only the organisation owner can enable registry protection measures.",
    "Mere zaštite se prikazuju samo za cilj koji je korisnik potvrdio (ne za AI predlog).": "Protection measures are shown only for a target the user confirmed (not for an AI suggestion).",
    "Nedostaje datum stanja registra (source_as_of).": "The registry's as-of date is missing (source_as_of).",
    "Neispravan datum (YYYY-MM-DD).": "Invalid date (YYYY-MM-DD).",
    "Neispravan EPPO kod: %s.": "Invalid EPPO code: %s.",
    "Nepoznat cilj: unos atlasa nije pronađen.": "Unknown target: the atlas entry was not found.",
    "Nepoznat kod karence: %s.": "Unknown pre-harvest interval code: %s.",
    "Nepoznata površina prikaza: %s.": "Unknown display surface: %s.",
    "Nepoznata vrsta upotrebe: %s.": "Unknown use type: %s.",
    "Nepoznato poreklo cilja: %s.": "Unknown target origin: %s.",
    "Odluka je confirm ili reject.": "The decision is confirm or reject.",
    "Odluka je merge ili separate.": "The decision is merge or separate.",
    "Polje %s mora biti ceo nenegativan broj.": "Field %s must be a non-negative whole number.",
    "Polje %s mora biti nenegativan broj.": "Field %s must be a non-negative number.",
    "Potreban je dokaz: broj rešenja, link ili fotografija etikete.": "Evidence is required: a decision number, a link or a photo of the label.",
    "Potrebna je uloga registra: %s.": "A registry role is required: %s.",
    "Potrebno je izričito prihvatanje uslova.": "Explicit acceptance of the terms is required.",
    "Potvrda traži ulogu kuratora ili verifikatora registra.": "Confirmation needs the registry curator or verifier role.",
    "Povlači se samo aktivan uvoz.": "Only an active import can be withdrawn.",
    "Predlagač ne može da potvrdi svoj predlog.": "The proposer cannot confirm their own proposal.",
    "Predlog je već zatvoren.": "The proposal is already closed.",
    "Predlog nije pronađen.": "Proposal not found.",
    "Smernice nisu pronađene.": "Guidance not found.",
    "Sredstvo nije pronađeno.": "Product not found.",
    "Upotreba nije pronađena.": "Use not found.",
    "Uslovi su se promenili; pročitajte i prihvatite važeću verziju.": "The terms have changed; read and accept the current version.",
    "Uvoz ima greške; aktivacija nije moguća.": "The import has errors; activation is not possible.",
    "Uvoz ima upotrebe; potvrđuju se upotrebe.": "The import has uses; the uses are verified.",
    "Uvoz mora biti potvrđen (pravilo četiri oka) pre aktivacije.": "The import must be verified (four-eyes rule) before activation.",
    "Uvoz mora imati dvoslovnu oznaku države.": "The import needs a two-letter country code.",
    "Uvoz nije pronađen.": "Import not found.",
    "Uvoz test podataka nije dozvoljen na ovoj instanci.": "Importing test data is not allowed on this instance.",
    "Vaša uloga ne može da predlaže potvrdu registracije.": "Your role cannot propose a registration confirmation.",
    "Vrsta grupe je crop ili target.": "The group kind is crop or target.",
    "Za ovo sredstvo i državu već postoji otvoren predlog.": "An open proposal already exists for this product and country.",
    "Uvoz iz izvora %s nije uključen: uslovi ponovne upotrebe nisu potvrđeni (ppp_guidance.yaml sources.%s.importer_enabled).":
        "Import from source %s is not enabled: reuse terms are not confirmed (ppp_guidance.yaml sources.%s.importer_enabled).",
    "Registar (snimak)": "Registry (snapshot)", "Upotreba iz registra": "Registry use",
}.items():
    MESSAGES.setdefault(_sr, _en)
