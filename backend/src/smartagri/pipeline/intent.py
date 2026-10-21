"""Offline intent classification and parsing of user replies. Deterministic keyword rules.

A language model can replace classify() for free-form questions; these rules keep the system
usable without one and make scenario runs reproducible.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from ..core.types import AdviceType
from ..retrieval.search import fold

OUT_OF_SCOPE = ("pesticid", "fungicid", "herbicid", "insekticid", "bolest", "stetoc", "korov", "preparat", "sredstv")
IRRIGATION = ("navodnj", "zaliv", "zalij", "vode da dam", "vodu", "kisenj", "kap po kap")
FERTILIZATION = ("djubr", "prihran", "azot", "ure", "kan ", "npk")
FIELD_OPS = ("prsk", "setv", "sej", "kultiv", "obrad", "radov", "mraz", "vetar", "kosidb", "zetv")
SCOUTING = ("obilaz", "obidj", "slabij", "ndvi", "satelit", "snimak", "deo parcele", "zut", "vegetacij", "stanje useva")
AMOUNT = ("koliko", "kolicin", "norma", "litar", "mm ", "kubik")
OPERATIONS = (("prsk", "spraying"), ("setv", "sowing"), ("sej", "sowing"), ("prihran", "fertilizing"),
              ("djubr", "fertilizing"), ("kultiv", "cultivation"), ("obrad", "cultivation"))
UNKNOWN_WORDS = ("ne znam", "nemam", "nije mi poznato", "nisam siguran", "nisam sigurna")


def _has(text: str, words) -> bool:
    return any(w in text for w in words)


def classify(question: str) -> Optional[AdviceType]:
    """Advice type of a question, or None when it cannot be told."""
    t = " " + fold(question) + " "
    if _has(t, OUT_OF_SCOPE):
        return AdviceType.OUT_OF_SCOPE
    if _has(t, IRRIGATION):
        return AdviceType.IRRIGATION_AMOUNT if _has(t, AMOUNT) else AdviceType.IRRIGATION_TIMING
    if _has(t, FERTILIZATION):
        if _has(t, ("kada", "kad ", "mogu li", "da li da")) and not _has(t, AMOUNT):
            return AdviceType.FERTILIZATION_TIMING if "kada" in t or "kad " in t else AdviceType.FERTILIZATION_PLAN
        return AdviceType.FERTILIZATION_PLAN
    if _has(t, FIELD_OPS):
        return AdviceType.FIELD_OPS_WINDOW
    if _has(t, SCOUTING):
        return AdviceType.SCOUTING
    return None


def operation_in(question: str) -> Optional[str]:
    t = fold(question)
    for word, op in OPERATIONS:
        if word in t:
            return op
    return None


N_CONTENT = (("ure", 0.46), ("kan", 0.27), ("an ", 0.335), ("amonijum nitrat", 0.335), ("npk 15", 0.15))


def parse_reply(input_name: str, text: str) -> Tuple[str, Any]:
    """Parse a free-text reply to a pending question.

    Returns ("value", parsed), ("declined", None) when the user does not know, or ("unparsed", None).
    """
    t = " " + fold(text).strip() + " "
    # "nemam" answers the irrigation question with "no"; elsewhere it means the datum is not available.
    if "ne znam" in t or "nisam sigur" in t or (
            _has(t, UNKNOWN_WORDS) and input_name not in ("previous_fertilization", "irrigation_available")):
        return "declined", None
    number = re.search(r"\d+(?:[.,]\d+)?", t)
    if input_name == "soil_water_status":
        if "umeren" in t or "srednj" in t:
            return "value", "moist"
        if "suv" in t or "mrvi" in t:
            return "value", "dry"
        if "vlaz" in t or "mokr" in t or "blat" in t:
            return "value", "wet"
    elif input_name == "irrigation_available":
        if re.search(r"\b(ne|nema|nemam)\b", t):
            return "value", "no"
        if re.search(r"\b(da|ima|imam)\b", t):
            return "value", "yes"
    elif input_name == "irrigation_efficiency":
        for word, system in (("kisenj", "sprinkler"), ("rasprsk", "sprinkler"), ("tifon", "sprinkler"),
                             ("kap", "drip"), ("brazd", "furrow")):
            if word in t:
                return "value", system
    elif input_name == "soil_awc":
        for word, texture in (("pesk", "sandy_loam"), ("lak", "sandy_loam"), ("ilov", "loam"), ("srednj", "loam"),
                              ("glin", "clay"), ("tesk", "clay"), ("tez", "clay")):
            if word in t:
                return "value", texture
    elif input_name == "phenophase":
        for word, bbch in (("metlic", 55), ("svil", 65), ("mlecn", 75), ("vostan", 85), ("zrel", 87)):
            if word in t:
                return "value", bbch
        leaves = re.search(r"(\d+)\s*(list|lista|listova)", t)
        if leaves:
            return "value", min(19, 10 + int(leaves.group(1)))
        if number and 0 <= float(number.group().replace(",", ".")) <= 99:
            return "value", int(float(number.group().replace(",", ".")))
    elif input_name == "previous_fertilization":
        if _has(t, ("nista", "nisam", "bez djubr", "nije djubr")):
            return "value", []
        if number:
            kg = float(number.group().replace(",", "."))
            for word, share in N_CONTENT:
                if word in t:
                    return "value", [{"product": word.strip(), "rate_kg_ha": kg, "n_kg_ha": round(kg * share, 1)}]
            if "azot" in t or " n " in t:
                return "value", [{"product": "N", "rate_kg_ha": kg, "n_kg_ha": kg}]
        if _has(t, UNKNOWN_WORDS):
            return "declined", None
    elif input_name == "yield_target":
        if number:
            return "value", float(number.group().replace(",", "."))
    elif input_name == "operation":
        op = operation_in(text)
        if op:
            return "value", op
    elif input_name == "soil_analysis":
        year = re.search(r"(20\d\d)", t)
        if year:
            return "value", {"date": year.group(1) + "-01-01"}
    return "unparsed", None


def apply_reply(agronomic: Dict[str, Any], input_name: str, value: Any, today: str) -> Dict[str, Any]:
    """Store a reply on the parcel's agronomic record. Returns the updated record."""
    a = dict(agronomic)
    if input_name == "soil_water_status":
        a.update(soil_water_status=value, soil_water_origin="user_reported", soil_water_reported_on=today)
    elif input_name == "irrigation_available":
        a["irrigation_available"] = value
    elif input_name == "irrigation_efficiency":
        if isinstance(value, (int, float)):
            a["irrigation_efficiency"] = float(value)
        else:
            a["irrigation_system_type"] = value
    elif input_name == "soil_awc":
        if isinstance(value, (int, float)):
            a["soil_awc_mm_m"] = float(value)
        else:
            a["soil_texture"] = value
    elif input_name == "phenophase":
        a.update(bbch=int(value), bbch_origin="user_reported", bbch_reported_on=today)
    elif input_name == "previous_fertilization":
        a["previous_fertilization"] = value
    elif input_name == "yield_target":
        a["yield_target_t_ha"] = float(value)
    elif input_name == "operation":
        a["operation"] = value
    elif input_name == "soil_analysis":
        a["soil_analysis"] = value if isinstance(value, dict) else {"level": value, "date": today}
    return a
