"""Offline intent classification and parsing of user replies. Deterministic keyword rules.

A language model can replace classify() for free-form questions; these rules keep the system
usable without one and make scenario runs reproducible.

Matching works on folded text (lower case, no diacritics) and on whole words or word starts, never on pieces of words
("ure" is not in "temperature"). A reply that cannot be read with confidence is "unparsed", never a guess: a negated state
("nije suvo"), two different states, a number without the cue that says what it measures, an amount whose unit or
product is unclear. The interactive research API asks the user to confirm what was understood before it writes a value
(research_api/service.py); the evaluation runner does not wait: it uses the scenario's prepared replies.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Pattern, Tuple

from .. import config
from ..core.types import AdviceType
from ..retrieval.search import fold


def _rx(*parts: str) -> Pattern[str]:
    return re.compile("|".join(parts))


OUT_OF_SCOPE = _rx(r"\bpesticid", r"\bfungicid", r"\bherbicid", r"\binsekticid", r"\binsekt", r"\bbolest", r"\bstetoc",
                   r"\bstetn", r"\bkorov", r"\bpreparat", r"\bsredstv", r"\bplamenjac", r"\bplamenac", r"\bplamenc",
                   r"\bzaraz", r"\bgljivic", r"\bmsic", r"\bsuzbij", r"\btretir", r"\bzastit\w*\s+bilja",
                   r"\bprsk\w*(?:\s+\w+){0,3}\s+protiv\b",
                   # aphids: "vaši"; the pronoun "vas" / "vaši" is not one, so only the phrases that mean the insect
                   r"\b(?:lisn|biljn)\w*\s+vasi\b", r"\bnapad\w*(?:\s+\w+)?\s+vasi\b", r"\bvasi\s+(?:na|u|po)\b")
IRRIGATION = _rx(r"\bnavodnj", r"\bzaliv", r"\bzalij", r"\bvode da dam", r"\bvodu\b", r"\bkisenj", r"\bkap po kap\b")
FERTILIZATION = _rx(r"\bdjubr", r"\bprihran", r"\bazot", r"\bure(?:a|e|u|om)?\b", r"\bkan\b", r"\bnpk\b")
FIELD_OPS = _rx(r"\bprsk", r"\bsetv", r"\bsej", r"\bkultiv", r"\bobrad", r"\bradov", r"\bmraz", r"\bvetar\b", r"\bvetr",
                r"\bkosidb", r"\bzetv")
SCOUTING = _rx(r"\bobilaz", r"\bobidj", r"\bslabij", r"\bndvi\b", r"\bsatelit", r"\bsnimak", r"\bdeo parcele",
               r"\bdelov\w* parcele", r"\bzut", r"\bvegetacij", r"\bstanje useva")
AMOUNT = _rx(r"\bkoliko", r"\bkolicin", r"\bnorm", r"\blitar", r"\bmm\b", r"\bkubik")
WHEN = _rx(r"\bkada\b", r"\bkad\b", r"\bmogu li\b", r"\bda li da\b")
OPERATIONS = ((r"\bprsk", "spraying"), (r"\bsetv", "sowing"), (r"\bsej", "sowing"), (r"\bprihran", "fertilizing"),
              (r"\bdjubr", "fertilizing"), (r"\bkultiv", "cultivation"), (r"\bobrad", "cultivation"))
UNKNOWN = _rx(r"\bne znam\b", r"\bnemam\b", r"\bnije mi poznato\b", r"\bnisam siguran\b", r"\bnisam sigurna\b",
              r"\bnemam pojma\b")
SURE_UNKNOWN = _rx(r"\bne znam\b", r"\bnisam sigur\w*", r"\bnemam pojma\b")      # declined whatever the input


def classify(question: str) -> Optional[AdviceType]:
    """Advice type of a question, or None when it cannot be told."""
    t = " " + fold(question) + " "
    if OUT_OF_SCOPE.search(t):
        return AdviceType.OUT_OF_SCOPE
    if IRRIGATION.search(t):
        return AdviceType.IRRIGATION_AMOUNT if AMOUNT.search(t) else AdviceType.IRRIGATION_TIMING
    if FERTILIZATION.search(t):
        if WHEN.search(t) and not AMOUNT.search(t):
            return AdviceType.FERTILIZATION_TIMING if re.search(r"\bkada?\b", t) else AdviceType.FERTILIZATION_PLAN
        return AdviceType.FERTILIZATION_PLAN
    if FIELD_OPS.search(t):
        return AdviceType.FIELD_OPS_WINDOW
    if SCOUTING.search(t):
        return AdviceType.SCOUTING
    return None


def operation_in(question: str) -> Optional[str]:
    t = fold(question)
    for pattern, op in OPERATIONS:
        if re.search(pattern, t):
            return op
    return None


# ---------------------------------------------------------------- reading a reply

NEGATORS = frozenset({"ne", "nije", "nisu", "nema", "nemam", "nemamo", "bez", "nikako", "nimalo", "nikad", "niti"})
CLAUSE = re.compile(r"[,.;:!?()]+|\b(?:ali|nego|vec|a)\b")
NUMBER = r"(\d+(?:[.,]\d+)?)"


def _num(text: str) -> float:
    return float(text.replace(",", "."))


def _mentions(t: str, pattern: str) -> Tuple[bool, bool]:
    """(mentioned, mentioned only under a negation): a match is negated when a negator stands within the three words before
    it in the same clause ("nije suvo", "ne baš suvo"); a comma, a full stop, "ali", "nego" or "a" ends the clause."""
    positive = negated = False
    for clause in CLAUSE.split(t):
        for m in re.finditer(pattern, clause):
            before = re.findall(r"\w+", clause[:m.start()])[-3:]
            if NEGATORS & set(before):
                negated = True
            else:
                positive = True
    return positive, negated


def _soil_water(t: str) -> Tuple[str, Any]:
    dry = _mentions(t, r"\bsuv(?:o|a|e|i|u|og|om|im|ih)\b|\bmrvi|\bispucal|\bpuca\b")
    wet = _mentions(t, r"\bvlaz\w*|\bmokr\w*|\bblat\w*|\bnatopljen\w*|\bzabarenj\w*")
    moist = _mentions(t, r"\bumeren\w*|\bsrednj\w*|\bpolu\s*vlaz\w*")
    if re.search(r"\bni\b.+\bni\b", t) and (dry[0] or dry[1]) and (wet[0] or wet[1]):
        return "value", "moist"                               # "ni suvo ni vlažno"
    if moist[0] and not dry[0]:
        return "value", "moist"                               # "umereno vlažno" is moist, not wet
    positives = [state for state, hit in (("dry", dry[0]), ("wet", wet[0]), ("moist", moist[0])) if hit]
    if len(positives) == 1:
        return "value", positives[0]
    if not positives and dry[1] and wet[1]:
        return "value", "moist"                               # "nije ni suvo, ni vlažno"
    return "unparsed", None                                   # a negation alone, or two states: ask again


def _irrigation_available(t: str) -> Tuple[str, Any]:
    first = re.match(r"\s*(da|ne)\b\s*(?:,|\.|!|$)", t)
    if first:
        return "value", "yes" if first.group(1) == "da" else "no"
    yes = re.search(r"\b(?:da|ima|imam|imamo|moze|mogu|postoji|jeste|naravno)\b", t)
    no = re.search(r"\b(?:ne|nema|nemam|nemamo|nikako)\b", t)
    if yes and not no:
        return "value", "yes"
    if no and not yes:
        return "value", "no"
    return "unparsed", None


SYSTEMS = (("sprinkler", r"\bkisenj|\brasprsk|\btifon|\bpivot|\btopov"), ("drip", r"\bkap po kap\b|\bkapanj|\bkapljic|\bkap\b"),
           ("furrow", r"\bbrazd|\bpovrsinsk"))


def _irrigation_system(t: str) -> Tuple[str, Any]:
    found = [system for system, pattern in SYSTEMS if _mentions(t, pattern)[0]]
    return ("value", found[0]) if len(found) == 1 else ("unparsed", None)


TEXTURE_WORDS = (("sandy_loam", r"\bpesk\w*|\blak\w*"), ("loam", r"\bilov\w*|\bsrednj\w*"), ("clay", r"\bglin\w*|\btesk\w*|\btez\w*"))


def _texture(t: str) -> Tuple[str, Any]:
    found = [texture for texture, pattern in TEXTURE_WORDS if re.search(pattern, t)]
    if len(found) == 1:
        return "value", found[0]
    if found == ["loam", "clay"] and re.search(r"\bglinovit\w*\s+ilovac", t):
        return "value", "clay_loam"
    return "unparsed", None


STAGE_WORDS = ((r"\bmetlic", 55), (r"\bsvil", 65), (r"\bmlecn", 75), (r"\bvostan", 85))


def _phenophase(t: str) -> Tuple[str, Any]:
    """BBCH from a stage word (not negated), "N listova", "BBCH N" / "faza N", or a reply that is only a number. A number
    with none of those cues ("posejano 25. aprila", "imam 5 ha") is not a stage."""
    found: List[int] = [bbch for pattern, bbch in STAGE_WORDS if _mentions(t, pattern)[0]]
    if not found and _mentions(t, r"\bzrel")[0]:
        found.append(87)                                      # "zrelost" without milk or wax
    for m in re.finditer(r"\b" + NUMBER + r"\s*list\w*", t):
        leaves = _num(m.group(1))
        if leaves != int(leaves) or not 1 <= leaves <= 30:
            return "unparsed", None
        found.append(min(19, 10 + int(leaves)))
    for m in re.finditer(r"\bbbch\s*(?:faz\w*)?\s*[:=]?\s*(\d{1,3})\b|\bfaz\w*\s+(?:je\s+|u\s+)?(?:bbch\s*)?[:=]?\s*(\d{1,3})\b", t):
        found.append(int(m.group(1) or m.group(2)))
    bare = re.match(r"\s*(?:bbch\s*)?(\d{1,3})\s*[.!]?\s*$", t)
    if bare:
        found.append(int(bare.group(1)))
    if len(set(found)) != 1 or not 0 <= found[0] <= 99:
        return "unparsed", None
    return "value", found[0]


PRODUCT_ALIASES = {"urea": (r"ure(?:a|e|u|om)", r"karbamid\w*"), "kan": (r"kan", r"kalcijum\s*amonijum\s*nitrat\w*"),
                   "an": (r"an", r"amonijum\s*nitrat\w*")}
NONE_APPLIED = _rx(r"\bnista\b", r"\bbez\s+(?:djubr|prihran)", r"\bnije\s+(?:bilo\s+)?(?:djubr|prihran)",
                   r"\bnisam\s+(?:\w+\s+){0,2}?(?:djubr|prihran|dao|dala|davao|rasuo|stavlj)")
RATE = re.compile(NUMBER + r"\s*kg\s*(?:/|po|na)?\s*(?:ha\b|hektar\w*)")
RATE_NO_AREA = re.compile(NUMBER + r"\s*kg\b(?!\s*(?:/|po|na)?\s*(?:ha\b|hektar))")
PRODUCT_WINDOW = 30


def _product_patterns() -> List[Tuple[str, Pattern[str]]]:
    """(key of rules.optional_inputs.n_content, pattern) for every product of the configuration, with the synonyms of
    PRODUCT_ALIASES. The shares of nitrogen are those of the configuration and nowhere else."""
    out = []
    for key in config.load("rules")["optional_inputs"]["n_content"]:
        forms = PRODUCT_ALIASES.get(key) or (r"[\s\-:/_.]*".join(re.escape(part) for part in key.split("_")),)
        out.append((key, re.compile(r"\b(?:%s)\b" % "|".join(forms))))
    return out


def _fertilization(t: str) -> Tuple[str, Any]:
    if NONE_APPLIED.search(t):
        return "value", []
    table = config.load("rules")["optional_inputs"]["n_content"]
    products = [(m.start(), m.end(), key) for key, pattern in _product_patterns() for m in pattern.finditer(t)]
    nitrogen = [(m.start(), m.end()) for m in re.finditer(r"\bazot\w*|\bn\b", t)]
    records: List[Dict[str, Any]] = []
    for m in RATE.finditer(t):
        rate = _num(m.group(1))
        times = re.search(r"(\d+)\s*(?:puta|x)\s*(?:po\s*)?$", t[:m.start()])
        if times:
            rate *= int(times.group(1))
        def gap(start: int, end: int) -> int:
            return max(start - m.end(), m.start() - end, 0)
        near = [(gap(a, b), a, key) for a, b, key in products if gap(a, b) <= PRODUCT_WINDOW]
        n_cue = [(gap(a, b), a) for a, b in nitrogen if gap(a, b) <= PRODUCT_WINDOW]
        if near and (not n_cue or min(near)[0] <= min(n_cue)[0]):
            key = min(near)[2]
            records.append({"product": key, "rate_kg_ha": rate, "n_kg_ha": round(rate * table[key], 1)})
        elif n_cue:
            records.append({"product": "N", "rate_kg_ha": rate, "n_kg_ha": rate})
        else:
            return "unparsed", None                           # an amount of nothing we can tell the nitrogen of
    if records:
        return "value", records
    return "unparsed", None                                   # no amount per hectare: no guess from a bare number


def _yield_target(t: str) -> Tuple[str, Any]:
    whole = re.match(r"\s*(?:oko\s+|otprilike\s+|cca\s+|preko\s+)?" + NUMBER + r"\s*(?:t|tona|tone|tonu)?\s*(?:/|po|na)?\s*(?:ha|hektar\w*)?\s*[.!]?\s*$", t)
    if whole:
        return "value", _num(whole.group(1))
    found = {_num(m.group(1)) for m in re.finditer(r"\b" + NUMBER + r"\s*(?:t|tona|tone|tonu)\b", t)}
    return ("value", found.pop()) if len(found) == 1 else ("unparsed", None)


def parse_reply(input_name: str, text: str) -> Tuple[str, Any]:
    """Parse a free-text reply to a pending question.

    Returns ("value", parsed), ("declined", None) when the user does not know, or ("unparsed", None) when the reply cannot
    be read with confidence (the caller asks again).
    """
    t = " " + fold(text).strip() + " "
    # "nemam" answers the irrigation question with "no"; elsewhere it means the datum is not available.
    if SURE_UNKNOWN.search(t) or (UNKNOWN.search(t) and input_name not in ("previous_fertilization", "irrigation_available")):
        return "declined", None
    if input_name == "soil_water_status":
        return _soil_water(t)
    if input_name == "irrigation_available":
        return _irrigation_available(t)
    if input_name == "irrigation_efficiency":
        return _irrigation_system(t)
    if input_name == "soil_awc":
        return _texture(t)
    if input_name == "phenophase":
        return _phenophase(t)
    if input_name == "previous_fertilization":
        kind, value = _fertilization(t)
        if kind == "unparsed" and UNKNOWN.search(t):
            return "declined", None
        return kind, value
    if input_name == "yield_target":
        return _yield_target(t)
    if input_name == "operation":
        op = operation_in(text)
        return ("value", op) if op else ("unparsed", None)
    if input_name == "soil_analysis":
        year = re.search(r"\b(20\d\d)\b(?!\s*(?:kg|mm|ha|t\b|m\b|l\b|g\b|din|eur|km|m2))", t)
        return ("value", {"date": year.group(1) + "-01-01"}) if year else ("unparsed", None)
    return "unparsed", None


def parse_confirmation(text: str) -> Optional[str]:
    """"yes" or "no" for the answer to "Understood: ...; is that right?" (local language or English), None when it is
    neither (ask again). A negation wins over a confirmation word ("ne, nije tačno")."""
    t = " " + fold(text).strip() + " "
    if re.search(r"\bnije\s+(?:tacno|tako|to)\b|\bnetacn\w*|\bpogresn\w*|\bne\b|\bnot\s+(?:right|correct)\b|\b(?:no|nope|wrong|incorrect)\b", t):
        return "no"
    if re.search(r"\b(?:da|tacno|tako je|ispravno|u redu|jeste|potvrdjujem|ok|okay|vazi|yes|yeah|correct|right|sure)\b", t):
        return "yes"
    return None


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
