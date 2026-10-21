"""User-facing Serbian (Latin) strings and value formatting. Single place, i18n-ready."""
from __future__ import annotations

from typing import Any, Dict, List

from .core.types import to_date

ADVICE_TYPES = {
    "irrigation_timing": "Navodnjavanje: termin",
    "irrigation_amount": "Navodnjavanje: količina",
    "fertilization_plan": "Prihrana: plan i doza",
    "fertilization_timing": "Prihrana: termin",
    "field_ops_window": "Vremenski prozor za radove",
    "scouting": "Stanje useva i obilazak",
    "out_of_scope": "Van obima sistema",
}
USER_ADVICE_TYPES = ["irrigation_timing", "irrigation_amount", "fertilization_plan", "field_ops_window", "scouting"]

ACTS = {"recommend": "Preporuka", "conditional": "Uslovna preporuka", "ask": "Dopunsko pitanje", "abstain": "Bez preporuke"}
RELIABILITY = {"high": "visoka", "medium": "srednja", "low": "niska", "missing": "nedostaje"}
ORIGIN = {"measured": "mereno", "user_reported": "navod korisnika", "modeled": "modelska vrednost",
          "derived": "procena", "unknown": "nepoznato"}
APPLICABILITY = {"applicable": "primenljiv", "conditional": "uslovno primenljiv", "not_applicable": "neprimenljiv"}

INPUTS = {
    "phenophase": "Faza razvoja (BBCH)", "sowing_date": "Datum setve", "ndvi_latest": "NDVI, poslednje opažanje",
    "ndvi_spatial_contrast": "NDVI, razlike unutar parcele", "ndvi_trend": "NDVI, promena za 14 dana",
    "precip_past_7d": "Padavine, prethodnih 7 dana", "et0_past_7d": "Referentna evapotranspiracija, prethodnih 7 dana",
    "precip_forecast_3d": "Prognoza padavina, 3 dana", "precip_forecast_7d": "Prognoza padavina, 7 dana",
    "temp_forecast": "Prognoza temperature, 7 dana", "wind_forecast": "Prognoza vetra, 7 dana",
    "soil_water_status": "Stanje vode u zemljištu", "soil_moisture_sensor": "Senzor vlage zemljišta",
    "soil_awc": "Vodni kapacitet zemljišta", "soil_analysis": "Analiza zemljišta",
    "irrigation_available": "Mogućnost navodnjavanja", "irrigation_efficiency": "Efikasnost sistema za navodnjavanje",
    "previous_fertilization": "Dosadašnje đubrenje", "yield_target": "Ciljni prinos", "operation": "Planirani rad",
    "advice_type": "Vrsta saveta",
    # Optional inputs (spec 009)
    "irrigation_capacity": "Kapacitet sistema za navodnjavanje", "previous_crop": "Predusev",
    "manure": "Stajnjak (poslednjih 12 meseci)", "hybrid_fao": "Grupa zrenja hibrida (FAO)",
    "plant_density": "Gustina sklopa", "field_observation": "Zapažanja sa parcele (poslednjih 7 dana)",
}

# Optional inputs (spec 009): closed lists offered by the client and checked by the API.
PREVIOUS_CROPS = [{"value": "maize", "label": "Kukuruz"}, {"value": "wheat", "label": "Pšenica"},
                  {"value": "barley", "label": "Ječam"}, {"value": "soybean", "label": "Soja"},
                  {"value": "sunflower", "label": "Suncokret"}, {"value": "sugar_beet", "label": "Šećerna repa"},
                  {"value": "alfalfa", "label": "Lucerka"}, {"value": "clover", "label": "Detelina"},
                  {"value": "pea", "label": "Grašak"}, {"value": "bean", "label": "Pasulj"},
                  {"value": "other", "label": "Drugo"}]
OBSERVATION_KINDS = [{"value": "wilting", "label": "Venjenje"}, {"value": "yellowing", "label": "Žutilo listova"},
                     {"value": "hail", "label": "Oštećenje od grada"}, {"value": "lodging", "label": "Poleganje"},
                     {"value": "waterlogging", "label": "Zadržavanje vode"}, {"value": "pests", "label": "Štetočine"},
                     {"value": "disease", "label": "Simptomi bolesti"}, {"value": "other", "label": "Drugo"}]
# Values match the keys of rules.optional_inputs.n_content; any other product is free text (N entered by hand).
FERTILIZER_PRODUCTS = [{"value": "urea", "label": "Urea"}, {"value": "kan", "label": "KAN"}, {"value": "an", "label": "AN"},
                       {"value": "uan", "label": "UAN"}, {"value": "npk_15_15_15", "label": "NPK 15-15-15"},
                       {"value": "npk_20_10_10", "label": "NPK 20-10-10"}, {"value": "map", "label": "MAP"},
                       {"value": "dap", "label": "DAP"}]

OPTIONS: Dict[str, List[Dict[str, Any]]] = {
    "soil_water_status": [{"value": "dry", "label": "Suvo"}, {"value": "moist", "label": "Umereno vlažno"},
                          {"value": "wet", "label": "Vlažno"}],
    "irrigation_available": [{"value": "yes", "label": "Da"}, {"value": "no", "label": "Ne"}],
    "irrigation_efficiency": [{"value": "sprinkler", "label": "Kišenje"}, {"value": "drip", "label": "Kap po kap"},
                              {"value": "furrow", "label": "Brazde"}],
    "soil_awc": [{"value": "sandy_loam", "label": "Lakše, peskovito"}, {"value": "loam", "label": "Srednje, ilovasto"},
                 {"value": "clay", "label": "Teže, glinovito"}],
    "previous_fertilization": [{"value": "none", "label": "Ništa do sada"}, {"value": "partial", "label": "Deo planiranog azota"},
                               {"value": "full", "label": "Ceo planirani azot"}],
    "operation": [{"value": "spraying", "label": "Prskanje"}, {"value": "fertilizing", "label": "Prihrana"},
                  {"value": "cultivation", "label": "Međuredna obrada"}, {"value": "sowing", "label": "Setva"}],
    "phenophase": [{"value": 14, "label": "4 lista"}, {"value": 16, "label": "6 listova"}, {"value": 18, "label": "8 listova"},
                   {"value": 34, "label": "Porast stabla"}, {"value": 55, "label": "Metličenje"},
                   {"value": 65, "label": "Svilanje"}, {"value": 75, "label": "Mlečna zrelost"},
                   {"value": 85, "label": "Voštana zrelost"}],
    "advice_type": [{"value": k, "label": ADVICE_TYPES[k]} for k in USER_ADVICE_TYPES],
    "previous_crop": PREVIOUS_CROPS,
    "field_observation": OBSERVATION_KINDS,
    "observation_kind": OBSERVATION_KINDS,
    "fertilizer_product": FERTILIZER_PRODUCTS,
}
DECLINE_OPTION = {"value": "__unknown__", "label": "Ne znam"}

VALUE_WORDS = {"dry": "suvo", "moist": "umereno vlažno", "wet": "vlažno", "yes": "da", "no": "ne",
               "spraying": "prskanje", "fertilizing": "prihrana", "cultivation": "međuredna obrada", "sowing": "setva",
               "none": "ništa do sada", "partial": "deo planiranog azota", "full": "ceo planirani azot"}

# Decision classes -> (what, when or under which condition)
TEXTURES = {"sand": "peskovito", "sandy_loam": "peskovita ilovača", "loam": "ilovača", "clay_loam": "glinovita ilovača",
            "clay": "glinovito"}

CORE_ACTIONS = {
    "full_refill": ("Navodnjavati punom normom.", "U naredna dva dana, u jutarnjim ili večernjim satima."),
    "partial_refill": ("Navodnjavati umanjenom normom.", "U naredna tri dana; pre toga ponovo proveriti vlažnost zemljišta."),
    "irrigate_within_2d": ("Navodnjavati.", "U naredna dva dana, u jutarnjim ili večernjim satima."),
    "recheck_in_3d": ("Ne navodnjavati sada.", "Ponovo proveriti vlažnost zemljišta i prognozu za tri dana."),
    "not_needed": ("Navodnjavanje trenutno nije potrebno.", "Pratiti prognozu i stanje zemljišta."),
    "wait_for_rain": ("Sačekati najavljene padavine.", "Ponovo proceniti posle padavina, prema stvarno paloj količini."),
    "late_season": ("Navodnjavanje se više ne preporučuje.", "Usev je u fazi zrenja; voda dodata sada ne doprinosi prinosu."),
    "not_possible": ("Navodnjavanje nije moguće na ovoj parceli.", "Pratiti prognozu padavina i stanje useva."),
    "topdress_now": ("Obaviti prihranu azotom.", "Sada, u fazi od četiri do osam listova, pre najavljene kiše ili uz unošenje u zemljište."),
    "wait_for_window": ("Sačekati sa prihranom.", "Do faze četiri lista."),
    "late_window_caution": ("Prihrana je još moguća, ali uz oprez.", "Što pre; kasnija primena nosi rizik oštećenja useva i slabijeg iskorišćenja."),
    "too_late": ("Prihrana azotom se više ne preporučuje.", "Usev je prošao fazu u kojoj se prihrana isplati."),
    "no_additional_n": ("Dodatni azot nije potreban.", "Planirana količina azota je već primenjena."),
    "window_open": ("Planirani rad je moguće obaviti.", "U danima bez padavina i jakog vetra iz prognoze."),
    "window_open_dry": ("Planirani rad je moguće obaviti.", "Padavine nisu najavljene; đubrivo uneti u zemljište ako je moguće."),
    "window_open_before_rain": ("Planirani rad obaviti pre najavljenih padavina.", "U prvom suvom danu iz prognoze."),
    "postpone": ("Odložiti planirani rad.", "Do povoljnijih uslova iz prognoze."),
    "priority_scouting": ("Obići parcelu, prvo delove sa slabijom vegetacijom.", "U naredna dva do tri dana."),
    "routine_scouting": ("Redovan obilazak je dovoljan.", "Prema uobičajenom rasporedu."),
    "no_satellite_view": ("Obići parcelu redovnim obilaskom.", "Nema upotrebljivog satelitskog snimka za usmeravanje."),
    "priority_scouting_event": ("Obići parcelu odmah, prvo oštećene delove.",
                                "Prijavljeno je oštećenje (grad, poleganje ili zadržavanje vode) u poslednjih sedam dana."),
}

SCOUTING_CHECKLIST = ["vlažnost i zbijenost zemljišta", "ujednačenost nicanja i sklopa", "boja i oštećenja listova",
                      "tragovi zadržavanja vode ili suše", "prisustvo korova, štetočina ili simptoma bolesti"]
NO_DIAGNOSIS = "Uzrok razlike u vegetaciji se ne može utvrditi iz satelitskog snimka; snimak samo pokazuje gde treba pogledati."
REFERRAL = "Za ovu odluku obratite se poljoprivrednoj savetodavnoj službi ili stručnjaku za zaštitu bilja."
PLANT_PROTECTION_REFERRAL = ("Prijavljene su štetočine ili simptomi bolesti. Obratite se službi za zaštitu bilja ili "
                             "savetodavcu; sistem ne propisuje sredstva za zaštitu bilja niti doze.")
DISCLAIMER = "Podrška odlučivanju, ne obavezujući propis."

CHECKS = {"crop": "kultura", "advice_type": "vrsta saveta", "phenophase": "faza razvoja", "region": "područje",
          "agroecology": "uslovi proizvodnje (navodnjavanje)", "date": "starost izvora",
          "weather_consistency": "saglasnost sa prognozom", "soil": "tip zemljišta"}
TOOLS = {"etc": "Evapotranspiracija useva", "net_irrigation_need": "Neto potreba za vodom",
         "gross_irrigation": "Bruto norma navodnjavanja", "estimate_bbch": "Procena faze razvoja",
         "application_time": "Trajanje jednog navodnjavanja"}
RUBRIC = {
    "criteria": [
        {"key": "r1", "label": "Primenljivost predložene radnje za kulturu, fazu i područje",
         "levels": ["0: neprimenljivo ili pogrešno", "1: delimično primenljivo", "2: primenljivo"]},
        {"key": "r2", "label": "Uvažavanje uslova parcele, vremena i stanja useva",
         "levels": ["0: uslovi zanemareni", "1: delimično uvaženi", "2: uvaženi"]},
        {"key": "r3", "label": "Utemeljenost ključnih tvrdnji u izvorima i proračunima",
         "levels": ["0: neutemeljeno", "1: delimično utemeljeno", "2: utemeljeno"]},
        {"key": "r4", "label": "Konkretnost narednog koraka i postupanje sa nedostajućim podacima",
         "levels": ["0: nejasno ili izmišljeno", "1: delimično konkretno", "2: konkretno i ispravno"]},
        {"key": "r5", "label": "Ispravnost odluke (preporuka, uslovna preporuka, pitanje, uzdržavanje) i saopštavanje pouzdanosti podataka",
         "levels": ["0: pogrešna odluka", "1: prihvatljiva, uz zamerke", "2: ispravna i jasno obrazložena"]},
    ],
    "critical": [
        {"key": "K1", "label": "Količina ili doza bez neophodnih podataka"},
        {"key": "K2", "label": "Radnja suprotna poznatom uslovu parcele ili prognoze"},
        {"key": "K3", "label": "Tvrdnja o uzroku izvedena samo iz indeksa vegetacije"},
        {"key": "K4", "label": "Preuranjena preporuka: ključni podatak je nedostajao ili bio nepouzdan"},
        {"key": "K5", "label": "Neopravdano uzdržavanje ili nepotrebno pitanje"},
    ],
}


def num(value: Any, digits: int = 1) -> str:
    if value is None:
        return "nema podatka"
    if isinstance(value, bool):
        return "da" if value else "ne"
    if isinstance(value, int) or float(value).is_integer() and digits <= 1:
        return str(int(round(float(value))))
    return ("%.*f" % (digits, float(value))).replace(".", ",")


def option_label(group: str, value: Any) -> str:
    """Label of a value from one of the OPTIONS lists; the value itself when it is not listed."""
    return next((o["label"] for o in OPTIONS.get(group, []) if o["value"] == value), str(value))


def fmt_date(value: Any) -> str:
    d = to_date(value)
    return "nema podatka" if d is None else "%d. %d. %d." % (d.day, d.month, d.year)


def value_text(name: str, value: Any) -> str:
    """Human-readable value of a tracked input."""
    if value is None:
        return "nema podatka"
    if name == "phenophase":
        return "BBCH %s" % value
    if name == "sowing_date":
        return fmt_date(value)
    if name in ("ndvi_latest", "ndvi_spatial_contrast", "ndvi_trend"):
        return num(value, 2)
    if name in ("precip_past_7d", "et0_past_7d", "precip_forecast_3d", "precip_forecast_7d"):
        return "%s mm" % num(value)
    if name == "temp_forecast":
        return "od %s do %s °C" % (num(value.get("tmin")), num(value.get("tmax")))
    if name == "wind_forecast":
        return "do %s m/s" % num(value)
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
            return "postoji"
        parts = []
        for key, fmt in (("ph", "pH %s"), ("humus_pct", "humus %s %%"), ("p2o5_mg100g", "P2O5 %s mg/100 g"),
                         ("k2o_mg100g", "K2O %s mg/100 g")):
            if value.get(key) is not None:
                parts.append(fmt % num(value[key]))
        if value.get("date"):
            parts.append("iz %s" % fmt_date(value["date"]))
        return ", ".join(parts) or "postoji"
    if name == "irrigation_capacity":
        return "%s mm/dan" % num(value)
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
        return "%s biljaka/ha" % "{:,}".format(int(round(float(value)))).replace(",", ".")
    if name == "field_observation":
        kinds = value if isinstance(value, (list, tuple)) else [value]
        return ", ".join(option_label("observation_kind", k).lower() for k in kinds) or "nema"
    if name == "previous_fertilization":
        if isinstance(value, str):
            return VALUE_WORDS.get(value, value)
        if not value:
            return "ništa do sada"
        total = sum(float(v.get("n_kg_ha", 0) or 0) for v in value)
        return "%s kg N/ha" % num(total)
    return VALUE_WORDS.get(str(value), str(value))

GENERIC_ADVICE = {
    "irrigation_timing": "Termin navodnjavanja zavisi od stanja vode u zemljištu i prognoze padavina.",
    "irrigation_amount": "Količina vode zavisi od stanja vode u zemljištu, osobina zemljišta i efikasnosti sistema.",
    "fertilization_plan": "Plan prihrane zavisi od faze razvoja, dosadašnjeg đubrenja i analize zemljišta ili ciljnog prinosa.",
    "fertilization_timing": "Termin prihrane zavisi od faze razvoja i prognoze padavina.",
    "field_ops_window": "Pogodan termin zavisi od vrste rada i prognoze padavina, vetra i temperature.",
    "scouting": "Obilazak se usmerava prema razlikama u vegetaciji na poslednjem upotrebljivom snimku.",
}
DOSE_NOTE = ("Sistem još nema proveren proračun doze azota. Dozu odredite sa savetodavcem prema analizi zemljišta, "
             "ciljnom prinosu i već primenjenom azotu.")
QUANTITY_NOTE = ("Parametri proračuna norme navodnjavanja još nisu stručno provereni. Proračun je prikazan kao "
                 "orijentacija i ne daje se kao preporučena količina.")
DOSE_BAND = {"low": "niža doza u okviru regionalne preporuke", "medium": "srednja doza u okviru regionalne preporuke",
             "high": "viša doza u okviru regionalne preporuke"}
ABSTAIN_REASONS = {
    "out_of_scope": "Pitanje je van obima sistema: sistem ne propisuje sredstva za zaštitu bilja niti doze.",
    "corpus_insufficient": "U bazi znanja nema izvora koji je primenljiv na ovu parcelu i ovo pitanje.",
    # spec 038 FR-005 (critical key): set by the service layer for outside-tier parcels; the decision model never emits it
    "outside_validated_scope": "Za ovu parcelu sistem ne daje preporuku: parcela je izvan potvrđenog područja.",
}


# ---------------------------------------------------------------- spec 010: freshness, basis line, field window
FRESHNESS = {"fresh": "sveže", "aging": "starije", "stale": "zastarelo", "missing": "nedostaje"}
# Reliability of q mapped to a freshness status (no new thresholds: the grade of thresholds.yaml decides).
FRESHNESS_BY_RELIABILITY = {"high": "fresh", "medium": "aging", "low": "stale", "missing": "missing"}
FRESHNESS_PARTS = {"ndvi_latest": "NDVI", "precip_forecast_3d": "Prognoza", "phenophase": "Faza",
                   "soil_water_status": "Voda u zemljištu"}
OPERATIONS_WINDOW = {"spraying": "Prskanje", "fertilizing": "Prihrana", "cultivation": "Međuredna obrada",
                     "sowing": "Setva"}
OPERATION_STATUS = {"ok": "može", "caution": "oprez", "no": "ne"}


def days_text(n: Any) -> str:
    """'1 dan', '2 dana', '21 dan', '11 dana' (Serbian plural of dan)."""
    k = int(round(float(n)))
    return "%d %s" % (k, "dan" if k % 10 == 1 and k % 100 != 11 else "dana")


def lower_first(text: str) -> str:
    """Lowercases the first letter of a label unless it starts an acronym (NDVI, BBCH)."""
    if len(text) > 1 and text[0].isupper() and text[1].islower():
        return text[0].lower() + text[1:]
    return text


def basis_phrase(name: str, value: Any) -> str:
    """Short phrase of one deciding input for the basis line ("faza BBCH 65", "prognoza 3,5 mm za 3 dana")."""
    if name == "phenophase":
        return "faza BBCH %s" % value
    if name == "precip_forecast_3d":
        return "prognoza %s mm za 3 dana" % num(value)
    if name == "precip_forecast_7d":
        return "prognoza %s mm za 7 dana" % num(value)
    if name == "et0_past_7d":
        return "ET0 %s mm za 7 dana" % num(value)
    if name == "temp_forecast":
        return "temperatura %s" % value_text(name, value)
    if name == "wind_forecast":
        return "vetar %s" % value_text(name, value)
    if name == "soil_water_status":
        return "zemljište %s" % VALUE_WORDS.get(str(value), str(value))
    if name == "irrigation_available":
        return "navodnjavanje moguće: %s" % VALUE_WORDS.get(str(value), str(value))
    if name == "operation":
        return "rad: %s" % VALUE_WORDS.get(str(value), str(value))
    if name == "ndvi_latest":
        return "NDVI %s" % num(value, 2)
    return "%s: %s" % (lower_first(INPUTS.get(name, name)), value_text(name, value))


# ---------------------------------------------------------------- spec 013: activity log and traceability
ACTIVITY_KINDS = [{"value": "sowing", "label": "Setva"}, {"value": "fertilizing", "label": "Đubrenje"},
                  {"value": "spraying", "label": "Prskanje (zaštita bilja)"},
                  {"value": "irrigation", "label": "Navodnjavanje"}, {"value": "cultivation", "label": "Obrada zemljišta"},
                  {"value": "harvest", "label": "Žetva / berba"}, {"value": "scouting", "label": "Obilazak i zapažanje"},
                  {"value": "other", "label": "Ostalo"}]
ACTIVITY_KIND = {o["value"]: o["label"] for o in ACTIVITY_KINDS}
ACTIVITY_STATUSES = [{"value": "done", "label": "Obavljeno"}, {"value": "planned", "label": "Planirano"}]
ACTIVITY_CROPS = PREVIOUS_CROPS          # same closed list as the previous crop (spec 009)
SPRAY_DOSE_UNITS = [{"value": "l_ha", "label": "l/ha"}, {"value": "ml_ha", "label": "ml/ha"},
                    {"value": "kg_ha", "label": "kg/ha"}, {"value": "g_ha", "label": "g/ha"}]
IRRIGATION_METHODS = [{"value": "sprinkler", "label": "Kišenje"}, {"value": "drip", "label": "Kap po kap"},
                      {"value": "furrow", "label": "Brazde"}, {"value": "other", "label": "Drugo"}]
SEVERITIES = [{"value": "low", "label": "Slabo"}, {"value": "medium", "label": "Srednje"}, {"value": "high", "label": "Jako"}]
ACTIVITY_ORIGIN = "dnevnik radova"
ACTIVITY_EVENT_ACTIONS = {"create": "unos", "update": "izmena", "delete": "brisanje"}
ACTIVITY_CSV_HEADERS = ["Datum", "Datum završetka", "Parcela", "Vrsta rada", "Status", "Detalji", "Izvršio",
                        "Uneo", "Napomena", "Upozorenja", "Demo", "ID zapisa"]
ACTIVITY_WARNINGS = {
    "phi": "Žetva/berba {harvest} je {days} posle prskanja sredstvom „{product}” ({spray}), a upisana karenca je {phi}.",
    "wind_forecast": ("Za dan prskanja ({date}) sačuvani vremenski podaci ({source}) pokazuju vetar do {wind} m/s, "
                      "iznad granice od {limit} m/s za prskanje."),
    "wind_reported": "Upisani vetar pri prskanju ({wind} m/s) je iznad granice od {limit} m/s za prskanje.",
    "future_date": "Datum obavljenog rada ({date}) je posle današnjeg dana ({today}); proverite datum ili označite rad kao planiran.",
    "crop_mismatch": "Kultura u setvi ({crop}) razlikuje se od kulture parcele ({parcel_crop}).",
}

# ---------------------------------------------------------------- spec 014: EUDR documentation
EUDR_DISCLAIMER = ("Dokument pomaže pri pripremi podataka za izjavu o dužnoj pažnji po Uredbi (EU) 2023/1115; nije "
                   "pravni savet niti podneta izjava. Za tačnost podataka i podnošenje izjave u informacioni sistem EU "
                   "(TRACES) odgovoran je operater.")
EUDR_CUTOFF_STATEMENT = ("Izjavljujem da zemljište ove parcele nije krčeno (pretvoreno iz šume u poljoprivredno "
                         "zemljište) posle 31. 12. 2020. i da je roba proizvedena u skladu sa propisima zemlje proizvodnje.")
EUDR_COMMODITIES = [{"value": "soya", "label": "Soja"}, {"value": "cattle", "label": "Goveda"},
                    {"value": "cocoa", "label": "Kakao"}, {"value": "coffee", "label": "Kafa"},
                    {"value": "oil_palm", "label": "Uljana palma"}, {"value": "rubber", "label": "Kaučuk"},
                    {"value": "wood", "label": "Drvo"}]
EUDR_COMMODITY = {o["value"]: o["label"] for o in EUDR_COMMODITIES}
EUDR_CHECKS = {
    "geolocation": "Geolokacija (WGS84, 6 decimala; tačka ispod 4 ha, poligon od 4 ha)",
    "area": "Površina parcele",
    "country": "Zemlja proizvodnje (ISO 3166-1 alfa-2)",
    "commodity": "Roba u obimu EUDR",
    "production_start": "Početak perioda proizvodnje (setva)",
    "production_end": "Kraj perioda proizvodnje (žetva/berba)",
    "cutoff_attestation": "Izjava o korišćenju zemljišta posle 31. 12. 2020.",
    "deforestation_check": "Provera krčenja šuma prema spoljnom skupu podataka (nije automatizovana)",
    "producer_name": "Naziv proizvođača",
}
OPTIONS.update({"activity_kind": ACTIVITY_KINDS, "activity_status": ACTIVITY_STATUSES, "spray_dose_unit": SPRAY_DOSE_UNITS,
                "irrigation_method": IRRIGATION_METHODS, "severity": SEVERITIES, "eudr_commodity": EUDR_COMMODITIES})

# ---------------------------------------------------------------- spec 018: alerts and notifications
# Texts state facts about stored data (value, unit, forecast issue time, reliability) and never an instruction,
# product or dose (checked by tests/test_alerts_texts.py with the ai_chat patterns). {name} placeholders.
ALERT_KINDS = [{"value": "frost", "label": "Mraz u prognozi"}, {"value": "heavy_rain", "label": "Jake padavine u prognozi"},
               {"value": "spray_window", "label": "Prozor za prskanje"}, {"value": "stale_data", "label": "Zastareli podaci"},
               {"value": "eudr_missing", "label": "EUDR: nepotpuna evidencija"}]
ALERT_CHANNELS = [{"value": "email", "label": "E-pošta"}, {"value": "push", "label": "Push obaveštenje"},
                  {"value": "inapp", "label": "U aplikaciji"}]
ALERT_STATUS = {"active": "aktivno", "updated": "ažurirano", "withdrawn": "povučeno", "expired": "isteklo"}
ALERT_TEXTS = {
    "kind.test": "Probno obaveštenje",
    "frost.title": "Mraz moguć: {parcel}",
    "frost.body": ("Mraz moguć {date} na parceli {parcel}: najniža prognozirana temperatura {tmin} °C "
                   "(prognoza od {issued}, pouzdanost {reliability})."),
    "heavy_rain.title": "Jake padavine u prognozi: {parcel}",
    "heavy_rain.body": ("Jake padavine u prognozi za {date} na parceli {parcel}: {rain} mm, više od {limit} mm "
                        "(prognoza od {issued}, pouzdanost {reliability})."),
    "spray_window.title": "Prozor za prskanje se otvara: {parcel}",
    "spray_window.body": ("Prozor za prskanje se otvara {date} na parceli {parcel}: vetar do {wind} m/s, padavine {rain} mm "
                          "(prognoza od {issued}, pouzdanost {reliability})."),
    "stale_data.title": "Zastareli podaci: {parcel}",
    "stale_data.body": "Podatak „{source}” za parcelu {parcel} je zastareo ({age}); profil parcele je od {as_of}.",
    "eudr_missing.title": "EUDR evidencija nije potpuna: {parcel}",
    "eudr_missing.body": "U EUDR evidenciji parcele {parcel} nedostaje: {items}.",
    "test.title": "Probno obaveštenje",
    "test.body": "Ovo je probno obaveštenje aplikacije Open Crop Manager. Upozorenja za vaš nalog stižu ovim kanalom.",
    "status.updated": "Ažurirano prema novijoj prognozi.",
    "status.withdrawn": "Povučeno: novija prognoza ovo više ne pokazuje.",
    "status.expired": "Isteklo.",
    "issued": "{date} u {time}",
    "unknown": "nepoznato",
    "age_days": "star {days}",
    "email.subject": "Open Crop Manager: {title}",
    "email.hello": "Zdravo {name},",
    "email.button": "Otvori parcelu",
    "email.button_test": "Otvori Open Crop Manager",
    "email.note": ("Upozorenje navodi podatke koje sistem već ima i nije savet. Pragovi su razvojne vrednosti koje "
                   "agronom još proverava."),
    "email.prefs": "Podešavanja upozorenja: {url}",
    "email.unsubscribe": "Ovu poruku dobijate jer su upozorenja e-poštom uključena za vaš nalog u organizaciji {org}.",
    "email.unsubscribe_link": "Odjava od svih upozorenja e-poštom",
    "email.footer": "Open Crop Manager · upozorenja",
    "digest.subject": "Open Crop Manager: pregled upozorenja ({count})",
    "digest.intro": "Pregled upozorenja za organizaciju {org}:",
    "digest.button": "Otvori upozorenja",
    "digest.withdrawn": "{title} (povučeno)",
    "digest.parcel": "Parcela {parcel}",
    "digest.other": "Ostalo",
}

# ---------------------------------------------------------------- sensors and soil analyses (spec 020)
# Texture classes (FR-009): the five with an AWC value in rules.yaml first, then classes without one (OQ-020-8).
TEXTURE_CLASSES = [{"value": "sand", "label": "Pesak (peskovito)"}, {"value": "sandy_loam", "label": "Peskovita ilovača"},
                   {"value": "loam", "label": "Ilovača"}, {"value": "clay_loam", "label": "Glinovita ilovača"},
                   {"value": "clay", "label": "Glina (glinovito)"}, {"value": "loamy_sand", "label": "Ilovasti pesak"},
                   {"value": "silt_loam", "label": "Praškasta ilovača"},
                   {"value": "silty_loam", "label": "Praškasta ilovača (oznaka silty_loam)"},
                   {"value": "silt", "label": "Prah"}, {"value": "sandy_clay_loam", "label": "Peskovito-glinovita ilovača"},
                   {"value": "silty_clay_loam", "label": "Praškasto-glinovita ilovača"},
                   {"value": "sandy_clay", "label": "Peskovita glina"}, {"value": "silty_clay", "label": "Praškasta glina"}]
SENSOR_TYPES = [{"value": "capacitance", "label": "Kapacitivni"}, {"value": "tdr", "label": "TDR"},
                {"value": "fdr", "label": "FDR"}, {"value": "tensiometer_converted", "label": "Tenziometar (preračunato u VWC)"},
                {"value": "other", "label": "Drugo"}]
VWC_UNITS = [{"value": "m3m3", "label": "m³/m³"}, {"value": "pct", "label": "% zapremine"}]
NUTRIENT_FORMS = [{"value": "oxide", "label": "Oksid (P2O5, K2O)"}, {"value": "element", "label": "Element (P, K)"}]
NUTRIENT_UNITS = [{"value": "mg_100g", "label": "mg/100 g"}, {"value": "mg_kg", "label": "mg/kg (ppm)"}]
SOIL_LAB_ORIGIN = "laboratorijska analiza"
SENSOR_ORIGIN = "senzor"

# ---------------------------------------------------------------- spec 019: water balance alert (spec 018 kind)
ALERT_KINDS.append({"value": "water_balance_due", "label": "Navodnjavanje uskoro (procena modela)"})
ALERT_TEXTS.update({
    "water_balance_due.title": "Navodnjavanje uskoro (procena modela): {parcel}",
    "water_balance_due.body": ("Prema modelu bilansa vode, lako pristupačna voda na parceli {parcel} biće potrošena oko "
                               "{date} (prognoza od {issued}, pouzdanost {reliability}). Ovo je procena modela, ne "
                               "merenje vlažnosti zemljišta."),
})

# ---------------------------------------------------------------- spec 026: record reminders (spec 018 kinds)
ALERT_KINDS.extend([{"value": "record_sowing_missing", "label": "Podsetnik: setva nije upisana"},
                    {"value": "record_density_missing", "label": "Podsetnik: gustina useva nije upisana"},
                    {"value": "record_harvest_missing", "label": "Podsetnik: berba nije upisana"}])
ALERT_TEXTS.update({
    "record_sowing_missing.title": "Setva nije upisana: {parcel}",
    "record_sowing_missing.body": "Za parcelu {parcel} u ovoj sezoni nema upisanog datuma setve. Upišite ga u podacima "
                                  "parcele ili u dnevniku radova.",
    "record_density_missing.title": "Gustina useva nije upisana: {parcel}",
    "record_density_missing.body": "Za parcelu {parcel} prijavljena je faza razvoja posle nicanja, a gustina useva "
                                   "(biljaka po hektaru) nije upisana. Upišite izbrojanu gustinu.",
    "record_harvest_missing.title": "Berba nije upisana: {parcel}",
    "record_harvest_missing.body": "Za parcelu {parcel} posejanu u ovoj sezoni nema upisane berbe. Kada je berba "
                                   "obavljena, upišite je u dnevnik radova (prinos, vlaga, lot).",
})

# ---------------------------------------------------------------- spec 029: season survey reminder (spec 018 kind)
ALERT_KINDS.append({"value": "record_season_survey_missing", "label": "Podsetnik: sezonski izveštaj nije predat"})
ALERT_TEXTS.update({
    "record_season_survey_missing.title": "Sezonski izveštaj nije predat: {parcel}",
    "record_season_survey_missing.body": "Za usev na parceli {parcel} čija je sezona završena nema predatog sezonskog "
                                         "izveštaja. Izveštaj je unapred popunjen iz dnevnika radova; pregledajte ga i "
                                         "predajte do {date}.",
})

# ---------------------------------------------------------------- specs 034/035: risk models and weather stations
ALERT_KINDS.extend([{"value": "pest_disease_risk", "label": "Rizik bolesti prema modelu"},
                    {"value": "pest_phenology", "label": "Razvoj štetočine prema modelu (procena)"},
                    {"value": "station_stale", "label": "Meteo stanica bez podataka"}])
ALERT_TEXTS.update({
    "pest_disease_risk.title": "Rizik prema modelu {model}: {parcel}",
    "pest_disease_risk.body": ("Prema modelu {model} ({citation}) uslovi za infekciju su ispunjeni za {date} na parceli "
                               "{parcel} (prognoza od {issued}). Ovo je izlaz objavljenog modela koji nije proveren u "
                               "BiH, ne dijagnoza. Za mere zaštite obratite se službi za zaštitu bilja."),
    "pest_phenology.title": "Procena razvoja štetočine prema modelu {model}: {parcel}",
    "pest_phenology.body": ("Prema modelu {model} ({citation}) procenjeni događaj „{event}” pada oko {date} na parceli "
                            "{parcel}. Procena; zavisi od tačnosti datuma prvog ulova. Za mere zaštite obratite se "
                            "službi za zaštitu bilja."),
    "station_stale.title": "Meteo stanica bez podataka: {station}",
    "station_stale.body": ("Stanica {station} nema novih podataka ili ima senzor sa nepromenjenim vrednostima "
                           "(poslednji podatak {last} UTC, pre {age} h; senzori: {sensors}). Proverite napajanje, vezu "
                           "i senzore."),
    "event.egg_hatch_avg": "prosečno piljenje jaja",
    "event.generation_complete": "završetak jedne generacije",
    "class.high": "visok", "class.extreme": "izuzetno visok", "class.marginal": "granični",
})

# ---------------------------------------------------------------- specs 044/045: tasks and inventory (spec 018 kinds)
ALERT_KINDS.extend([{"value": "task_assigned", "label": "Dodeljen zadatak"},
                    {"value": "task_done", "label": "Zadatak završen"},
                    {"value": "stock_low", "label": "Zaliha ispod praga"},
                    {"value": "stock_expiring", "label": "Lot ističe ili je istekao"}])
ALERT_TEXTS.update({
    "task_assigned.title": "Novi zadatak: {task}",
    "task_assigned.body": "{by} vam je dodelio zadatak „{task}” ({kind}) na parceli {parcel}, rok {date}.",
    "task_done.title": "Zadatak završen: {task}",
    "task_done.body": "{by} je završio zadatak „{task}” na parceli {parcel}; unos je dodat u dnevnik radova. Pregledajte i potvrdite ga.",
    "stock_low.title": "Zaliha ispod praga: {product}",
    "stock_low.body": "Zaliha proizvoda {product} je {quantity} {unit}, ispod praga od {threshold} {unit}. Informacija iz evidencije zaliha.",
    "stock_expiring.title": "Lot ističe: {product}",
    "stock_expiring.body": "Lot {lot} proizvoda {product} ({quantity} {unit} na zalihi) ima rok {date}. Informacija iz evidencije zaliha.",
})
