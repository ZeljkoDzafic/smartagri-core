"""Registry of the agronomic parameters that can be set through the web (settings levels: global, user, parcel).

The registry describes parameters; it never holds their defaults. A default is read from the YAML file at run time
(`config.load_file`), so the files stay the single source of the starting values. `entries()` expands the declarations
below against the files: a declaration with a `*` matches every key at that place (for example every input of
thresholds.yaml), a declaration without one matches one key. `uncovered()` lists the leaves of the editable files that no
declaration covers; a test fails when it is not empty, so a new YAML key cannot be added without a registry entry.

Protocol files (variants, analysis, evaluation, vocab) are not parameters of the web: they define the experiment and are
shown read-only (`protocol_view`). Evaluation (evalkit) reads the files only and never an overlay.

Declarations carry the source and the status of a value (verified, partly, disputed, no_source, development). The status
comes from the comparison of the constants with the cited sources and is not an agronomic approval.

Python 3.9 compatible; no dependencies beyond the standard library and the existing PyYAML.
"""
from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .. import config, labels, labels_en

EDITABLE_FILES = ("rules", "kc_maize", "thresholds", "asking", "requirements", "parcel_features")
PROTOCOL_FILES = ("variants", "analysis", "evaluation", "vocab")

STATUSES = ("verified", "partly", "disputed", "no_source", "development")
RELIABILITY = ("high", "medium", "low")
ORIGINS = ("measured", "user_reported", "modeled", "derived", "unknown")
TOKEN = re.compile(r"^[A-Za-z0-9_+.\-]{1,40}$")
MAX_ITEMS = 24

SOURCES: Dict[str, Tuple[str, str]] = {
    "fao56_t11": ("Allen et al. (1998), FAO-56, Table 11 (length of the growing stages)",
                  "https://www.fao.org/4/x0490e/x0490e0b.htm"),
    "fao56_t12": ("Allen et al. (1998), FAO-56, Table 12 (single crop coefficients)",
                  "https://www.fao.org/4/x0490e/x0490e0b.htm"),
    "fao56_t19": ("Allen et al. (1998), FAO-56, Table 19 (soil water characteristics)",
                  "https://www.fao.org/4/x0490e/x0490e0c.htm"),
    "fao56_t22": ("Allen et al. (1998), FAO-56, Table 22 (rooting depth, depletion fraction p) and eq. 82-83",
                  "https://www.fao.org/4/x0490e/x0490e0e.htm"),
    "fao4_t4": ("Brouwer, Prins and Heibloem (1989), FAO Irrigation Water Management, Training Manual 4, ch. 3, Table 4 "
                "(net irrigation depths)", "https://www.fao.org/4/t7202e/t7202e06.htm"),
    "fao4_t5": ("Brouwer, Prins and Heibloem (1989), FAO Training Manual 4, ch. 3, Table 5 (rooting depth)",
                "https://www.fao.org/4/t7202e/t7202e06.htm"),
    "fao4_t8": ("Brouwer, Prins and Heibloem (1989), FAO Training Manual 4, Annex I, Table 8 (application efficiency)",
                "https://www.fao.org/4/t7202e/t7202e08.htm"),
    "mcmaster": ("McMaster and Wilhelm (1997), Agric. For. Meteorol. 87(4), 291-300 (growing degree-days; method only)",
                 "https://doi.org/10.1016/S0168-1923(97)00027-0"),
    "sentiwiki": ("SentiWiki, Sentinel-2 Mission (revisit period)", "https://sentiwiki.copernicus.eu/web/s2-mission"),
    "arith": ("Arithmetic: 30 interior pixels x 100 m2 = 0.3 ha, 10 x 100 m2 = 0.1 ha (10 m pixel, SentiWiki)",
              "https://sentiwiki.copernicus.eu/web/s2-mission"),
    "stoich": ("Stoichiometry of the pure compound (arithmetic): the share of N cannot be higher", ""),
}

# Review outcome shown next to the value, status by status (the same wording for every parameter with that outcome unless
# a declaration gives its own note).
NO_SOURCE_EN = "No external source found in the review of the constants (27 October 2026). Development value, awaiting agronomist review."
NO_SOURCE_SR = "U proveri konstanti (27. 10. 2026) nije nađen spoljni izvor. Razvojna vrednost, čeka pregled agronoma."
DEV_EN = "Development value, awaiting agronomist review. No external source is claimed."
DEV_SR = "Razvojna vrednost, čeka pregled agronoma. Spoljni izvor se ne tvrdi."


@dataclass(frozen=True)
class Col:
    name: str
    kind: str                                   # int | float | str | enum | bool | list
    lo: Optional[float] = None
    hi: Optional[float] = None
    choices: Optional[Any] = None               # tuple, or a dynamic name ("inputs", "advice_types")
    optional: bool = False
    en: str = ""
    sr: str = ""


@dataclass
class Spec:
    path: str
    kind: str                                   # bool int float str enum pair list map table groups
    group: str
    en: str
    sr: str
    unit: str = ""
    lo: Optional[float] = None
    hi: Optional[float] = None
    choices: Optional[Any] = None
    cols: Tuple[Col, ...] = ()
    checks: Tuple[str, ...] = ()
    min_items: int = 0
    max_items: int = MAX_ITEMS
    max_len: int = 400
    recommended: Any = None
    source: str = ""
    status: str = "development"
    note_en: str = ""
    note_sr: str = ""
    user: bool = True                           # may a user (and a parcel) override it, before the admin decides
    readonly: Optional[Tuple[str, str]] = None  # (reason en, reason sr): shown, never editable
    item_kind: str = "token"                    # list items: token (a short word), scalar (a number or a word)
    hint_en: str = ""
    hint_sr: str = ""
    limit: Any = None                           # default administrator limit, same shape as `recommended`; else derived
    basis: str = ""                             # "development" when `recommended` is not a range of the cited source


def c(name, kind, lo=None, hi=None, choices=None, optional=False, en="", sr=""):
    return Col(name, kind, lo, hi, choices, optional, en or name, sr or en or name)


RELIAB = c("reliability", "enum", choices=RELIABILITY, en="Reliability", sr="Pouzdanost")
MINREL = c("min_reliability", "enum", choices=RELIABILITY, en="Minimum reliability", sr="Najmanja pouzdanost")
INPUT_COL = c("input", "enum", choices="inputs", en="Input", sr="Ulaz")
GRADE_COLS = (
    RELIAB,
    c("origins", "list", choices=ORIGINS, optional=True, en="Origins", sr="Poreklo"),
    c("max_age_days", "int", 0, 36500, optional=True, en="Max age (days)", sr="Najveća starost (dani)"),
    c("min_coverage", "float", 0, 1, optional=True, en="Min coverage", sr="Najmanja pokrivenost"),
    c("min_count", "int", 1, 1000, optional=True, en="Min count", sr="Najmanji broj"),
)

# ---------------------------------------------------------------------------------------------------------------------
# Declarations. Order matters: the first declaration whose path matches wins, so specific ones precede wildcards.
# ---------------------------------------------------------------------------------------------------------------------
G_IRR, G_FERT, G_OPS, G_SCOUT, G_PHEN, G_SOIL, G_KC = ("irrigation", "fertilization", "field_ops", "scouting", "phenology",
                                                       "soil", "crop_coefficients")
G_OPT, G_ASK, G_REQ, G_Q, G_PF = "optional_inputs", "asking", "sufficiency", "quality", "parcel_features"
G_IN = "input_limits"

GROUPS = [
    (G_IRR, "Irrigation", "Navodnjavanje"), (G_FERT, "Fertilization", "Đubrenje"),
    (G_OPS, "Field operations", "Radovi u polju"), (G_SCOUT, "Scouting (NDVI)", "Obilazak (NDVI)"),
    (G_PHEN, "Phenology", "Fenologija"), (G_SOIL, "Soil", "Zemljište"),
    (G_KC, "Crop coefficients", "Koeficijenti kulture"), (G_OPT, "Optional inputs", "Opcioni ulazi"),
    (G_IN, "Plausible ranges of inputs", "Verodostojni opsezi ulaza"),
    (G_ASK, "Asking and sufficiency", "Pitanja i dovoljnost"), (G_REQ, "Required inputs per advice type", "Neophodni ulazi po tipu saveta"),
    (G_Q, "Input quality thresholds", "Pragovi kvaliteta ulaza"), (G_PF, "Parcel features", "Pokazatelji parcele"),
]


def _scalar(path, kind, group, en, sr, unit="", lo=None, hi=None, **kw):
    return Spec(path, kind, group, en, sr, unit=unit, lo=lo, hi=hi, **kw)


def _no(en_note="", sr_note=""):
    return dict(status="no_source", note_en=en_note or NO_SOURCE_EN, note_sr=sr_note or NO_SOURCE_SR)


def _dev(en_note="", sr_note=""):
    return dict(status="development", note_en=en_note or DEV_EN, note_sr=sr_note or DEV_SR)


def _limit(key, en, sr, unit, lo, hi, recommended, note_en, note_sr, source="", status="development"):
    return Spec("rules.input_limits." + key, "pair", G_IN, en, sr, unit=unit, lo=lo, hi=hi, user=False, recommended=recommended,
                basis="development", source=source, status=status, note_en=note_en, note_sr=note_sr)


SPECS: List[Spec] = [
    # ---------------------------------------------------------------- rules.yaml: irrigation
    _scalar("rules.irrigation.rain_wait_mm_3d", "float", G_IRR, "Forecast rain that justifies waiting", "Prognozirana kiša koja opravdava čekanje", "mm", 0, 200, **_no()),
    _scalar("rules.irrigation.late_season_bbch", "int", G_IRR, "No irrigation advice from this growth stage (BBCH)", "Bez saveta o navodnjavanju od ove faze (BBCH)", "BBCH", 0, 99,
            **_no("No external source found; FAO-56 gives no stop of irrigation by BBCH. Development value, awaiting agronomist review.",
                  "Spoljni izvor nije nađen; FAO-56 ne daje prekid navodnjavanja po BBCH. Razvojna vrednost, čeka pregled agronoma.")),
    Spec("rules.irrigation.awc_bands_mm_m", "pair", G_IRR, "Water-holding capacity bands (low / medium / high dose)", "Granice vodnog kapaciteta (niska / srednja / visoka doza)",
         unit="mm/m", lo=0, hi=500, source="fao56_t19", status="partly",
         note_en="The limits coincide with the loam range of Table 19 (130-180 mm/m). Whether they are sensible limits for the low / medium / high dose band is not in the source.",
         note_sr="Granice se poklapaju sa opsegom ilovače u Tabeli 19 (130-180 mm/m). Da li su to razumne granice pojasa doze, nije u izvoru."),
    _scalar("rules.irrigation.forecast_days", "int", G_IRR, "Forecast window used for the irrigation balance", "Prozor prognoze za bilans navodnjavanja", "days", 1, 14, **_no()),
    _scalar("rules.irrigation.max_single_net_mm", "float", G_IRR, "Largest net depth in one irrigation", "Najveća neto doza u jednom navodnjavanju", "mm (water)", 1, 300,
            source="fao4_t4", status="partly", recommended=(15, 70),
            note_en="Net depth in millimetres of water, not nitrogen. The source gives 15-70 mm depending on soil and rooting depth; one limit for all textures is a compromise, and for sandy soils and early stages the source gives less than 50 mm.",
            note_sr="Neto dubina vode u milimetrima, ne azot. Izvor daje 15-70 mm zavisno od zemljišta i dubine korena; jedna granica za sve teksture je kompromis, a za peskovita zemljišta i rane faze izvor daje manje od 50 mm."),
    _scalar("rules.irrigation.quantity_validated", "bool", G_IRR, "Irrigation quantities reviewed by an agronomist (safety gate)", "Količine za navodnjavanje pregledao agronom (zaštitni prekidač)",
            user=False, status="development",
            note_en="Safety gate: while it is false the system gives no irrigation quantity. Turn it on only after an agronomist has reviewed the balance parameters.",
            note_sr="Zaštitni prekidač: dok je isključen, sistem ne daje količinu za navodnjavanje. Uključiti tek kada agronom pregleda parametre bilansa."),
    Spec("rules.irrigation.root_depth_m_by_bbch", "table", G_IRR, "Effective root depth by growth stage", "Efektivna dubina korena po fazi", unit="m",
         cols=(c("bbch_max", "int", 0, 99, en="Up to BBCH", sr="Do BBCH"), c("depth", "float", 0.05, 3.0, en="Depth (m)", sr="Dubina (m)")),
         checks=("sorted:bbch_max", "last_min:bbch_max:99"), min_items=1, max_items=8, source="fao56_t22", status="partly",
         recommended={"depth": (0.2, 1.7)}, limit={"depth": (0.1, 2.0)}, basis="development",
         note_en="The last row (1.0 m) lies in the source range 1.0-1.7 m (Table 22; Table 5 of the training manual: 90-150 cm). The 0.3 m and 0.6 m rows have no source. The last row must reach BBCH 99. The upper end of the recommended range (1.7 m) is the top of that source range; the lower end (0.2 m) and the limit (0.1-2.0 m) are development values.",
         note_sr="Poslednji red (1,0 m) je u opsegu izvora 1,0-1,7 m (Tabela 22; Tabela 5 priručnika: 90-150 cm). Redovi 0,3 m i 0,6 m nemaju izvor. Poslednji red mora da dosegne BBCH 99. Gornji kraj preporučenog opsega (1,7 m) je vrh tog opsega izvora; donji kraj (0,2 m) i granica (0,1-2,0 m) su razvojne vrednosti."),
    Spec("rules.irrigation.vwc_bands", "pair", G_IRR, "Soil sensor limits: dry / moist / wet (volumetric water content)", "Granice senzora vlage: suvo / umereno / vlažno (zapreminski sadržaj vode)",
         unit="m3/m3", lo=0, hi=1, source="fao56_t19", status="disputed",
         note_en="One pair of limits for all textures does not agree with Table 19, where the wilting point and field capacity depend on texture (for sand 0.18 is above field capacity, for clay it is below the wilting point). Needs a code change to be made texture-dependent.",
         note_sr="Jedan par granica za sve teksture ne slaže se sa Tabelom 19, gde tačka uvenuća i poljski kapacitet zavise od teksture (za pesak je 0,18 iznad poljskog kapaciteta, za glinu ispod tačke uvenuća). Za zavisnost od teksture potrebna je izmena koda."),
    # ---------------------------------------------------------------- rules.yaml: fertilization
    Spec("rules.fertilization.topdress_bbch", "pair", G_FERT, "Main top-dressing window (BBCH from, to)", "Glavni prozor prihrane (BBCH od, do)", unit="BBCH", lo=0, hi=99, **_no(
        "No external source; the only reference is a development note of the project. Development value, awaiting agronomist review.",
        "Nema spoljnog izvora; jedina referenca je razvojna beleška projekta. Razvojna vrednost, čeka pregled agronoma.")),
    _scalar("rules.fertilization.late_bbch_max", "int", G_FERT, "No top-dressing advice after this stage (BBCH)", "Bez saveta o prihrani posle ove faze (BBCH)", "BBCH", 0, 99, **_no()),
    _scalar("rules.fertilization.season_n_full_kg_ha", "float", G_FERT, "Previous nitrogen counted as \"full\"", "Prethodni azot koji se računa kao \"pun\"", "kg N/ha", 0, 500,
            **_no("No external source. This is a threshold for the descriptive dose band, not a nitrogen dose. Development value, awaiting agronomist review.",
                  "Nema spoljnog izvora. Prag je za opisni pojas doze, a ne doza azota. Razvojna vrednost, čeka pregled agronoma.")),
    Spec("rules.fertilization.yield_bands_t_ha", "pair", G_FERT, "Target-yield bands (low / medium / high dose band)", "Granice ciljnog prinosa (niska / srednja / visoka doza)", unit="t/ha", lo=0, hi=40, **_no()),
    # ---------------------------------------------------------------- rules.yaml: field operations
    _scalar("rules.field_ops.spraying_max_wind_ms", "float", G_OPS, "Wind limit for spraying", "Granica vetra za prskanje", "m/s", 0, 40,
            **_no("No external source; the usual limit depends on the product label and local rules. Development value, awaiting agronomist review.",
                  "Nema spoljnog izvora; uobičajena granica zavisi od deklaracije sredstva i propisa. Razvojna vrednost, čeka pregled agronoma.")),
    _scalar("rules.field_ops.rain_block_mm_3d", "float", G_OPS, "Rain that blocks field work (3 days)", "Kiša koja blokira rad u polju (3 dana)", "mm", 0, 200, **_no()),
    _scalar("rules.field_ops.heavy_rain_postpone_mm", "float", G_OPS, "Forecast rain at or above which fertilising and field work are postponed", "Prognozirana kiša od koje se prihrana i radovi u polju odlažu", "mm", 0, 500,
            recommended=(10, 50), basis="development",
            **_dev("Development value (25 mm within the forecast window), awaiting agronomist review. No external source is claimed.",
                   "Razvojna vrednost (25 mm u prozoru prognoze), čeka pregled agronoma. Spoljni izvor se ne tvrdi.")),
    _scalar("rules.field_ops.frost_tmin_c", "float", G_OPS, "Frost limit for sowing (minimum temperature)", "Granica mraza za setvu (minimalna temperatura)", "°C", -30, 30,
            **_no("No external source. The corpus asks for about 10 °C soil temperature at sowing, which the code does not check (needs a code change). Development value, awaiting agronomist review.",
                  "Nema spoljnog izvora. Korpus traži oko 10 °C temperature zemljišta pri setvi, što kod ne proverava (potrebna izmena koda). Razvojna vrednost, čeka pregled agronoma.")),
    _scalar("rules.field_ops.window.caution_wind_share", "float", G_OPS, "Spraying caution: share of the wind limit", "Oprez pri prskanju: udeo granice vetra", "share", 0, 1,
            **_no("Used by the 72 h window card only; not by the decision cores. " + NO_SOURCE_EN, "Koristi se samo u kartici prozora od 72 h, ne u jezgrima odluke. " + NO_SOURCE_SR)),
    _scalar("rules.field_ops.window.caution_frost_margin_c", "float", G_OPS, "Sowing caution: margin above the frost limit", "Oprez pri setvi: razmak iznad granice mraza", "°C", 0, 20,
            **_no("Used by the 72 h window card only; not by the decision cores. " + NO_SOURCE_EN, "Koristi se samo u kartici prozora od 72 h, ne u jezgrima odluke. " + NO_SOURCE_SR)),
    _scalar("rules.field_ops.window.heavy_rain_factor", "float", G_OPS, "Heavy rain: multiple of the rain limit", "Jaka kiša: umnožak granice kiše", "x", 1, 50,
            **_no("Used by the 72 h window card only; the decision core uses a fixed factor of 5 in code (needs a code change). " + NO_SOURCE_EN,
                  "Koristi se samo u kartici prozora od 72 h; jezgro odluke koristi fiksan faktor 5 u kodu (potrebna izmena koda). " + NO_SOURCE_SR)),
    # ---------------------------------------------------------------- rules.yaml: scouting, phenology
    _scalar("rules.scouting.contrast_priority", "float", G_SCOUT, "NDVI contrast (p90 - p10) that makes scouting a priority", "NDVI kontrast (p90 - p10) koji obilazak čini prioritetom", "NDVI", 0, 2, **_dev()),
    _scalar("rules.scouting.trend_priority", "float", G_SCOUT, "NDVI 14-day change that makes scouting a priority", "NDVI promena za 14 dana koja obilazak čini prioritetom", "NDVI", -2, 2, **_dev()),
    _scalar("rules.scouting.low_coverage_warning", "float", G_SCOUT, "Warn when usable pixel coverage is below", "Upozorenje kad je pokrivenost upotrebljivim pikselima ispod", "share", 0, 1, **_dev()),
    _scalar("rules.phenology.gdd_base_c", "float", G_PHEN, "Base temperature for growing degree-days", "Osnovna temperatura za toplotnu sumu", "°C", 0, 20,
            source="mcmaster", status="no_source",
            hint_en="Applied when the parcel profile is refreshed (the stored weather summary is computed with it).",
            hint_sr="Primenjuje se pri osvežavanju profila parcele (sačuvani vremenski sažetak računa se sa njom).",
            note_en="The source describes the method; that the base is 10 °C for maize was not verified in the text. Development value, awaiting agronomist review.",
            note_sr="Izvor opisuje metod; da je osnova 10 °C za kukuruz nije proveren u tekstu. Razvojna vrednost, čeka pregled agronoma."),
    Spec("rules.phenology.gdd_to_bbch", "table", G_PHEN, "Cumulative GDD since sowing to BBCH", "Zbir toplotne sume od setve do BBCH", unit="°C day",
         cols=(c("gdd_max", "float", 0, 99999, en="Up to GDD", sr="Do GDD"), c("bbch", "int", 0, 99, en="BBCH", sr="BBCH")),
         checks=("sorted:gdd_max", "last_min:gdd_max:99999"), min_items=2, max_items=20, **_no(
             "No external source (approximate lookup). The last row is the catch-all and must stay at 99999.",
             "Nema spoljnog izvora (približna tabela). Poslednji red je za sve ostalo i mora ostati 99999.")),
    Spec("rules.phenology.days_to_bbch", "table", G_PHEN, "Days since sowing to BBCH (when no GDD is available)", "Dani od setve do BBCH (kad nema toplotne sume)", unit="days",
         cols=(c("days_max", "int", 0, 9999, en="Up to day", sr="Do dana"), c("bbch", "int", 0, 99, en="BBCH", sr="BBCH")),
         checks=("sorted:days_max", "last_min:days_max:9999"), min_items=2, max_items=20, source="fao56_t11", status="partly",
         note_en="The total season length implied is in the range of Table 11 (125-180 days for grain maize); the mapping to BBCH itself is not in the source. The last row is the catch-all and must stay at 9999.",
         note_sr="Ukupna dužina sezone je u opsegu Tabele 11 (125-180 dana za kukuruz u zrnu); sama veza sa BBCH nije u izvoru. Poslednji red je za sve ostalo i mora ostati 9999."),
    # ---------------------------------------------------------------- rules.yaml: soil
    Spec("rules.soil.awc_by_texture_mm_m", "map", G_SOIL, "Available water capacity by soil texture", "Pristupačna voda po teksturi zemljišta", unit="mm/m", lo=1, hi=400,
         source="fao56_t19", status="partly",
         recommended={"sand": (50, 110), "sandy_loam": (110, 150), "loam": (130, 180), "clay_loam": (130, 180), "clay": (120, 200)},
         note_en="Values lie inside the ranges of Table 19. Clay loam and clay sit at the upper edge of the range (clay loam compared with the silty clay loam row); a higher value gives a larger irrigation dose.",
         note_sr="Vrednosti su u opsezima Tabele 19. Glinovita ilovača i glina su na gornjoj granici opsega (glinovita ilovača prema redu silty clay loam); veća vrednost daje veću dozu."),
    Spec("rules.soil.efficiency_by_system", "map", G_SOIL, "Application efficiency by irrigation system", "Efikasnost primene po sistemu navodnjavanja", unit="share", lo=0.05, hi=1.0,
         source="fao4_t8", status="verified",
         note_en="Sprinkler 0.75, drip 0.90, surface (furrow) 0.60 match Annex I, Table 8. Scheme efficiency (conveyance x application) is not modelled.",
         note_sr="Kišenje 0,75, kap po kap 0,90, površinsko (brazde) 0,60 odgovaraju Prilogu I, Tabela 8. Efikasnost šeme (provodljivost x primena) nije modelovana."),
    # ---------------------------------------------------------------- rules.yaml: plausible ranges of inputs
    # Development values: a value outside is not used (graded low, "implausible value"). Only the administrator changes them.
    _limit("soil_moisture_vwc", "Soil sensor reading: plausible range (volumetric water content)", "Očitavanje senzora vlage: verodostojan opseg (zapreminski sadržaj vode)",
           "m3/m3", 0, 1, {"0": (0, 0.05), "1": (0.6, 1.0)},
           "A sensor reading above 1 is a percentage written as a fraction (25 for 0.25). Development range, awaiting agronomist review.",
           "Očitavanje iznad 1 je procenat upisan kao razlomak (25 umesto 0,25). Razvojni opseg, čeka pregled agronoma."),
    _limit("soil_awc_mm_m", "Available water capacity: plausible range", "Pristupačna voda: verodostojan opseg", "mm/m", 1, 1000,
           {"0": (10, 50), "1": (200, 400)},
           "Table 19 gives 50-200 mm/m by texture; the range is wider on purpose and only catches wrong units (1.6 for metres). Development range, awaiting agronomist review.",
           "Tabela 19 daje 50-200 mm/m po teksturi; opseg je namerno širi i hvata samo pogrešne jedinice (1,6 za metre). Razvojni opseg, čeka pregled agronoma.",
           source="fao56_t19", status="partly"),
    _limit("irrigation_efficiency", "Application efficiency: plausible range (greater than the lower end, at most the upper)", "Efikasnost primene: verodostojan opseg (veća od donje granice, najviše gornja)", "share", 0, 1,
           {"0": (0, 0.1), "1": (0.95, 1.0)},
           "An efficiency of 0 is never plausible (the lower end itself is excluded) and one above 1 is a percentage. Development range, awaiting agronomist review.",
           "Efikasnost 0 nikad nije verodostojna (sama donja granica je isključena), a iznad 1 je procenat. Razvojni opseg, čeka pregled agronoma."),
    _limit("root_depth_m", "Effective root depth: plausible range", "Efektivna dubina korena: verodostojan opseg", "m", 0.01, 5,
           {"0": (0.05, 0.3), "1": (1.7, 3.0)},
           "Table 22 gives 1.0-1.7 m for maize at full development. Development range, awaiting agronomist review.",
           "Tabela 22 daje 1,0-1,7 m za kukuruz u punom razvoju. Razvojni opseg, čeka pregled agronoma.",
           source="fao56_t22", status="partly"),
    _limit("precipitation_mm", "Rain in the 3- or 7-day window: plausible range", "Kiša u prozoru od 3 ili 7 dana: verodostojan opseg", "mm", 0, 5000,
           {"0": (0, 0), "1": (300, 1000)},
           "A negative rain is never plausible (it would enlarge the dose). Development range, awaiting agronomist review.",
           "Negativna kiša nikad nije verodostojna (povećala bi dozu). Razvojni opseg, čeka pregled agronoma."),
    _limit("et0_mm", "Reference evapotranspiration over 7 days: plausible range", "Referentna evapotranspiracija za 7 dana: verodostojan opseg", "mm", 0, 500,
           {"0": (0, 0), "1": (70, 150)}, "Development range, awaiting agronomist review.", "Razvojni opseg, čeka pregled agronoma."),
    _limit("yield_target_t_ha", "Target yield: plausible range", "Ciljni prinos: verodostojan opseg", "t/ha", 0, 100,
           {"0": (0, 0), "1": (20, 60)}, "Development range, awaiting agronomist review.", "Razvojni opseg, čeka pregled agronoma."),
    _limit("fertilizer_rate_kg_ha", "Fertiliser rate in one record: plausible range", "Doza đubriva u jednom zapisu: verodostojan opseg", "kg/ha", 0, 10000,
           {"0": (0, 0), "1": (1000, 3000)}, "Development range, awaiting agronomist review.", "Razvojni opseg, čeka pregled agronoma."),
    # ---------------------------------------------------------------- rules.yaml: optional inputs
    _scalar("rules.optional_inputs.recent_irrigation_days", "int", G_OPT, "Irrigation this recent implies a moist root zone", "Navodnjavanje ovako skoro znači vlažnu zonu korena", "days", 0, 30, **_no()),
    _scalar("rules.optional_inputs.recent_irrigation_min_mm", "float", G_OPT, "... and at least this deep", "... i bar ovolike dubine", "mm", 0, 200, **_no()),
    _scalar("rules.optional_inputs.wilting_hint_days", "int", G_OPT, "Reported wilting this recent hints at dry soil", "Prijavljeno uvenuće ovako skoro nagoveštava suvo zemljište", "days", 0, 30, **_no()),
    _scalar("rules.optional_inputs.field_event_days", "int", G_OPT, "Hail, lodging or waterlogging this recent makes scouting a priority", "Grad, poleganje ili zadržavanje vode ovako skoro čine obilazak prioritetom", "days", 0, 60, **_no()),
    Spec("rules.optional_inputs.priority_events", "list", G_OPT, "Field events that make scouting a priority", "Događaji koji obilazak čine prioritetom", max_items=12, **_dev()),
    Spec("rules.optional_inputs.referral_events", "list", G_OPT, "Field events referred to an expert", "Događaji koji se upućuju stručnjaku", max_items=12, **_dev()),
    Spec("rules.optional_inputs.legumes", "list", G_OPT, "Previous crops counted as legumes", "Predusevi koji se računaju kao leguminoze", max_items=24, **_dev()),
    _scalar("rules.optional_inputs.manure_credit_days", "int", G_OPT, "Manure counts for this many days", "Stajnjak se računa ovoliko dana", "days", 0, 1500, **_no()),
    Spec("rules.optional_inputs.ph_range", "pair", G_OPT, "Soil pH range without a constraint note", "Opseg pH zemljišta bez napomene o ograničenju", unit="pH", lo=3, hi=10, **_no()),
    Spec("rules.optional_inputs.humus_bands_pct", "pair", G_OPT, "Humus bands (low / medium / high soil supply)", "Granice humusa (niska / srednja / visoka obezbeđenost)", unit="%", lo=0, hi=30,
         **_no("No external source; official supply classes in the region were not checked. Development value, awaiting agronomist review.",
               "Nema spoljnog izvora; zvanične klase obezbeđenosti u regionu nisu proverene. Razvojna vrednost, čeka pregled agronoma.")),
    _scalar("rules.optional_inputs.fao_reference", "int", G_OPT, "Maturity group (FAO) the GDD thresholds are for", "FAO grupa za koju važe pragovi toplotne sume", "FAO", 100, 900, **_no()),
    _scalar("rules.optional_inputs.fao_gdd_per_100", "float", G_OPT, "Scaling of thermal time per 100 FAO units", "Skaliranje toplotne sume na 100 FAO jedinica", "share", 0, 1, **_no()),
    Spec("rules.optional_inputs.n_content", "map", G_OPT, "Share of nitrogen in common fertiliser products", "Udeo azota u uobičajenim đubrivima", unit="share", lo=0, hi=1, source="stoich", status="no_source",
         recommended={"urea": (0, 0.4665), "an": (0, 0.35), "map": (0, 0.1218), "dap": (0, 0.2121)},
         limit={"urea": (0, 0.4665), "an": (0, 0.35), "map": (0, 0.1218), "dap": (0, 0.2121)},
         note_en="No source for the product values (labels were not opened). The upper limits shown are the stoichiometric maxima of the pure compound; the defaults stay below them.",
         note_sr="Za vrednosti proizvoda nema izvora (deklaracije nisu otvorene). Prikazane gornje granice su stehiometrijski maksimumi čistog jedinjenja; podrazumevane vrednosti su ispod njih."),
    # ---------------------------------------------------------------- kc_maize.yaml
    Spec("kc_maize.kc", "table", G_KC, "Single crop coefficient Kc by BBCH range (maize)", "Koeficijent kulture Kc po opsegu BBCH (kukuruz)", unit="Kc",
         cols=(c("bbch_min", "int", 0, 99, en="BBCH from", sr="BBCH od"), c("bbch_max", "int", 0, 99, en="BBCH to", sr="BBCH do"),
               c("kc", "float", 0, 2, en="Kc", sr="Kc"), c("stage", "str", optional=True, en="Stage", sr="Faza")),
         checks=("kc_ranges",), min_items=2, max_items=10, source="fao56_t12", status="partly", recommended={"kc": (0.30, 1.20)},
         note_en="Kc ini 0.30 (cereals value; footnote 1: higher under frequent wetting) and Kc mid 1.20 match Table 12. Kc end 0.60 is inside the source range 0.60-0.35, but the source interpolates through the late stage and the stepwise value understates ETc early in it. The development value 0.75 is the midpoint of the interpolation, not a table value. The BBCH limits are an assumption. The climate correction (eq. 62) is not applied. Ranges must be contiguous from BBCH 0. The recommended range 0.30-1.20 spans the maize values of Table 12 (ini 0.30, mid 1.20, end 0.60-0.35); the limit is that range widened by a quarter of its width.",
         note_sr="Kc ini 0,30 (vrednost grupe žitarica; fusnota 1: raste kod čestog kvašenja) i Kc mid 1,20 odgovaraju Tabeli 12. Kc end 0,60 je u opsegu izvora 0,60-0,35, ali izvor interpoliše kroz kasnu fazu pa stepenasta vrednost potcenjuje ETc na početku te faze. Razvojna vrednost 0,75 je sredina interpolacije, a ne vrednost iz tabele. Granice BBCH su pretpostavka. Korekcija klime (jedn. 62) nije primenjena. Opsezi moraju biti susedni od BBCH 0. Preporučeni opseg 0,30-1,20 obuhvata vrednosti Tabele 12 za kukuruz (ini 0,30, mid 1,20, end 0,60-0,35); granica je taj opseg proširen za četvrtinu širine."),
    # ---------------------------------------------------------------- thresholds.yaml (q): ndvi and soil analysis have their own status
    Spec("thresholds.inputs.ndvi_latest.grades", "table", G_Q, "Reliability grades: {name}", "Stepeni pouzdanosti: {name}", cols=GRADE_COLS, max_items=8, user=False, source="sentiwiki", status="partly",
         note_en="The 5-day limit matches the Sentinel-2 revisit period at the equator; the other ages and coverages are engineering choices. Grades are tried top to bottom; the first that holds wins.",
         note_sr="Granica od 5 dana poklapa se sa periodom ponovnog snimanja Sentinel-2 na ekvatoru; ostale starosti i pokrivenosti su inženjerski izbor. Stepeni se probaju odozgo; prvi koji važi pobeđuje."),
    Spec("thresholds.inputs.ndvi_spatial_contrast.grades", "table", G_Q, "Reliability grades: {name}", "Stepeni pouzdanosti: {name}", cols=GRADE_COLS, max_items=8, user=False, source="sentiwiki", status="partly",
         note_en="The 5-day limit matches the Sentinel-2 revisit period at the equator; the other ages and coverages are engineering choices.",
         note_sr="Granica od 5 dana poklapa se sa periodom ponovnog snimanja Sentinel-2 na ekvatoru; ostale starosti i pokrivenosti su inženjerski izbor."),
    Spec("thresholds.inputs.soil_analysis.grades", "table", G_Q, "Reliability grades: {name}", "Stepeni pouzdanosti: {name}", cols=GRADE_COLS, max_items=8, user=False, **_no()),
    Spec("thresholds.inputs.ndvi_latest.missing_after_days", "int", G_Q, "Treated as missing after (days): {name}", "Smatra se da nedostaje posle (dani): {name}", unit="days", lo=1, hi=36500, user=False,
         source="sentiwiki", status="partly", note_en="Engineering choice; see the grades of this input.", note_sr="Inženjerski izbor; vidi stepene ovog ulaza."),
    Spec("thresholds.inputs.ndvi_spatial_contrast.missing_after_days", "int", G_Q, "Treated as missing after (days): {name}", "Smatra se da nedostaje posle (dani): {name}", unit="days", lo=1, hi=36500, user=False,
         source="sentiwiki", status="partly", note_en="Engineering choice; see the grades of this input.", note_sr="Inženjerski izbor; vidi stepene ovog ulaza."),
    Spec("thresholds.inputs.*.grades", "table", G_Q, "Reliability grades: {name}", "Stepeni pouzdanosti: {name}", cols=GRADE_COLS, max_items=8, user=False, **_dev(
        "Development value (initial threshold, not locked), awaiting agronomist review. No external source is claimed.",
        "Razvojna vrednost (početni prag, nije zaključan), čeka pregled agronoma. Spoljni izvor se ne tvrdi.")),
    Spec("thresholds.inputs.*.missing_after_days", "int", G_Q, "Treated as missing after (days): {name}", "Smatra se da nedostaje posle (dani): {name}", unit="days", lo=1, hi=36500, user=False, **_dev()),
    Spec("thresholds.inputs.*.default", "enum", G_Q, "Grade of a value that matches no grade: {name}", "Stepen vrednosti koja ne odgovara nijednom stepenu: {name}", choices=RELIABILITY, user=False, **_dev()),
    # ---------------------------------------------------------------- asking.yaml
    Spec("asking.max_questions", "int", G_ASK, "Most follow-up questions per conversation", "Najviše dopunskih pitanja u razgovoru", lo=0, hi=5, user=False, **_dev()),
    Spec("asking.inputs.*.user_obtainable", "bool", G_ASK, "The user can supply this input: {name}", "Korisnik može da navede ovaj ulaz: {name}", user=False, **_dev()),
    Spec("asking.inputs.*.cost", "int", G_ASK, "Cost of asking (relative): {name}", "Cena pitanja (relativna): {name}", lo=0, hi=20, user=False, **_dev()),
    Spec("asking.inputs.*.plausible_values", "list", G_ASK, "Plausible answers (decision sensitivity): {name}", "Mogući odgovori (osetljivost odluke): {name}", item_kind="scalar", max_items=12, user=False, **_dev(
        "Development value. Note: an AWC answer of 110 is not in the texture table and is graded as low by the band limits.",
        "Razvojna vrednost. Napomena: odgovor AWC 110 nije u tabeli teksture i prema granicama pojasa je \"niska\".")),
    Spec("asking.inputs.*.question_sr", "str", G_ASK, "Question text (local language): {name}", "Tekst pitanja (lokalni jezik): {name}", max_len=400, user=False, **_dev()),
    Spec("asking.inputs.*.how_to_obtain_sr", "str", G_ASK, "How to obtain the answer (local language): {name}", "Kako doći do odgovora (lokalni jezik): {name}", max_len=1000, user=False, **_dev()),
    # ---------------------------------------------------------------- requirements.yaml
    Spec("requirements.advice_types.*.risk", "enum", G_REQ, "Risk class of the advice: {name}", "Klasa rizika saveta: {name}", choices=("low", "medium", "high"), user=False, **_dev()),
    Spec("requirements.advice_types.*.quantity", "bool", G_REQ, "The advice carries a quantity: {name}", "Savet nosi količinu: {name}", user=False, **_dev()),
    Spec("requirements.advice_types.*.required", "table", G_REQ, "Required inputs: {name}", "Neophodni ulazi: {name}", cols=(INPUT_COL, MINREL), max_items=12, user=False, **_dev()),
    Spec("requirements.advice_types.*.one_of", "groups", G_REQ, "Alternative groups (one group must be satisfied): {name}", "Alternativne grupe (mora biti zadovoljena jedna): {name}",
         cols=(INPUT_COL, MINREL), max_items=6, user=False, **_dev("Each group lists inputs that are all needed together; one satisfied group is enough. Development value, awaiting agronomist review.",
                                                                    "Svaka grupa navodi ulaze koji su zajedno potrebni; dovoljna je jedna zadovoljena grupa. Razvojna vrednost, čeka pregled agronoma.")),
    Spec("requirements.advice_types.*.desirable", "list", G_REQ, "Desirable inputs: {name}", "Poželjni ulazi: {name}", choices="inputs", max_items=12, user=False, **_dev()),
    Spec("requirements.degrade.*", "enum", G_REQ, "Falls back to this advice type: {name}", "Spušta se na ovaj tip saveta: {name}", choices="advice_types", user=False, **_dev()),
    # ---------------------------------------------------------------- parcel_features.yaml
    Spec("parcel_features.schema_version", "int", G_PF, "Schema version of the parcel features contract", "Verzija šeme ugovora o pokazateljima parcele",
         readonly=("The version of the data contract that the validator enforces; changing it would reject every document.",
                   "Verzija ugovora o podacima koju validator nameće; izmena bi odbila svaki dokument.")),
    Spec("parcel_features.*.status", "str", G_PF, "Status label: {name}", "Oznaka statusa: {name}",
         readonly=("A recorded label of the review state; it is not read by any rule.", "Zabeležena oznaka stanja provere; nijedno pravilo je ne čita.")),
    Spec("parcel_features.ndvi_quality.enabled", "bool", G_PF, "NDVI observation quality rules on", "Pravila kvaliteta NDVI opažanja uključena", user=False, **_dev()),
    Spec("parcel_features.ndvi_quality.max_masked_share_for_high", "float", G_PF, "Cloud and shadow share above which the grade is at most medium", "Udeo oblaka i senke iznad kog je ocena najviše srednja", "share", 0, 1, user=False, **_dev()),
    Spec("parcel_features.ndvi_quality.max_masked_share_for_medium", "float", G_PF, "Cloud and shadow share above which the grade is low", "Udeo oblaka i senke iznad kog je ocena niska", "share", 0, 1, user=False, **_dev()),
    Spec("parcel_features.ndvi_quality.max_mixed_share_for_high", "float", G_PF, "Boundary (mixed) pixel share above which the grade is at most medium", "Udeo graničnih (mešanih) piksela iznad kog je ocena najviše srednja", "share", 0, 1, user=False, **_dev()),
    Spec("parcel_features.ndvi_quality.max_mixed_share_for_medium", "float", G_PF, "Boundary (mixed) pixel share above which the grade is low", "Udeo graničnih (mešanih) piksela iznad kog je ocena niska", "share", 0, 1, user=False, **_dev()),
    Spec("parcel_features.ndvi_quality.min_interior_px_for_high", "int", G_PF, "Fewer interior valid pixels: at most medium", "Manje unutrašnjih ispravnih piksela: najviše srednja", "pixels", 0, 100000, user=False, source="arith", status="development",
         note_en="The arithmetic is right (30 pixels of 100 m2 = 0.3 ha); the threshold itself is not derived from a source. Development value, awaiting agronomist review.",
         note_sr="Aritmetika je tačna (30 piksela od 100 m2 = 0,3 ha); sam prag nije izveden iz izvora. Razvojna vrednost, čeka pregled agronoma."),
    Spec("parcel_features.ndvi_quality.min_interior_px_for_medium", "int", G_PF, "Fewer interior valid pixels: low", "Manje unutrašnjih ispravnih piksela: niska", "pixels", 0, 100000, user=False, source="arith", status="development",
         note_en="The arithmetic is right (10 pixels = 0.1 ha); the threshold itself is not derived from a source. Development value, awaiting agronomist review.",
         note_sr="Aritmetika je tačna (10 piksela = 0,1 ha); sam prag nije izveden iz izvora. Razvojna vrednost, čeka pregled agronoma."),
    Spec("parcel_features.ndvi_quality.cloud_flag_caps_at", "enum", G_PF, "Highest grade when cloud or shadow touches the parcel", "Najviša ocena kad oblak ili senka dodiruje parcelu", choices=RELIABILITY, user=False, **_dev()),
    Spec("parcel_features.ndvi_quality.exclude_temporal_outliers", "bool", G_PF, "Leave screened outliers out of the NDVI summary", "Izostavi odbačena odstupanja iz NDVI sažetka", user=False, **_dev()),
    Spec("parcel_features.stage_conflict.enabled", "bool", G_PF, "Stage conflict rule on", "Pravilo sukoba faza uključeno", user=False, **_dev()),
    Spec("parcel_features.stage_conflict.tolerance_bbch", "int", G_PF, "Tolerance outside the satellite stage interval", "Tolerancija izvan satelitskog intervala faze", "BBCH", 0, 99, user=False, **_dev()),
    Spec("parcel_features.stage_conflict.max_estimate_age_days", "int", G_PF, "Satellite estimate older than this is not compared", "Satelitska procena starija od ovoga se ne poredi", "days", 0, 365, user=False, **_dev()),
    Spec("parcel_features.stage_conflict.cap_reliability_at", "enum", G_PF, "Stage reliability cap on conflict", "Ograničenje pouzdanosti faze pri sukobu", choices=RELIABILITY, user=False, **_dev()),
    Spec("parcel_features.crop_plausibility.enabled", "bool", G_PF, "Crop plausibility check on (classifier not validated)", "Provera verodostojnosti useva uključena (klasifikator nije validiran)", user=False,
         status="development", note_en="Not validated: the producer's classifier has no transfer check. Off by default; turning it on lets an unvalidated signal lower a reliability grade.",
         note_sr="Nije validirano: klasifikator proizvođača nema proveru prenosivosti. Podrazumevano isključeno; uključivanje dozvoljava nevalidiranom signalu da spusti ocenu pouzdanosti."),
    Spec("parcel_features.crop_plausibility.cap_reliability_at", "enum", G_PF, "Crop identity cap on discrepancy", "Ograničenje identiteta useva pri neslaganju", choices=RELIABILITY, user=False, **_dev()),
    Spec("parcel_features.field_markers.enabled", "bool", G_PF, "Bare-soil and harvest markers on (not validated)", "Markeri golog zemljišta i žetve uključeni (nisu validirani)", user=False,
         status="development", note_en="Not validated. Off by default; turning it on lets an unvalidated marker lower a reliability grade.",
         note_sr="Nije validirano. Podrazumevano isključeno; uključivanje dozvoljava nevalidiranom markeru da spusti ocenu pouzdanosti."),
    Spec("parcel_features.field_markers.bare_soil_conflict_min_bbch", "int", G_PF, "Bare soil is a conflict from this stage", "Golo zemljište je sukob od ove faze", "BBCH", 0, 99, user=False, **_dev()),
    Spec("parcel_features.field_markers.min_reliability_for_conflict", "enum", G_PF, "Lowest marker grade that counts as a conflict", "Najniža ocena markera koja se računa kao sukob", choices=RELIABILITY, user=False, **_dev()),
    Spec("parcel_features.field_markers.harvest_conflicting_advice", "list", G_PF, "Advice types in conflict with a detected harvest", "Tipovi saveta u sukobu sa otkrivenom žetvom", choices="advice_types", max_items=8, user=False, **_dev()),
    Spec("parcel_features.field_markers.cap_reliability_at", "enum", G_PF, "Stage reliability cap on a marker conflict", "Ograničenje pouzdanosti faze pri sukobu markera", choices=RELIABILITY, user=False, **_dev()),
    Spec("parcel_features.field_markers.grades", "table", G_PF, "Reliability of the field state from the producer's confidence", "Pouzdanost stanja njive iz pouzdanosti proizvođača",
         cols=(RELIAB, c("min_confidence", "float", 0, 1, en="Min confidence", sr="Najmanja pouzdanost proizvođača"),
               c("data_sufficiency", "list", optional=True, en="Data sufficiency", sr="Dovoljnost podataka")), max_items=6, user=False, **_dev()),
    Spec("parcel_features.field_markers.default", "enum", G_PF, "Field-state grade when no grade matches", "Ocena stanja njive kad nijedna ne odgovara", choices=RELIABILITY, user=False, **_dev()),
]

# Cross-parameter relations on the merged values: (key a, operator, key b, code). Checked on every write.
RELATIONS = [
    ("parcel_features.ndvi_quality.max_masked_share_for_high", "<=", "parcel_features.ndvi_quality.max_masked_share_for_medium", "relation_masked"),
    ("parcel_features.ndvi_quality.max_mixed_share_for_high", "<=", "parcel_features.ndvi_quality.max_mixed_share_for_medium", "relation_mixed"),
    ("parcel_features.ndvi_quality.min_interior_px_for_high", ">=", "parcel_features.ndvi_quality.min_interior_px_for_medium", "relation_interior"),
]

PROTOCOL_REASON = (
    "Protocol file: it defines the experiment (variants, analysis plan, model settings, controlled vocabulary) and is locked. "
    "Evaluation reads the files only; web settings never reach it.",
    "Protokolarna datoteka: definiše eksperiment (varijante, plan analize, podešavanja modela, kontrolisani rečnik) i zaključana je. "
    "Evaluacija čita samo datoteke; podešavanja sa veba do nje nikad ne dopiru.")


# ---------------------------------------------------------------------------------------------------------------------
# Expansion against the files
# ---------------------------------------------------------------------------------------------------------------------
@dataclass
class Entry:
    key: str
    spec: Spec
    name: str                                     # what the `*` matched (an input or an advice type), or ""
    file: str
    default: Any = field(default=None)
    _ranges: Any = field(default=None, repr=False, compare=False)

    @property
    def editable(self) -> bool:
        return self.spec.readonly is None and not self.blocked()

    def blocked(self) -> Optional[Tuple[str, str]]:
        """Reason an entry that looks editable cannot be: asking a question needs its text."""
        if self.spec.path == "asking.inputs.*.user_obtainable":
            node = config.load_file("asking")["inputs"].get(self.name) or {}
            if "question_sr" not in node:
                return ("This input has no question text in the file, so it cannot be made askable here (edit the file).",
                        "Ovaj ulaz nema tekst pitanja u datoteci, pa ovde ne može postati pitanje (izmeniti datoteku).")
        return None


def _match(pattern: str, path: str) -> Optional[str]:
    """None when the path does not match; otherwise what the `*` matched ("" when there is none)."""
    a, b = pattern.split("."), path.split(".")
    if len(a) != len(b):
        return None
    name = ""
    for x, y in zip(a, b):
        if x == "*":
            name = y
        elif x != y:
            return None
    return name


def _find_spec(path: str) -> Optional[Tuple[Spec, str]]:
    for spec in SPECS:
        name = _match(spec.path, path)
        if name is not None:
            return spec, name
    return None


def _walk(node: Any, path: str, file: str, out: List[Entry], bad: List[str]) -> None:
    found = _find_spec(path)
    if found is not None:
        out.append(Entry(path, found[0], found[1], file, copy.deepcopy(node)))
    elif isinstance(node, dict) and node:
        for k, v in node.items():
            _walk(v, path + "." + str(k), file, out, bad)
    else:
        bad.append(path)


@lru_cache(maxsize=8)
def _expand(config_dir: str) -> Tuple[Tuple[Entry, ...], Tuple[str, ...]]:
    out: List[Entry] = []
    bad: List[str] = []
    for f in EDITABLE_FILES:
        data = config.load_file(f)
        for k, v in data.items():
            _walk(v, f + "." + str(k), f, out, bad)
    return tuple(out), tuple(bad)


def entries() -> List[Entry]:
    return list(_expand(str(config.config_dir()))[0])


def entry_map() -> Dict[str, Entry]:
    return {e.key: e for e in entries()}


def uncovered() -> List[str]:
    """Leaves of the editable files that no declaration covers (must be empty)."""
    return list(_expand(str(config.config_dir()))[1])


def unused_specs() -> List[str]:
    """Declarations that match nothing in the files (stale)."""
    used = {e.spec.path for e in entries()}
    return [s.path for s in SPECS if s.path not in used]


def reset_cache() -> None:
    _expand.cache_clear()


# ---------------------------------------------------------------------------------------------------------------------
# Labels, choices, bounds
# ---------------------------------------------------------------------------------------------------------------------
def _name_label(entry: Entry, lang: str) -> str:
    names = labels_en.INPUTS if lang == "en" else labels.INPUTS
    advice = labels_en.ADVICE_TYPES if lang == "en" else labels.ADVICE_TYPES
    return names.get(entry.name) or advice.get(entry.name) or entry.name


def label(entry: Entry) -> Dict[str, str]:
    s = entry.spec
    return {"en": s.en.replace("{name}", _name_label(entry, "en")), "sr": s.sr.replace("{name}", _name_label(entry, "sr"))}


def dynamic_choices(name: str) -> List[str]:
    if name == "inputs":
        return sorted(config.load_file("thresholds")["inputs"])
    if name == "advice_types":
        return sorted(config.load_file("requirements")["advice_types"])
    raise KeyError(name)


def choices_of(obj: Any) -> Optional[List[str]]:
    ch = obj.choices
    if ch is None:
        return None
    return dynamic_choices(ch) if isinstance(ch, str) else list(ch)


def hard_bounds(entry: Entry) -> Dict[str, Any]:
    """The physical bounds of the registry (what the quantity can be at all)."""
    s = entry.spec
    return {"min": s.lo, "max": s.hi, "min_items": s.min_items, "max_items": s.max_items,
            "columns": {col.name: {"min": col.lo, "max": col.hi} for col in s.cols if col.lo is not None or col.hi is not None}}


# ---------------------------------------------------------------------------------------------------------------------
# Default limits and recommended ranges
#
# Three nested ranges for every numeric value:  recommended  inside  default limit  inside  physical bounds (Spec.lo/hi).
# - physical bounds: the quantity cannot be outside them (a share is in 0..1); never changed by a setting;
# - default limit: what the registry accepts until an administrator sets the limit of that parameter (the administrator
#   may widen it up to the physical bounds or narrow it); a value outside it is refused;
# - recommended: a value between the recommended range and the limit is accepted with a warning.
# Where the cited source gives a range, `Spec.recommended` is that range (basis "source") and the default limit is the
# range widened by a quarter of its width on each side, unless the declaration gives its own `limit`. Where no source
# gives a range, both are a conservative band around the default in the file (basis "development"): a development
# limit, never a citation. The bands are derived here, so a change of a default in a file moves its band with it.
# ---------------------------------------------------------------------------------------------------------------------
WIDEN = 0.25
RATIO_REC, RATIO_LIM = (0.7, 1.3), (0.5, 2.0)          # around a positive default: -30 % .. +30 %, and /2 .. x2
ABS_BANDS = {"BBCH": (5, 15), "°C": (2, 5), "pH": (0.5, 1.0), "NDVI": (0.05, 0.15)}   # (recommended, limit) half widths
ABS_SPAN = (0.05, 0.15)                                 # a default of zero or below, no unit: share of the physical span


def _clip(v: float, lo: Optional[float], hi: Optional[float]) -> float:
    if lo is not None:
        v = max(v, lo)
    if hi is not None:
        v = min(v, hi)
    return v


def _pretty(v: float, integer: bool, up: bool) -> Any:
    if integer:
        return int(math.ceil(v) if up else math.floor(v))
    return round(v, 4)


def _auto(values: Sequence[float], lo: Optional[float], hi: Optional[float], integer: bool, unit: str,
          name: str = "") -> Tuple[List[Any], List[Any]]:
    """(recommended, limit) as [lo, hi] pairs: a development band around the default value(s)."""
    vmin, vmax = min(values), max(values)
    add = ABS_BANDS.get(unit) or ((5, 15) if "bbch" in name else None)
    if add is None and vmin <= 0:
        span = (hi - lo) if lo is not None and hi is not None else (abs(vmax - vmin) or 1.0)
        add = (ABS_SPAN[0] * span, ABS_SPAN[1] * span)
    out = []
    for k in (0, 1):
        if add is not None:
            a, b = vmin - add[k], vmax + add[k]
        else:
            r = (RATIO_REC, RATIO_LIM)[k]
            a, b = vmin * r[0], vmax * r[1]
        a, b = _clip(a, lo, hi), _clip(b, lo, hi)
        out.append([_pretty(a, integer, False), _pretty(b, integer, True)])
    rec, lim = out
    rec = [min(rec[0], vmin), max(rec[1], vmax)]
    lim = [min(lim[0], rec[0]), max(lim[1], rec[1])]
    return rec, lim


def _widen(rng: Sequence[float], lo: Optional[float], hi: Optional[float], integer: bool) -> List[Any]:
    """The source's range widened by a quarter of its width on each side, rounded outward to a readable number."""
    w = (rng[1] - rng[0]) * WIDEN
    out = []
    for v, up in ((_clip(rng[0] - w, lo, hi), False), (_clip(rng[1] + w, lo, hi), True)):
        if integer:
            out.append(_pretty(v, True, up))
        else:
            q = 10.0 if abs(v) >= 1 else 1000.0
            out.append(round((math.ceil if up else math.floor)(v * q) / q, 3))
    return [_clip(out[0], lo, hi), _clip(out[1], lo, hi)]


def _numbers(entry: Entry) -> Dict[str, Tuple[List[float], Optional[float], Optional[float], bool, str]]:
    """slot -> (default values, physical lo, hi, integer?, column name) for every numeric slot of the entry."""
    s, d = entry.spec, entry.default
    if s.kind in ("int", "float"):
        return {"": ([d], s.lo, s.hi, s.kind == "int", "")}
    if s.kind == "pair":
        return {str(i): ([d[i]], s.lo, s.hi, s.unit == "BBCH", "") for i in (0, 1)}
    if s.kind == "map":
        return {k: ([v], s.lo, s.hi, False, "") for k, v in d.items()}
    if s.kind in ("table", "groups"):
        rows = [r for g in d for r in g] if s.kind == "groups" else d
        out = {}
        for col in s.cols:
            if col.kind in ("int", "float"):
                vals = [r[col.name] for r in rows if col.name in r]
                if vals:
                    out[col.name] = (vals, col.lo, col.hi, col.kind == "int", col.name)
        return out
    return {}


def _explicit(spec_value: Any, slot: str, kind: str) -> Optional[Sequence[float]]:
    if spec_value is None:
        return None
    if isinstance(spec_value, dict):
        return spec_value.get(slot)
    return spec_value if kind in ("int", "float", "pair") else None


def ranges(entry: Entry) -> Dict[str, Dict[str, Any]]:
    """slot -> {"recommended": [lo, hi], "limit": [lo, hi], "basis": "source" | "development"}; the slot is "" for a
    number, "0"/"1" for the two ends of a pair, the key of a map, the column of a table. Empty for values that are not
    numbers (switches, choices, texts, lists)."""
    if entry._ranges is not None:
        return entry._ranges
    s, out = entry.spec, {}
    for slot, (vals, lo, hi, integer, name) in _numbers(entry).items():
        rec_x, lim_x = _explicit(s.recommended, slot, s.kind), _explicit(s.limit, slot, s.kind)
        auto_rec, auto_lim = _auto(vals, lo, hi, integer, s.unit, name)
        if rec_x is not None:
            rec = [rec_x[0], rec_x[1]]
            lim = [lim_x[0], lim_x[1]] if lim_x is not None else _widen(rec, lo, hi, integer)
            basis = "development" if s.basis == "development" else "source"
        else:
            rec, lim, basis = auto_rec, auto_lim, "development"
            if lim_x is not None:
                lim = [lim_x[0], lim_x[1]]
        out[slot] = {"recommended": rec, "limit": lim, "basis": basis}
    entry._ranges = out
    return out


def _slot_bound(entry: Entry, slot: str, lo_hard: Optional[float], hi_hard: Optional[float],
                admin: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Effective bound of one slot: the administrator's min/max where set, else the default limit; never beyond the
    physical bounds."""
    lim = (ranges(entry).get(slot) or {}).get("limit") or [None, None]
    admin = admin or {}
    lo = admin["min"] if admin.get("min") is not None else lim[0]
    hi = admin["max"] if admin.get("max") is not None else lim[1]
    return {"min": None if lo is None and lo_hard is None else _clip(lo if lo is not None else lo_hard, lo_hard, hi_hard),
            "max": None if hi is None and hi_hard is None else _clip(hi if hi is not None else hi_hard, lo_hard, hi_hard)}


def merged_bounds(entry: Entry, limit: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The bounds that apply now: the default limit (or the administrator's limit where one was set), inside the
    physical bounds. `elements` (pair), `keys` (map) and `columns` (table) hold the bound of every slot."""
    s, hb, limit = entry.spec, hard_bounds(entry), limit or {}
    b = dict(hb, columns={})
    admin = {"min": limit.get("min"), "max": limit.get("max")}
    if s.kind in ("int", "float"):
        b.update(_slot_bound(entry, "", s.lo, s.hi, admin))
    elif s.kind == "pair":
        b["elements"] = [_slot_bound(entry, str(i), s.lo, s.hi, admin) for i in (0, 1)]
    elif s.kind == "map":
        b["keys"] = {k: _slot_bound(entry, k, s.lo, s.hi, admin) for k in entry.default}
    if s.kind in ("pair", "map"):
        slots = b["elements"] if s.kind == "pair" else list(b["keys"].values())
        mins, maxs = [x["min"] for x in slots if x["min"] is not None], [x["max"] for x in slots if x["max"] is not None]
        b["min"], b["max"] = (min(mins) if mins else None), (max(maxs) if maxs else None)
    for col in s.cols:
        if col.kind in ("int", "float"):
            b["columns"][col.name] = _slot_bound(entry, col.name, col.lo, col.hi, (limit.get("columns") or {}).get(col.name))
    for k, pick in (("min_items", max), ("max_items", min)):
        if limit.get(k) is not None:
            b[k] = pick(b[k], limit[k])
    return b


# ---------------------------------------------------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------------------------------------------------
class Invalid(Exception):
    def __init__(self, code: str, **params: Any):
        super().__init__(code)
        self.code = code
        self.params = params


def _num(v: Any, kind: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or (isinstance(v, float) and not math.isfinite(v)):
        raise Invalid("type", expected=kind)
    if kind == "int":
        if isinstance(v, float):
            if v != int(v):
                raise Invalid("type", expected="int")
            return int(v)
        return v
    return float(v) if isinstance(v, float) else v


def _in_range(v: float, lo: Optional[float], hi: Optional[float]) -> None:
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        raise Invalid("range", min=lo, max=hi)


def _token(v: Any, ch: Optional[Sequence[str]], kind: str = "token") -> Any:
    if kind == "scalar" and isinstance(v, (int, float)) and not isinstance(v, bool):
        if isinstance(v, float) and not math.isfinite(v):
            raise Invalid("type", expected="scalar")
        return v
    if not isinstance(v, str) or not TOKEN.match(v):
        raise Invalid("type", expected="token")
    if ch is not None and v not in ch:
        raise Invalid("choice", allowed=list(ch))
    return v


def _col_value(col: Col, v: Any, bounds: Dict[str, Any]) -> Any:
    cb = bounds["columns"].get(col.name, {})
    if col.kind in ("int", "float"):
        out = _num(v, col.kind)
        _in_range(out, cb.get("min"), cb.get("max"))
        return out
    if col.kind == "enum":
        if v not in (choices_of(col) or []):
            raise Invalid("choice", allowed=choices_of(col))
        return v
    if col.kind == "str":
        if not isinstance(v, str) or len(v) > 80 or any(ord(ch) < 32 for ch in v):
            raise Invalid("type", expected="str")
        return v
    if col.kind == "bool":
        if not isinstance(v, bool):
            raise Invalid("type", expected="bool")
        return v
    if col.kind == "list":
        if not isinstance(v, list) or len(v) > MAX_ITEMS:
            raise Invalid("type", expected="list")
        ch = choices_of(col)
        out = [_token(x, ch) for x in v]
        if len(set(out)) != len(out):
            raise Invalid("duplicate")
        return out
    raise Invalid("type", expected=col.kind)


def _rows(spec: Spec, rows: Any, bounds: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(rows, list):
        raise Invalid("type", expected="table")
    out = []
    names = {col.name: col for col in spec.cols}
    for row in rows:
        if not isinstance(row, dict) or not set(row) <= set(names):
            raise Invalid("shape")
        clean = {}
        for col in spec.cols:
            if col.name not in row or row[col.name] is None:
                if not col.optional:
                    raise Invalid("shape", missing=col.name)
                continue
            clean[col.name] = _col_value(col, row[col.name], bounds)
        out.append(clean)
    return out


def _check(rule: str, rows: List[Dict[str, Any]]) -> None:
    kind, *args = rule.split(":")
    if kind == "sorted":
        col = args[0]
        if any(rows[i][col] >= rows[i + 1][col] for i in range(len(rows) - 1)):
            raise Invalid("order", column=col)
    elif kind == "last_min":
        col, floor = args[0], float(args[1])
        if rows and rows[-1][col] < floor:
            raise Invalid("last_row", column=col, min=floor)
    elif kind == "kc_ranges":
        if rows and rows[0]["bbch_min"] != 0:
            raise Invalid("first_row", column="bbch_min", value=0)
        for i, r in enumerate(rows):
            if r["bbch_min"] > r["bbch_max"]:
                raise Invalid("range_order", column="bbch_min")
            if i and r["bbch_min"] != rows[i - 1]["bbch_max"] + 1:
                raise Invalid("contiguous", column="bbch_min")


def validate(entry: Entry, value: Any, limit: Optional[Dict[str, Any]] = None) -> Any:
    """The value in its canonical form, or Invalid. Types and shape come from the registry, bounds from the registry
    narrowed by the administrator's limit."""
    s = entry.spec
    b = merged_bounds(entry, limit)
    k = s.kind
    if k == "bool":
        if not isinstance(value, bool):
            raise Invalid("type", expected="bool")
        return value
    if k in ("int", "float"):
        out = _num(value, k)
        _in_range(out, b["min"], b["max"])
        return out
    if k == "str":
        if not isinstance(value, str) or len(value) > s.max_len or any(ord(ch) < 32 and ch not in "\n\t" for ch in value):
            raise Invalid("type", expected="str", max_len=s.max_len)
        return value
    if k == "enum":
        if value not in (choices_of(s) or []):
            raise Invalid("choice", allowed=choices_of(s))
        return value
    if k == "pair":
        if not isinstance(value, list) or len(value) != 2:
            raise Invalid("shape", expected="pair")
        kind = "int" if s.unit == "BBCH" else "float"
        out = [_num(x, kind) for x in value]
        for x, el in zip(out, b["elements"]):
            _in_range(x, el["min"], el["max"])
        if out[0] > out[1]:
            raise Invalid("order", column="pair")
        return out
    if k == "map":
        if not isinstance(value, dict) or set(value) != set(entry.default):
            raise Invalid("shape", expected="same keys", keys=sorted(entry.default))
        out = {}
        for key, v in value.items():
            out[key] = _num(v, "float")
            _in_range(out[key], b["keys"][key]["min"], b["keys"][key]["max"])
        return out
    if k == "list":
        if not isinstance(value, list):
            raise Invalid("type", expected="list")
        if len(value) < b["min_items"] or len(value) > b["max_items"]:
            raise Invalid("items", min=b["min_items"], max=b["max_items"])
        out = [_token(x, choices_of(s), s.item_kind) for x in value]
        if len(set(map(repr, out))) != len(out):
            raise Invalid("duplicate")
        return out
    if k == "table":
        rows = _rows(s, value, b)
        if len(rows) < max(b["min_items"], 0) or len(rows) > b["max_items"]:
            raise Invalid("items", min=b["min_items"], max=b["max_items"])
        for rule in s.checks:
            _check(rule, rows)
        return rows
    if k == "groups":
        if not isinstance(value, list) or len(value) > b["max_items"] or len(value) < b["min_items"]:
            raise Invalid("items", min=b["min_items"], max=b["max_items"])
        out = []
        for grp in value:
            rows = _rows(s, grp, b)
            if not rows or len(rows) > 8:
                raise Invalid("items", min=1, max=8)
            out.append(rows)
        return out
    raise Invalid("type")


def validate_limit(entry: Entry, limit: Any) -> Dict[str, Any]:
    """An administrator limit in canonical form, inside the registry bounds; Invalid otherwise."""
    if not isinstance(limit, dict) or not set(limit) <= {"user_editable", "min", "max", "min_items", "max_items", "columns"}:
        raise Invalid("shape", expected="limit")
    s, hb = entry.spec, hard_bounds(entry)
    out: Dict[str, Any] = {}
    if "user_editable" in limit:
        if not isinstance(limit["user_editable"], bool):
            raise Invalid("type", expected="bool")
        out["user_editable"] = limit["user_editable"]

    def bound(v, kind, lo, hi):
        if v is None:
            return None
        n = _num(v, kind)
        _in_range(n, lo, hi)
        return n
    numeric = s.kind in ("int", "float", "pair", "map")
    for k in ("min", "max"):
        if limit.get(k) is not None:
            if not numeric:
                raise Invalid("shape", expected="no numeric limit")
            out[k] = bound(limit[k], "float", hb["min"], hb["max"])
    if "min" in out and "max" in out and out["min"] > out["max"]:
        raise Invalid("order", column="limit")
    for k in ("min_items", "max_items"):
        if limit.get(k) is not None:
            if s.kind not in ("list", "table", "groups"):
                raise Invalid("shape", expected="no item limit")
            out[k] = bound(limit[k], "int", hb["min_items"], hb["max_items"])
    if limit.get("columns"):
        if s.kind not in ("table", "groups") or not isinstance(limit["columns"], dict):
            raise Invalid("shape", expected="no column limit")
        cols = {}
        for name, cl in limit["columns"].items():
            if name not in hb["columns"] or not isinstance(cl, dict) or not set(cl) <= {"min", "max"}:
                raise Invalid("shape", expected="column limit")
            hc = hb["columns"][name]
            one = {k: bound(cl[k], "float", hc["min"], hc["max"]) for k in ("min", "max") if cl.get(k) is not None}
            if "min" in one and "max" in one and one["min"] > one["max"]:
                raise Invalid("order", column=name)
            if one:
                cols[name] = one
        if cols:
            out["columns"] = cols
    return out


def check_relations(flat: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Relations violated by the merged values (key -> value; a missing key is read from the file)."""
    errors = []
    for a, op, b, code in RELATIONS:
        va, vb = flat.get(a), flat.get(b)
        if va is None or vb is None:
            continue
        if (op == "<=" and va > vb) or (op == ">=" and va < vb):
            errors.append({"key": a, "code": code, "params": {"other": b}})
    return errors


# ---------------------------------------------------------------------------------------------------------------------
# Warnings: inside the allowed range but outside the recommended values of the source
# ---------------------------------------------------------------------------------------------------------------------
def warnings(entry: Entry, value: Any) -> List[Dict[str, Any]]:
    """A value inside the limit but outside the recommended range of its slot. `basis` says whether that range is the
    cited source's (`source` is then given) or a development band around the file default (no source is claimed)."""
    s = entry.spec
    rg = ranges(entry)
    if not rg or value is None:
        return []
    src = SOURCES.get(s.source)
    out: List[Dict[str, Any]] = []

    def check(v: Any, slot: str, where: str) -> None:
        r = rg.get(slot)
        if r is None or not isinstance(v, (int, float)) or isinstance(v, bool):
            return
        lo, hi = r["recommended"]
        if v < lo or v > hi:
            out.append({"key": entry.key, "code": "outside_recommended", "where": where, "value": v, "range": [lo, hi],
                        "basis": r["basis"], "source": {"text": src[0], "url": src[1]} if src and r["basis"] == "source" else None})
    if s.kind in ("int", "float"):
        check(value, "", "")
    elif s.kind == "pair":
        for i, v in enumerate(value):
            check(v, str(i), str(i))
    elif s.kind == "map":
        for name, v in value.items():
            check(v, name, name)
    elif s.kind in ("table", "groups"):
        rows = [(f"{gi + 1}.{i + 1}", row) for gi, g in enumerate(value) for i, row in enumerate(g)] if s.kind == "groups" else \
            [(str(i + 1), row) for i, row in enumerate(value)]
        for label_, row in rows:
            for col in rg:
                if col in row:
                    check(row[col], col, "%s.%s" % (label_, col))
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Description for the API
# ---------------------------------------------------------------------------------------------------------------------
def describe(entry: Entry) -> Dict[str, Any]:
    """Static metadata of one entry (everything except values and limits)."""
    s = entry.spec
    src = SOURCES.get(s.source)
    shape: Dict[str, Any] = {}
    if s.cols:
        shape["columns"] = [{"name": col.name, "kind": col.kind, "min": col.lo, "max": col.hi, "optional": col.optional,
                             "choices": choices_of(col), "label": {"en": col.en, "sr": col.sr}} for col in s.cols]
    if s.kind in ("enum", "list") and s.choices is not None:
        shape["choices"] = choices_of(s)
    if s.kind == "map":
        shape["keys"] = list(entry.default)
    if s.kind == "list":
        shape["item"] = s.item_kind
    if s.kind == "str":
        shape["max_len"] = s.max_len
    rg = ranges(entry)
    shaped: Dict[str, Any] = {"recommended": None, "default_limit": None, "range_basis": None}
    if rg:
        pick = {"recommended": "recommended", "default_limit": "limit", "range_basis": "basis"}
        for out_key, in_key in pick.items():
            if s.kind in ("int", "float"):
                shaped[out_key] = rg[""][in_key]
            elif s.kind == "pair":
                shaped[out_key] = [rg[str(i)][in_key] for i in (0, 1)]
            else:
                shaped[out_key] = {slot: v[in_key] for slot, v in rg.items()}
    reason = entry.spec.readonly or entry.blocked()
    return {"key": entry.key, "file": entry.file, "name": entry.name, "label": label(entry), "group": s.group, "kind": s.kind,
            "unit": s.unit, "shape": shape, "default": entry.default, "hard": hard_bounds(entry), **shaped,
            "user_editable_default": s.user, "status": s.status,
            "source": {"text": src[0], "url": src[1]} if src else None,
            "note": {"en": s.note_en, "sr": s.note_sr}, "hint": {"en": s.hint_en, "sr": s.hint_sr},
            "readonly": {"en": reason[0], "sr": reason[1]} if reason else None}


def protocol_view() -> List[Dict[str, Any]]:
    return [{"file": f + ".yaml", "reason": {"en": PROTOCOL_REASON[0], "sr": PROTOCOL_REASON[1]},
             "values": copy.deepcopy(config.load_file(f))} for f in PROTOCOL_FILES]


def groups() -> List[Dict[str, Any]]:
    return [{"id": g, "label": {"en": en, "sr": sr}} for g, en, sr in GROUPS]


def statuses() -> List[str]:
    return list(STATUSES)
