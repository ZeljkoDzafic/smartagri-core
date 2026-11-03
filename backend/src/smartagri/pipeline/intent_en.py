"""English questions and replies: deterministic keyword rules like pipeline/intent.py.

Used only when the request locale is `en` and the local rules do not recognise the text, so the local
classification (and every evaluation run) is unchanged. The corpus stays in the local language: an English
question is mapped to its advice type and retrieval uses the canonical local question of that type
(labels_en.LOCAL_QUERIES); the user's own text is what the conversation shows.
"""
from __future__ import annotations

import re
from typing import Any, Optional, Tuple

from ..core.types import AdviceType

OUT_OF_SCOPE = ("pesticide", "fungicide", "herbicide", "insecticide", "disease", "pest ", "pests", "weed", "spray product",
                "which product", "what product", "chemical")
IRRIGATION = ("irrigat", " water ", " water?", " water.", "watering", "sprinkler", "drip")
FERTILIZATION = ("fertili", "top-dress", "topdress", "top dress", "nitrogen", "urea", "calcium ammonium", "npk", "manure")
FIELD_OPS = ("spray", "sow", "seeding", "cultivat", "tillage", "field work", "frost", "wind", "harvest", "work on the field")
SCOUTING = ("scout", "ndvi", "satellite", "image", "weaker", "part of the field", "part of the parcel", "yellow",
            "vegetation", "crop condition", "check the field", "walk the")
AMOUNT = ("how much", "how many", "amount", "quantity", "litre", "liter", " mm", "rate", "dose")
OPERATIONS = (("spray", "spraying"), ("sow", "sowing"), ("seeding", "sowing"), ("top-dress", "fertilizing"),
              ("topdress", "fertilizing"), ("fertili", "fertilizing"), ("cultivat", "cultivation"), ("tillage", "cultivation"))
UNKNOWN_WORDS = ("don't know", "do not know", "dont know", "not sure", "no idea", "unknown")


def _t(text: str) -> str:
    return " " + re.sub(r"\s+", " ", (text or "").lower()) + " "


def _has(text: str, words) -> bool:
    return any(w in text for w in words)


def classify(question: str) -> Optional[AdviceType]:
    """Advice type of an English question, or None."""
    t = _t(question)
    if _has(t, OUT_OF_SCOPE):
        return AdviceType.OUT_OF_SCOPE
    if _has(t, IRRIGATION):
        return AdviceType.IRRIGATION_AMOUNT if _has(t, AMOUNT) else AdviceType.IRRIGATION_TIMING
    if _has(t, FERTILIZATION):
        if _has(t, ("when", "can i", "should i")) and not _has(t, AMOUNT):
            return AdviceType.FERTILIZATION_TIMING if "when" in t else AdviceType.FERTILIZATION_PLAN
        return AdviceType.FERTILIZATION_PLAN
    if _has(t, FIELD_OPS):
        return AdviceType.FIELD_OPS_WINDOW
    if _has(t, SCOUTING):
        return AdviceType.SCOUTING
    return None


def operation_in(question: str) -> Optional[str]:
    t = _t(question)
    for word, op in OPERATIONS:
        if word in t:
            return op
    return None


def parse_reply(input_name: str, text: str) -> Tuple[str, Any]:
    """English free-text reply to a pending question: ("value", v), ("declined", None) or ("unparsed", None)."""
    t = _t(text)
    if _has(t, UNKNOWN_WORDS):
        return "declined", None
    number = re.search(r"\d+(?:[.,]\d+)?", t)
    if input_name == "soil_water_status":
        if "moderat" in t or "medium" in t or "moist" in t and "very" not in t:
            return "value", "moist"
        if "dry" in t or "crumbl" in t:
            return "value", "dry"
        if "wet" in t or "muddy" in t or "soak" in t:
            return "value", "wet"
    elif input_name == "irrigation_available":
        if re.search(r"\b(no|not|cannot|can't)\b", t):
            return "value", "no"
        if re.search(r"\b(yes|can|have)\b", t):
            return "value", "yes"
    elif input_name == "irrigation_efficiency":
        for word, system in (("sprinkler", "sprinkler"), ("drip", "drip"), ("furrow", "furrow")):
            if word in t:
                return "value", system
    elif input_name == "soil_awc":
        for word, texture in (("sand", "sandy_loam"), ("light", "sandy_loam"), ("loam", "loam"), ("medium", "loam"),
                              ("clay", "clay"), ("heavy", "clay")):
            if word in t:
                return "value", texture
    elif input_name == "phenophase":
        for word, bbch in (("tassel", 55), ("silk", 65), ("milk", 75), ("dough", 85), ("ripe", 87)):
            if word in t:
                return "value", bbch
        leaves = re.search(r"(\d+)\s*(leaf|leaves)", t)
        if leaves:
            return "value", min(19, 10 + int(leaves.group(1)))
        if number and 0 <= float(number.group().replace(",", ".")) <= 99:
            return "value", int(float(number.group().replace(",", ".")))
    elif input_name == "previous_fertilization":
        if _has(t, ("nothing", "none", "not yet", "no fertili")):
            return "value", []
        if number and ("nitrogen" in t or " n " in t):
            kg = float(number.group().replace(",", "."))
            return "value", [{"product": "N", "rate_kg_ha": kg, "n_kg_ha": kg}]
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
