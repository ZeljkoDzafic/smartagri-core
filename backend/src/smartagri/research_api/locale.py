"""Answer language of the research API.

English is the default answer language of web and API requests; SMARTAGRI_LOCALE=sr-Latn restores the local
language (Latin script). A request may ask for another supported locale with ?lang= or
the X-SmartAgri-Lang header (the client's language setting). The locale is set per request (i18n context variable),
so evaluation runs, the CLI and tests outside a request keep the default locale; the blind rating endpoints always
run in the default locale, as the rater guide expects.

The knowledge passages (corpus) are in the local language whatever the answer language: an English question is
mapped to its advice type and retrieval searches with the canonical local question of that type.
"""
from __future__ import annotations

import os
from typing import Optional

from .. import i18n

ENV = "SMARTAGRI_LOCALE"
HEADER = "x-smartagri-lang"
DEFAULT_ANSWER_LOCALE = "en"
SUPPORTED = ("en", "sr-Latn")
# Paths that always run in the default locale (blind rating: the protocol screen and its items).
DEFAULT_LOCALE_PATHS = ("/api/eval/",)


def _code(value: Optional[str]) -> Optional[str]:
    code = i18n.normalize(value)
    return code if code in SUPPORTED else None


def configured() -> str:
    """The server's answer locale: SMARTAGRI_LOCALE when it names a supported locale, otherwise English."""
    return _code(os.environ.get(ENV)) or DEFAULT_ANSWER_LOCALE


def for_request(path: str, query: Optional[str] = None, header: Optional[str] = None) -> str:
    """The locale of one request: the default locale for the rating endpoints, then ?lang=, the header, the server
    setting."""
    if path.startswith(DEFAULT_LOCALE_PATHS):
        return i18n.DEFAULT_LOCALE
    return _code(query) or _code(header) or configured()


def ensure_english_catalogue() -> None:
    """English labels come from module labels_en where the JSON catalogue registry is not shipped (the open core):
    without it i18n.L() and i18n.T() have no English catalogue to read. Only the English code path is affected; the
    default locale never reads either."""
    if i18n._catalogue() is None:
        os.environ.setdefault("AGROVID_EN_CATALOGUE", "module")
