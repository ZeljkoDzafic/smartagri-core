"""Latin to Cyrillic transliteration of the local language (spec 017), for the sr-Cyrl locale.

Deterministic and lossless for local words: lj, nj and dž become љ, њ and џ (with capitals and the known
prefix exceptions such as nadživeti, odžaliti, injekcija); every other letter maps one to one. What must stay
in Latin script stays: URLs and e-mail addresses, numbers with their units (mm, kg/ha, m/s, °C, t/ha, kg N/ha),
acronyms and technical tokens (NDVI, FAO, BBCH, EUDR, GeoJSON, ET0, ETc, Kc, Sentinel-2, Open-Meteo, ...),
identifiers with digits (DEMO-LOT-2026-001, AGV-DDS-...), words with letters outside the local alphabet
(q, w, x, y), English phrases and quoted English titles, and any substring passed in `keep` (user-entered
values such as parcel or product names). Text that is already Cyrillic is left as it is, so the function is
idempotent. Protected tokens (PROTECT list) and token rules keep codes, units and names unchanged.

`to_latin` is the exact inverse for local words; it is used to run the Latin-script checks on Cyrillic text.
"""
from __future__ import annotations

import functools
import re
from typing import Iterable, List, Optional, Tuple

DIGRAPHS = [("Lj", "Љ"), ("LJ", "Љ"), ("lj", "љ"), ("Nj", "Њ"), ("NJ", "Њ"), ("nj", "њ"), ("Dž", "Џ"), ("DŽ", "Џ"),
            ("dž", "џ")]
SINGLE = dict(zip("abcčćdđefghijklmnoprsštuvzžABCČĆDĐEFGHIJKLMNOPRSŠTUVZŽ",
                  "абцчћдђефгхијклмнопрсштувзжАБЦЧЋДЂЕФГХИЈКЛМНОПРСШТУВЗЖ"))
CYR2LAT = {v: k for k, v in SINGLE.items()}
CYR2LAT.update({"љ": "lj", "њ": "nj", "џ": "dž", "Љ": "Lj", "Њ": "Nj", "Џ": "Dž"})

# Words that stay in Latin script: product, data-set and system names, technical abbreviations.
PROTECT = set("""Agrovid SmartAgri Sentinel Sentinel-2 Copernicus CDSE Open-Meteo Meteo NDVI FAO BBCH EUDR GeoJSON JSON PDF
CSV HS EORI ET0 ETc Kc AI LLM SMTP TRACES WGS84 ISO EPSG GPS URL API ID Mailpit DejaVu ReportLab reportlab TARAG
pH N P K Excel UTF-8 BOM KAN NPK UAN MAP DAP AN Urea Claude Anthropic OpenAI sr-Latn sr-Cyrl en true false null
Push Data Space Ecosystem Google Earth Esri EOX Nominatim Photon OpenStreetMap Apple Android Safari Firefox Chrome""".split())
# Acronyms written in local Cyrillic in Cyrillic text (spec 053, U12): "EU" -> "ЕУ".
LOCAL_ACRONYMS = {"EU"}
# Brand and system names whose inflected forms (Agrovidu, Sentinelom) also stay Latin. "Agrovid" is the former
# product name (kept so older texts stay as they were).
PROTECT_PREFIXES = ("Agrovid", "Sentinel", "Copernicus", "Open-Meteo")
# Multi-word names that always stay Latin, as a whole: the product name (since 2026-10-19). They are also left out of
# the English-sentence check, so "Otvori Open Crop Manager" is still treated as local text.
PROTECT_PHRASES = ("Open Crop Manager",)
# Unit symbols kept in Latin script next to a number, a slash or a degree sign ("3,5 mm", "kg N/ha", "°C").
UNITS = {"mm", "cm", "km", "m", "s", "h", "ha", "kg", "g", "mg", "t", "l", "ml", "N", "C", "K"}
ROMAN = {"I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"}
# Local words in which "dž" or "nj" are two letters (prefix + word), not a digraph.
DZ_EXCEPTIONS = ("nadž", "odž", "podž", "predž", "Nadž", "Odž", "Podž", "Predž")
NJ_EXCEPTIONS = ("injek", "konjug", "konjunk", "vanjez", "Injek", "Konjug", "Konjunk", "Vanjez")
LATIN_ONLY = re.compile(r"[qwxyQWXYäöüÄÖÜßéèáàíóú]")
LOCAL_DIACRITICS = re.compile(r"[čćžšđČĆŽŠĐ]")
# English detection (titles of guidance documents, English phrases): share of English-looking words.
EN_WORDS = set("""the of and with for from this that are is on in to by an as at or not be its system systems file guide
guidelines maize corn crop crops water soil field fields data free products product regulation directive information
handbook manual report use plant plants nitrogen fertilizer fertiliser management requirements computing farm farmers
description documentation operator help meets grade capped under any no max min not""".split())
EN_SUFFIX = re.compile(r"(tion|tions|sion|ness|ing|ity|ies|ly|ous|ical|ward|ship|ful)$")
TOKEN = re.compile(r"[A-Za-zČĆŽŠĐčćžšđäöüÄÖÜßéèáàíóú][A-Za-zČĆŽŠĐčćžšđäöüÄÖÜßéèáàíóú0-9_.'’\-]*")
# Segments that are never transliterated: URLs, e-mail addresses, quoted text (decided separately).
SPECIAL = re.compile(r"(\b[A-Z][a-z]+/[A-Z][A-Za-z_]+(?:/[A-Z][A-Za-z_]+)?|\([^()]*\)|%[-0-9.]*[sdfr]|https?://\S+|www\.\S+|[\w.+-]+@[\w-]+(?:\.[\w-]+)+|/api/\S+|„[^”]*”|\"[^\"]*\"|“[^”]*”)")


def _cyr_word(w: str) -> str:
    out = w
    if not out.startswith(DZ_EXCEPTIONS):
        out = out.replace("Dž", "Џ").replace("DŽ", "Џ").replace("dž", "џ")
    else:
        head, tail = out[:4], out[4:]
        out = head + tail.replace("Dž", "Џ").replace("DŽ", "Џ").replace("dž", "џ")
    out = out.replace("Lj", "Љ").replace("LJ", "Љ").replace("lj", "љ")
    if not out.startswith(NJ_EXCEPTIONS):
        out = out.replace("Nj", "Њ").replace("NJ", "Њ").replace("nj", "њ")
    return "".join(SINGLE.get(c, c) for c in out)


def _keep_word(w: str) -> bool:
    bare = w.rstrip(".'’-")
    if bare in LOCAL_ACRONYMS:
        return False
    return bool(bare in PROTECT or w in PROTECT or bare.startswith(PROTECT_PREFIXES) or LATIN_ONLY.search(w)
                or any(c.isdigit() for c in w) or "_" in w
                or (len(bare) >= 2 and bare.isupper() and not LOCAL_DIACRITICS.search(bare) and not bare.startswith(("LJ", "NJ")))
                or re.search(r"[a-z][A-Z]", w))


def _is_unit(text: str, start: int, end: int, word: str) -> bool:
    word = word.rstrip(".")
    end = start + len(word)
    if word not in UNITS:
        return False
    before = text[:start].rstrip("  ")
    after = text[end:end + 1]
    prev = text[start - 1:start] if start else ""
    if prev in ("/", "°") or after in ("/", "³", "²") or re.match(r"\s*N\s*/", text[end:]):
        return True
    if before[-1:].isdigit() or before.endswith("%") or before.endswith("kg"):
        return True
    return not text[:start].strip() and not text[end:].strip()          # the whole text is the unit ("mm")


def _roman(text: str, start: int, word: str) -> bool:
    if word not in ROMAN:
        return False
    before = text[:start].rstrip()
    return bool(before) and before[-1] not in ".!?:"


def _translit_plain(text: str) -> str:
    def repl(m):
        w = m.group(0)
        if _is_unit(text, m.start(), m.end(), w) or _roman(text, m.start(), w):
            return w
        bare = w.rstrip(".'’-")
        whole = bare in PROTECT or w in PROTECT or bare.startswith(PROTECT_PREFIXES) or LATIN_ONLY.search(w)
        parts = w.split("-")
        if "-" in w and not whole and not all(_keep_word(p) for p in parts if p):
            return "-".join(p if (p and _keep_word(p)) else _cyr_word(p) for p in parts)
        return w if _keep_word(w) else _cyr_word(w)
    return TOKEN.sub(repl, text)


def _english(text: str) -> bool:
    """English phrase or title: no local diacritics and at least half of its (non-acronym) words look English."""
    if LOCAL_DIACRITICS.search(text):
        return False
    words = [w for w in re.findall(r"[A-Za-z]{2,}", text) if not w.isupper()]
    if len(words) < 2:
        return False
    score = sum(1 for w in words if w.lower() in EN_WORDS or EN_SUFFIX.search(w.lower()))
    return score >= 2 and score * 2 >= len(words)


@functools.lru_cache(maxsize=64)
def _keep_pattern(words: Tuple[str, ...]):
    return re.compile("|".join(r"(?<!\w)%s(?!\w)" % re.escape(k) for k in words))


def _split_keep(text: str, keep: Iterable[str]) -> List[Tuple[str, bool]]:
    """Split text into (segment, protected) parts; protected parts are the longest `keep` occurrences."""
    words = tuple(sorted({k for k in keep if isinstance(k, str) and len(k.strip()) >= 2}, key=lambda k: (-len(k), k)))
    if not words:
        return [(text, False)]
    pattern = _keep_pattern(words)
    out: List[Tuple[str, bool]] = []
    pos = 0
    for m in pattern.finditer(text):
        if m.start() > pos:
            out.append((text[pos:m.start()], False))
        out.append((m.group(0), True))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], False))
    return out


def to_cyrillic(text: Optional[str], keep: Iterable[str] = ()) -> Optional[str]:
    """Local Latin text in Cyrillic script; see the module docstring for what stays in Latin script."""
    if not isinstance(text, str) or not text:
        return text
    probe = text
    for phrase in PROTECT_PHRASES:
        probe = probe.replace(phrase, " ")
    if _english(SPECIAL.sub(" ", probe)):         # an English sentence or title (quoted parts decided below)
        return text
    if any(phrase in text for phrase in PROTECT_PHRASES):
        keep = tuple(keep) + PROTECT_PHRASES
    out = []
    for segment, protected in _split_keep(text, keep):
        if protected:
            out.append(segment)
            continue
        for i, part in enumerate(SPECIAL.split(segment)):
            if i % 2 == 0:
                out.append(_translit_plain(part))
            elif part[:1] == "(":
                inner = part[1:-1]
                if _english(inner) or re.search(r"[_=]", inner):
                    out.append(part)                             # an English or technical note in parentheses
                else:
                    out.append("(" + to_cyrillic(inner, keep) + ")")
            elif part[:1] in "„\"“" and len(part) > 1:
                inner = part[1:-1]
                # Quoted English titles and Latin-only names stay as written; quoted local words are transliterated.
                if _english(inner) or LATIN_ONLY.search(inner) or inner.strip() in PROTECT or re.search(r"\d", inner) \
                        or re.search(r"\b[A-Z]{2,}\b", inner):
                    out.append(part)
                else:
                    out.append(part[0] + _translit_plain(inner) + part[-1])
            else:
                out.append(part)                                 # URL, e-mail, API path
    return "".join(out)


def to_latin(text: Optional[str]) -> Optional[str]:
    """Cyrillic text of the local language in Latin script (exact inverse for local words)."""
    if not isinstance(text, str) or not text:
        return text
    out = []
    for i, c in enumerate(text):
        lat = CYR2LAT.get(c)
        if lat is None:
            out.append(c)
        elif len(lat) == 2 and c.isupper():
            nxt = text[i + 1:i + 2]
            out.append(lat.upper() if nxt.isupper() else lat)  # "ЉУБАВ" -> "LJUBAV", "Љубав" -> "Ljubav"
        else:
            out.append(lat)
    return "".join(out)


def has_cyrillic(text: str) -> bool:
    return bool(re.search(r"[Ѐ-ӿ]", text or ""))
