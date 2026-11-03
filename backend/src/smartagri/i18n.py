"""Locales of user-facing text.

Three locales: `sr-Latn` (default; the local language in Latin script), `sr-Cyrl` (the same text in Cyrillic
script) and `en` (English). Codes are BCP 47 tags; user-facing labels never name a nation ("Lokalni (latinica)",
"Локални (ћирилица)", "English").

How text becomes localised:
  - `L()` returns the label catalogue of the active locale: `labels` (unchanged, the default) or `labels_en`.
    Code that writes user-facing text reads its tables and formatting functions through `L()`, so numbers and
    logic are the same in every locale and only the words differ.
  - `T(text)` returns a literal sentence (often a %-format) of the default catalogue in the active locale:
    the English entry of `labels_en.MESSAGES` for `en`, the neutral wording of `NEUTRAL` for `sr-Cyrl`, the text
    itself otherwise (so the default output stays byte-identical).
  - Cyrillic is never written by the generators: the API layer transliterates allow-listed text fields of the
    response (api/localize.py), so every check runs on the same Latin text as in the default locale.

The active locale lives in a context variable holding a small mutable state, set per request by the API
middleware; outside a request (evaluation runs, CLI, tests) it is the default.

The registry `product_config/locales.yaml` adds locales as data (`i18n_catalogue`). The
state keeps two codes: `locale`, the base locale whose code paths run (`current()`: sr-Latn, sr-Cyrl or en), and
`requested`, the locale the user asked for (`active()`). For a new locale (e.g. `de`) `current()` is `en`, so every
module that still branches on English writes English (the fallback language of every new catalogue), while `L()`,
`T()` and `translate_message()` render the requested locale's JSON catalogue with English fallback per key. For the
three existing locales both codes are equal and nothing changes; `L()` and `T()` for `sr-Latn` never leave this
module (plan D1). English itself is served from its JSON catalogue (D2, proven equivalent to labels_en); the
environment variable SMARTAGRI_EN_CATALOGUE=module switches English back to module labels_en.
"""
from __future__ import annotations

import contextlib
import re
from contextvars import ContextVar
from typing import Any, Dict, Iterator, List, Optional

DEFAULT_LOCALE = "sr-Latn"
LOCALES: List[Dict[str, str]] = [
    {"code": "sr-Latn", "label": "Lokalni (latinica)"},
    {"code": "sr-Cyrl", "label": "Локални (ћирилица)"},
    {"code": "en", "label": "English"},
]
CODES = tuple(x["code"] for x in LOCALES)
# Language subtags of the local language and its standard variants; all map to the local language.
LOCAL_LANGUAGES = ("sr", "bs", "hr", "cnr", "sh")

_STATE: ContextVar[Optional[Dict[str, Any]]] = ContextVar("smartagri_locale", default=None)

# sr-Cyrl: neutral wording for the few default sentences that name a language (the default text is unchanged).
NEUTRAL = {
    "PDF nije moguće napraviti: na serveru nema fonta sa srpskim slovima (DejaVu Sans).":
        "PDF nije moguće napraviti: na serveru nema fonta sa slovima lokalnog jezika (DejaVu Sans).",
}


# ---------------------------------------------------------------- resolution

def _catalogue():
    """The registry module (`i18n_catalogue`), or None where it is not shipped (the open core has only sr-Latn, sr-Cyrl and en): every other locale then falls back to the default, as before 036."""
    try:
        from . import i18n_catalogue
    except ImportError:
        return None
    return i18n_catalogue


def normalize(tag: Any) -> Optional[str]:
    """A locale code for a language tag, or None when the tag names no supported locale.

    sr, bs, hr, cnr, sh (any region) -> sr-Latn; any of them with -Cyrl -> sr-Cyrl; en (any region) -> en (an enabled
    pseudo-locale en-XA by its exact code); any other tag -> the selectable registry locale with the same
    code or language subtag (mk and sl are separate languages and never map to the local language).
    """
    if not isinstance(tag, str):
        return None
    t = tag.strip().replace("_", "-")
    if not t:
        return None
    parts = [p.lower() for p in t.split("-") if p]
    if not parts:
        return None
    lang = parts[0]
    if lang == "en":
        if len(parts) > 1 and parts[1] == "xa":
            cat = _catalogue()
            return (cat.match_tag(t) if cat else None) or "en"
        return "en"
    if lang in LOCAL_LANGUAGES:
        if "cyrl" in parts[1:]:
            return "sr-Cyrl"
        return "sr-Latn"
    cat = _catalogue()
    return cat.match_tag(t) if cat else None


def from_accept_language(header: Optional[str]) -> Optional[str]:
    """The supported locale with the highest q value in an Accept-Language header (ties: header order)."""
    if not header:
        return None
    ranked = []
    for i, item in enumerate(header.split(",")):
        piece = item.strip()
        if not piece:
            continue
        tag, _, params = piece.partition(";")
        q = 1.0
        m = re.search(r"q\s*=\s*([0-9.]+)", params)
        if m:
            try:
                q = float(m.group(1))
            except ValueError:
                q = 0.0
        if q <= 0:
            continue
        ranked.append((-q, i, tag.strip()))
    for _, _, tag in sorted(ranked):
        code = normalize(tag)
        if code:
            return code
    return None


def resolve(query: Optional[str] = None, header: Optional[str] = None,
            accept_language: Optional[str] = None) -> Optional[str]:
    """The explicitly requested locale: ?lang=, then the language header of the client, then Accept-Language; None when none applies
    (then the user's saved preference, then the default, decide; see apply_user_preference)."""
    for value in (query, header):
        code = normalize(value)
        if code:
            return code
    return from_accept_language(accept_language)


# ---------------------------------------------------------------- active locale

def _state_for(code: Optional[str], explicit: bool) -> Dict[str, Any]:
    cat = _catalogue()
    code = code or DEFAULT_LOCALE
    base = cat.base_of(code) if cat else (code if code in CODES else DEFAULT_LOCALE)
    return {"locale": base, "requested": code, "explicit": explicit}


def begin(explicit: Optional[str]) -> Dict[str, Any]:
    """New per-request state; returns it (the middleware keeps a reference to read the final locale)."""
    if explicit is None or explicit in CODES:
        state = {"locale": explicit or DEFAULT_LOCALE, "requested": explicit or DEFAULT_LOCALE,
                 "explicit": explicit is not None}
    else:
        state = _state_for(explicit, True)
    _STATE.set(state)
    return state


def state() -> Optional[Dict[str, Any]]:
    return _STATE.get()


def known(code: Any) -> bool:
    """A code of the three base locales or of a selectable registry locale."""
    if code in CODES:
        return True
    cat = _catalogue()
    return bool(cat and cat.is_selectable(code))


def set_locale(st: Optional[Dict[str, Any]], code: Optional[str]) -> None:
    """Switch a request state to `code` (both the base locale and the requested one)."""
    if st is None:
        return
    new = _state_for(code if known(code) else DEFAULT_LOCALE, st.get("explicit", False))
    st["locale"], st["requested"] = new["locale"], new["requested"]


def apply_user_preference(user_locale: Any) -> None:
    """Use the user's saved locale when the request named none."""
    st = _STATE.get()
    code = user_locale if known(user_locale) else None
    if st is not None and not st["explicit"] and code:
        set_locale(st, code)


def current() -> str:
    """The base locale whose code paths run: sr-Latn, sr-Cyrl or en (en for every new locale)."""
    st = _STATE.get()
    return st["locale"] if st else DEFAULT_LOCALE


def active() -> str:
    """The locale the request asked for (equal to current() for the three base locales)."""
    st = _STATE.get()
    return st.get("requested", st["locale"]) if st else DEFAULT_LOCALE


@contextlib.contextmanager
def use(locale: str) -> Iterator[None]:
    """Run a block in `locale` (tests, background work)."""
    if locale in CODES:
        st = {"locale": locale, "requested": locale, "explicit": True}
    else:
        cat = _catalogue()
        st = _state_for(locale if cat and cat.entry(locale) else DEFAULT_LOCALE, True)
    token = _STATE.set(st)
    try:
        yield
    finally:
        _STATE.reset(token)


def is_default() -> bool:
    return current() == DEFAULT_LOCALE


def _en_module() -> bool:
    from .config import env
    return env("EN_CATALOGUE") == "module"


# ---------------------------------------------------------------- catalogues

def L():
    """The label catalogue of the active locale: module `labels` (sr-Latn, sr-Cyrl), otherwise the JSON catalogue of
    the requested locale (English, and every new locale with English fallback)."""
    if current() == "en":
        code = active()
        if code == "en" and _en_module():
            from . import labels_en
            return labels_en
        return _catalogue().catalogue(code)       # only reached for a registry locale (catalogue present)
    from . import labels
    return labels


def T(text: str) -> str:
    """A literal default-catalogue sentence in the active locale (see module docstring)."""
    loc = current()
    if loc == "en":
        code = active()
        if code == "en" and _en_module():
            from .labels_en import MESSAGES
            return MESSAGES.get(text, text)
        return _catalogue().catalogue(code).message(text)
    if loc == "sr-Cyrl":
        return NEUTRAL.get(text, text)
    return text


# ---------------------------------------------------------------- stored and raised messages (en)

_PATTERNS: Optional[List[Any]] = None
_EXACT: Optional[Dict[str, str]] = None
# Tables of `labels` mirrored in `labels_en` whose strings are also looked up by translate_message.
LABEL_TABLES = ("ADVICE_TYPES", "ACTS", "RELIABILITY", "ORIGIN", "APPLICABILITY", "INPUTS", "PREVIOUS_CROPS",
                "OBSERVATION_KINDS", "OPTIONS", "DECLINE_OPTION", "VALUE_WORDS", "CORE_ACTIONS", "NO_DIAGNOSIS", "REFERRAL",
                "PLANT_PROTECTION_REFERRAL", "CHECKS", "TOOLS", "GENERIC_ADVICE", "DOSE_NOTE", "QUANTITY_NOTE",
                "ABSTAIN_REASONS", "FRESHNESS", "OPERATIONS_WINDOW", "OPERATION_STATUS", "ACTIVITY_KINDS",
                "ACTIVITY_STATUSES", "SEVERITIES", "IRRIGATION_METHODS", "ACTIVITY_ORIGIN", "ACTIVITY_EVENT_ACTIONS",
                "EUDR_DISCLAIMER", "EUDR_CUTOFF_STATEMENT", "EUDR_COMMODITIES", "EUDR_CHECKS")


def _pairs(sr: Any, en: Any, out: Dict[str, str]) -> None:
    if isinstance(sr, str) and isinstance(en, str):
        if sr != en and sr not in out:
            out[sr] = en
    elif isinstance(sr, dict) and isinstance(en, dict):
        for k in sr:
            if k in en:
                _pairs(sr[k], en[k], out)
    elif isinstance(sr, (list, tuple)) and isinstance(en, (list, tuple)):
        for a, b in zip(sr, en):
            _pairs(a, b, out)


def _exact() -> Dict[str, str]:
    """MESSAGES plus every default label paired with its English entry (same table, same position)."""
    global _EXACT
    if _EXACT is None:
        from . import labels, labels_en
        out: Dict[str, str] = {}
        for name in LABEL_TABLES:
            _pairs(getattr(labels, name), getattr(labels_en, name), out)
        out.update(labels_en.MESSAGES)
        _EXACT = out
    return _EXACT


def _patterns() -> List[Any]:
    """%-format entries of MESSAGES and the {name} formats of ACTIVITY_WARNINGS as (regex, english format) pairs,
    longest first."""
    global _PATTERNS
    if _PATTERNS is None:
        from . import labels, labels_en
        out = []
        for sr, en in labels_en.MESSAGES.items():
            if "%" not in sr:
                continue
            pieces = re.split(r"(%[-0-9.]*[sdfr]|%%)", sr)
            rx = ""
            for p in pieces:
                if p == "%%":
                    rx += "%"
                elif re.fullmatch(r"%[-0-9.]*[sdfr]", p or ""):
                    rx += "(.+?)"
                else:
                    rx += re.escape(p)
            out.append((re.compile("^" + rx + "$", re.S), re.sub(r"%[-0-9.]*[sdfr]", "%s", en), sr))
        for key, sr in labels.ACTIVITY_WARNINGS.items():
            names = re.findall(r"\{(\w+)\}", sr)
            rx = "".join("(.+?)" if re.fullmatch(r"\{\w+\}", p) else re.escape(p) for p in re.split(r"(\{\w+\})", sr))
            en = labels_en.ACTIVITY_WARNINGS[key]
            fmt = re.sub(r"\{(\w+)\}", lambda m: "%%(%s)s" % m.group(1), en.replace("%", "%%"))
            out.append((re.compile("^" + rx + "$", re.S), (fmt, names), sr))
        out.sort(key=lambda x: -len(x[2]))
        _PATTERNS = out
    return _PATTERNS


def _legacy_translate_arg(arg: str, depth: int) -> str:
    """An argument of a matched message: a message or label, a date, a number of days, a decimal number, or a
    list of them joined with '; ' or ', ' (anything else, e.g. a parcel or product name, stays as it is)."""
    from . import labels_en
    out = _legacy_translate_message(arg, depth + 1)
    if out != arg:
        return out
    out = _legacy_translate_message(arg + ".", depth + 1)          # list items are joined without their final period
    if out != arg + ".":
        return out.rstrip(".")
    m = re.fullmatch(r"(\d{1,2})\. (\d{1,2})\. (\d{4})\.", arg)
    if m:
        return labels_en.fmt_date("%s-%02d-%02d" % (m.group(3), int(m.group(2)), int(m.group(1))))
    m = re.fullmatch(r"(\d+) (dan|dana)", arg)
    if m:
        return labels_en.days_text(int(m.group(1)))
    if re.fullmatch(r"-?\d+,\d+", arg):
        return arg.replace(",", ".")
    for sep in ("; ", ", "):
        if sep in arg:
            parts = arg.split(sep)
            done = [_legacy_translate_arg(p.rstrip("."), depth + 1) for p in parts]
            if done != [p.rstrip(".") for p in parts]:
                return sep.join(done)
    return arg


def _legacy_translate_message(text: Any, depth: int = 0) -> Any:
    """English version of a default-catalogue message that was stored or raised as finished text (error details,
    stored warnings, provider messages): an exact entry (labels_en.MESSAGES or a mirrored label), or a format entry
    (%-formats of MESSAGES, {name} formats of ACTIVITY_WARNINGS) whose arguments are translated in turn. Text without
    an entry is returned unchanged (user data stays as entered)."""
    if not isinstance(text, str) or not text or depth > 4:
        return text
    exact = _exact()
    if text in exact:
        return exact[text]
    for rx, en, _ in _patterns():
        m = rx.match(text)
        if not m:
            continue
        args = [_legacy_translate_arg(a, depth) for a in m.groups()]
        try:
            if isinstance(en, tuple):
                fmt, names = en
                return fmt % dict(zip(names, args))
            return en % tuple(args)
        except (TypeError, ValueError, KeyError):
            return text
    return text


# ---------------------------------------------------------------- stored and raised messages (any locale)

_GENERIC: Dict[str, Any] = {}


def _generic_tables(code: str):
    """(exact map, patterns) from default text to locale `code` (D6): the same construction as _exact()/_patterns()
    with the target catalogue in place of labels_en."""
    from . import labels, labels_en
    reg = _catalogue()
    catalogue, sources = reg.catalogue, reg.source_messages()
    n = len(labels_en.MESSAGES)
    hit = _GENERIC.get(code)
    if hit is not None and hit[0] == n:
        return hit[1], hit[2]
    cat = catalogue(code)
    exact: Dict[str, str] = {}
    for name in LABEL_TABLES:
        _pairs(getattr(labels, name), cat.table(name), exact)
    messages = {sr: cat.message(sr) for sr in sources}
    exact.update({sr: str(t) for sr, t in messages.items()})
    out = []
    for sr, target in messages.items():
        if "%" not in sr:
            continue
        pieces = re.split(r"(%[-0-9.]*[sdfr]|%%)", sr)
        rx = ""
        for p in pieces:
            if p == "%%":
                rx += "%"
            elif re.fullmatch(r"%[-0-9.]*[sdfr]", p or ""):
                rx += "(.+?)"
            else:
                rx += re.escape(p)
        out.append((re.compile("^" + rx + "$", re.S), target, sr))
    warnings = cat.table("ACTIVITY_WARNINGS")
    for key, sr in labels.ACTIVITY_WARNINGS.items():
        names = re.findall(r"\{(\w+)\}", sr)
        rx = "".join("(.+?)" if re.fullmatch(r"\{\w+\}", p) else re.escape(p) for p in re.split(r"(\{\w+\})", sr))
        fmt = re.sub(r"\{(\w+)\}", lambda m: "%%(%s)s" % m.group(1), str(warnings[key]).replace("%", "%%"))
        out.append((re.compile("^" + rx + "$", re.S), (fmt, names), sr))
    out.sort(key=lambda x: -len(x[2]))
    _GENERIC[code] = (n, exact, out)
    return exact, out


def _number_or_text(arg: str) -> Any:
    try:
        return float(arg.replace(",", "."))
    except ValueError:
        return arg


def _generic_translate_arg(code: str, arg: str, depth: int) -> str:
    cat = _catalogue().catalogue(code)
    out = _generic_translate(code, arg, depth + 1)
    if out != arg:
        return out
    out = _generic_translate(code, arg + ".", depth + 1)
    if out != arg + ".":
        return out.rstrip(".")
    m = re.fullmatch(r"(\d{1,2})\. (\d{1,2})\. (\d{4})\.", arg)
    if m:
        return cat.fmt_date("%s-%02d-%02d" % (m.group(3), int(m.group(2)), int(m.group(1))))
    m = re.fullmatch(r"(\d+) (dan|dana)", arg)
    if m:
        return cat.days_text(int(m.group(1)))
    if re.fullmatch(r"-?\d+,\d+", arg):
        return arg.replace(",", cat.decimal_symbol())
    for sep in ("; ", ", "):
        if sep in arg:
            parts = arg.split(sep)
            done = [_generic_translate_arg(code, p.rstrip("."), depth + 1) for p in parts]
            if done != [p.rstrip(".") for p in parts]:
                return sep.join(done)
    return arg


def _generic_translate(code: str, text: Any, depth: int = 0) -> Any:
    PyFormat = _catalogue().PyFormat
    if not isinstance(text, str) or not text or depth > 4:
        return text
    exact, patterns = _generic_tables(code)
    if text in exact:
        return exact[text]
    for rx, target, _ in patterns:
        m = rx.match(text)
        if not m:
            continue
        args = [_generic_translate_arg(code, a, depth) for a in m.groups()]
        try:
            if isinstance(target, tuple):
                fmt, names = target
                return fmt % dict(zip(names, args))
            if isinstance(target, PyFormat):
                shown = {str(i): a for i, a in enumerate(args)}
                raw = {str(i): _number_or_text(a) for i, a in enumerate(args)}
                return target._cat._render(target._nodes, shown, raw)
            return re.sub(r"%[-0-9.]*[sdfr]", "%s", target) % tuple(args)
        except (TypeError, ValueError, KeyError):
            return text
    return text


def translate_message(text: Any, depth: int = 0) -> Any:
    """A default-catalogue message that was stored or raised as finished text (error details, stored warnings,
    provider messages) in the requested locale: an exact entry (a message or a mirrored label), or a format entry
    (%-formats of the messages, {name} formats of ACTIVITY_WARNINGS) whose arguments are translated in turn. Text
    without an entry is returned unchanged (user data stays as entered). English and every new locale use the JSON
    catalogues; SMARTAGRI_EN_CATALOGUE=module restores the labels_en path for English."""
    code = active()
    if code == "en" and _en_module():
        return _legacy_translate_message(text, depth)
    if code in (DEFAULT_LOCALE, "sr-Cyrl"):
        code = "en"                       # default behaviour: translate_message always produced English
    return _generic_translate(code, text, depth)


def neutral_message(text: Any) -> Any:
    return NEUTRAL.get(text, text) if isinstance(text, str) else text
