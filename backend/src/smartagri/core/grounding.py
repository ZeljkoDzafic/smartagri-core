"""Grounding check gamma.

Numeric part: every number in an answer must come from a tool or the context.
Support part: every sentence a language model writes must be supported by an applicable passage
or by the fact sheet. The default check is lexical (share of a sentence's content words found in
the best supporting text) and therefore conservative and explainable; an entailment model can be
plugged in through `support_check(..., judge=...)`.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, List, Optional

from .types import ToolResult

_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:[.,]\d+)?")


def _numbers_in(obj: Any) -> List[float]:
    out: List[float] = []
    if isinstance(obj, bool) or obj is None:
        return out
    if isinstance(obj, (int, float)):
        return [float(obj)]
    if isinstance(obj, str):
        return [float(m.replace(",", ".")) for m in _NUMBER.findall(obj)]
    if isinstance(obj, dict):
        obj = obj.values()
    if isinstance(obj, Iterable):
        for item in obj:
            out.extend(_numbers_in(item))
    return out


# Kind of a figure ("role"), from the unit written after it in a text or from the words of the key it is stored under.
# A figure with a unit is supported only by a value of the same kind or of an unknown kind (audit D14): a latitude, a
# BBCH stage or a year can no longer "support" a depth of water. Unknown kind = "none".
_UNIT_ROLES = (
    (r"kg\s*(?:N|P|K)?\s*/\s*ha|kg", "kg_ha"), (r"t\s*/\s*ha", "t_ha"), (r"l\s*/\s*ha", "l_ha"),
    (r"m\u00b3|m3", "m3"), (r"mm", "mm"), (r"%", "pct"), (r"\u00b0\s*C|\u00b0", "degc"), (r"km\s*/\s*h", "kmh"),
    (r"m\s*/\s*s", "ms"), (r"ha", "ha"), (r"dana|dan|days|day", "days"), (r"sati|sata|sat|hours|hour|h", "hours"),
)
_UNIT_AFTER = re.compile(r"^\s*(" + "|".join("(?:%s)" % u for u, _ in _UNIT_ROLES) + r")(?![A-Za-z])", re.IGNORECASE)
QUANTITY_ROLES = frozenset(("mm", "kg_ha", "t_ha", "l_ha", "m3"))
_KEY_ROLES = (("kg_ha", "kg_ha"), ("n_kg", "kg_ha"), ("t_ha", "t_ha"), ("m3", "m3"), ("mm", "mm"), ("pct", "pct"),
              ("percent", "pct"), ("degc", "degc"), ("temp", "degc"), ("tmin", "degc"), ("tmax", "degc"),
              ("ms", "ms"), ("days", "days"), ("hours", "hours"), ("area", "ha"), ("lat", "coord"), ("lon", "coord"), ("latitude", "coord"), ("longitude", "coord"), ("lng", "coord"),
              ("bbch", "bbch"))
_NUMBER_ANY = re.compile(r"(?<![\w.])-?\d{1,3}[.,]\d{3}(?![\d])|(?<![\w.])-?\d+(?:[.,]\d+)?")
_GROUPED = re.compile(r"^-?[1-9]\d{0,2}[.,]\d{3}$")


def settings() -> dict:
    from .. import config
    base = {"number_tolerance_rel": 0.05, "number_tolerance_floor": 1.0, "quantity_tolerance_rel": 0.005,
            "number_roles": True, "ambiguous_group": "strict", "check_negation": True}
    base.update(config.load("rules").get("grounding") or {})
    return base


def _role_of_key(key: Any) -> str:
    words = re.split(r"[^a-z0-9]+", str(key).lower())
    joined = "_".join(words)
    for needle, role in _KEY_ROLES:
        if (needle in words or needle in joined) and (len(needle) > 3 or needle in words):
            return role
    return "none"


def _role_of_unit(unit: str) -> str:
    for pattern, role in _UNIT_ROLES:
        if re.fullmatch(pattern, unit.strip(), re.IGNORECASE):
            return role
    return "none"


def _readings(token: str) -> List[float]:
    """The values a written figure can mean: "1,200" is 1.2 or 1200 (decimal comma or thousands group)."""
    if _GROUPED.match(token):
        return [float(token.replace(",", ".")), float(re.sub(r"[.,]", "", token))]
    return [float(token.replace(",", "."))]


def _claims(text: str) -> List[tuple]:
    """(readings, role) of every figure written in `text`; the role comes from the unit after it (or BBCH before it)."""
    out = []
    for m in _NUMBER_ANY.finditer(text):
        after = _UNIT_AFTER.match(text[m.end():])
        role = _role_of_unit(after.group(1)) if after else ("bbch" if re.search(r"BBCH\s*$", text[:m.start()], re.I) else "none")
        out.append((_readings(m.group(0)), role))
    return out


def _pool(obj: Any, key: Any = None) -> List[tuple]:
    """(value, role) of every number in a nested structure; the role is that of the closest key, or of the unit in a text."""
    if isinstance(obj, bool) or obj is None:
        return []
    if isinstance(obj, (int, float)):
        return [(float(obj), _role_of_key(key) if key is not None else "none")]
    if isinstance(obj, str):
        return [(v, role) for readings, role in _claims(obj) for v in readings]
    if isinstance(obj, dict):
        return [p for k, v in obj.items() for p in _pool(v, k)]
    if isinstance(obj, Iterable):
        return [p for item in obj for p in _pool(item, key)]
    return []


def unsupported_numbers(text: str, tools: List[ToolResult], context_values: Any = None,
                        tolerance: Optional[float] = None) -> List[float]:
    """Numbers in `text` that match neither a tool input/output nor a context value.

    A non-empty result means the answer states a figure nobody computed: remove it, make the claim conditional, or
    downgrade the act. Matching (rules.grounding): within a relative tolerance of max(floor, |value|); a quantity (depth,
    dose, volume) to rounding only; a figure with a unit only against a value of the same kind (audit D14); a figure
    that can be read two ways ("1,200") must be supported in every reading under `ambiguous_group: strict`.
    """
    cfg = settings()
    pool: List[tuple] = _pool(context_values)
    for t in tools:
        pool.extend(_pool(t.inputs))
        pool.extend(_pool(t.output))
    rel = cfg["number_tolerance_rel"] if tolerance is None else tolerance
    floor = cfg["number_tolerance_floor"]

    def supported(n: float, role: str) -> bool:
        tol = cfg["quantity_tolerance_rel"] if role in QUANTITY_ROLES else rel
        for value, vrole in pool:
            if cfg["number_roles"]:
                if role != "none" and vrole not in (role, "none"):
                    continue
                if role == "none" and vrole == "coord":
                    continue
            if abs(n - value) <= tol * max(floor, abs(value)):
                return True
        return False

    bad = []
    for readings, role in _claims(text):
        mode = cfg["ambiguous_group"]
        if len(readings) == 2 and mode == "decimal":
            readings = readings[:1]
        elif len(readings) == 2 and mode == "thousands":
            readings = readings[1:]
        if not all(supported(n, role) for n in readings):
            bad.append(next(n for n in readings if not supported(n, role)))
    return bad


def _content(text: str):
    from ..retrieval.search import tokenize
    return set(tokenize(text))


ABBREVIATIONS = ("npr", "tj", "itd", "sl", "br", "str", "god", "tzv", "dr", "prof", "sar", "min", "maks", "cca", "oko")


def split_sentences(text: str) -> List[str]:
    """Split on . ! ? followed by space, but not after common Serbian abbreviations or a decimal point."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    out: List[str] = []
    for part in parts:
        if out:
            last_word = re.findall(r"(\w+)\.$", out[-1].lower())
            # also do not split dates and ordinals: "20. 9. 2025." or "u 3. nedelji"
            # a new sentence starts with a capital letter, a digit or a dash, never with a lowercase letter
            if (last_word and last_word[0] in ABBREVIATIONS) or re.search(r"(^|[\s(])\d{1,2}\.$", out[-1]) \
                    or part[:1].islower():
                out[-1] = out[-1] + " " + part
                continue
        if part:
            out.append(part)
    return out


NEGATIONS = frozenset(("ne", "nije", "nisu", "nemoj", "nemojte", "nema", "nemate", "bez", "nikad", "nikada", "nista",
                       "ništa", "not", "no", "without", "never", "don't", "dont", "cannot"))


def _negated(text: str) -> bool:
    return any(w in NEGATIONS for w in re.findall(r"[\w']+", text.lower()))


def _polarity_clash(sentence: str, source: str, words: set) -> bool:
    """Does the sentence of `source` that is closest to `sentence` say the opposite (one negates, the other does not)?
    Only when that closest sentence shares at least half of the content words (otherwise there is nothing to compare)."""
    best, best_share = None, 0.0
    for part in split_sentences(source):
        share = len(words & _content(part)) / float(len(words))
        if share > best_share:
            best, best_share = part, share
    return best is not None and best_share >= 0.5 and _negated(sentence) != _negated(best)


def support_check(sentences: List[str], sources: List[str], threshold: float = 0.5,
                  judge=None, check_negation: Optional[bool] = None) -> List[dict]:
    """For each sentence: the best-supporting source index, the support score and a verdict.

    Lexical score = |content words of the sentence found in the source| / |content words of the sentence|.
    A sentence with fewer than three content words is treated as supported (connectives, short replies).
    judge(sentence, source) -> float in [0, 1] replaces the lexical score when given; a judge that
    returns None for a pair (API error, refusal) leaves the lexical score for that pair.
    """
    out = []
    negation = settings()["check_negation"] if check_negation is None else check_negation
    source_words = [_content(s) for s in sources]
    for sentence in sentences:
        words = _content(sentence)
        if len(words) < 3:
            out.append({"sentence": sentence, "score": 1.0, "source": None, "supported": True})
            continue
        best, best_i = 0.0, None
        for i, src in enumerate(sources):
            score = judge(sentence, src) if judge else None
            if score is None:                 # no judge, or the judge gave no verdict: lexical score
                score = len(words & source_words[i]) / float(len(words))
            if score > best:
                best, best_i = score, i
        ok = best >= threshold
        entry = {"sentence": sentence, "score": round(best, 3), "source": best_i, "supported": ok}
        if ok and negation and best_i is not None and _polarity_clash(sentence, sources[best_i], words):
            entry.update(supported=False, reason="negation")      # same words, opposite meaning (audit D14)
        out.append(entry)
    return out
