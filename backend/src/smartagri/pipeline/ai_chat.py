"""Free AI conversation about one parcel, grounded in its data and in applicable corpus passages.

In the app this is a prototype feature outside the V0-V5 ladder. In the experiment the same function is
the strong LLM baseline VC ("LLM sa podacima i izvorima", comparison E5): evalkit.vc calls `answer`
with the scenario's context; there is no decision model (no q-gated sufficiency, no alpha, no delta).
The model sees the parcel's data with reliability and age, and passages that the applicability
predicate does not reject; it must cite passage ids. Afterwards the same checks as in the grounding
layer run: numbers must come from the data, sentences must be supported by a cited source or a
datum, and the prohibitions hold (no doses, no plant-protection products, no diagnosis from NDVI).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any, Callable, Dict, List, Optional

from .. import labels
from ..core.applicability import applicability
from ..core.grounding import split_sentences, support_check, unsupported_numbers
from ..core.quality import annotate_quality, values
from ..core.types import AdviceType, Applicability, Context, Reliability
from ..llm import LLMError, Provider, parse_json_object
from ..retrieval.corpus import Corpus
from ..retrieval.search import Retriever, fold
from .intent import classify
from .profile import quality_rows

SYSTEM_PROMPT = """Ti si agronomski savetnik za kukuruz u Bosni i Hercegovini. Razgovaraš sa poljoprivrednikom o jednoj parceli.
Piši na srpskom, latinicom, ekavski, jednostavno i konkretno, kao iskusan savetodavac.

Dobijaš JSON sa: podacima o parceli (svaki podatak ima pouzdanost i starost), pasusima iz stručnih izvora (svaki ima oznaku
id i status primenljivosti na ovu parcelu) i dosadašnjim razgovorom.

Pravila:
- Oslanjaj se samo na podatke o parceli i na pasuse. Za svaku stručnu tvrdnju navedi id pasusa iz kog potiče u polju cited.
- Ne izmišljaj brojeve. Broj smeš da navedeš samo ako se nalazi u podacima ili u pasusu.
- Nikad ne navodi dozu đubriva, količinu vode za navodnjavanje ni sredstvo za zaštitu bilja ili njegovu dozu.
  Za količine i doze uputi korisnika na poljoprivrednu savetodavnu službu (ne pominji aplikaciju ni druge delove sistema).
- Iz indeksa vegetacije (NDVI) ne zaključuj uzrok problema; on samo pokazuje gde treba pogledati.
- Ako je podatak nepouzdan ili star, reci to. Ako ti nedostaje podatak koji menja odgovor, postavi jedno konkretno pitanje.
- Ako pitanje nije o kukuruzu, ovoj parceli ili agronomiji, ljubazno reci da je to van tvoje oblasti.
- Odgovor neka ima najviše 150 reči; koristi kratke pasuse i, po potrebi, redove koji počinju sa "- ".
- Ne koristi Markdown (bez ** i #). Ne upisuj oznake izvora u tekst; navedi ih samo u polju cited.
- Dopunsko pitanje korisniku stavi u polje question_to_user, ne u tekst."""

# The app's chat replaces the advisory service as far as it safely can (product owner's decision, 13. 10. 2026):
# it also receives the decision model's conclusion and the system's calculations. The experiment's VC
# baseline keeps SYSTEM_PROMPT above and never sees the decision model.
APP_SYSTEM_PROMPT = """Ti si agronomski savetnik za kukuruz u Bosni i Hercegovini i zamenjuješ savetodavca na terenu koliko god je to bezbedno.
Razgovaraš sa poljoprivrednikom o jednoj parceli. Piši na srpskom, latinicom, ekavski, jednostavno i konkretno.

Dobijaš JSON sa: podacima o parceli (svaki podatak ima pouzdanost i starost), pasusima iz stručnih izvora (svaki ima id i
status primenljivosti), zaključkom sistema za odlučivanje (čin, radnja, rok ili uslov, šta nedostaje), proračunima sistema
i dosadašnjim razgovorom.

Kako savetuješ:
- Daj konkretan savet: šta da uradi, kada, kako i šta da proveri na njivi. Ne šalji korisnika dalje kada možeš sam da pomogneš.
- Zaključak sistema je obavezujući za čin: ako sistem traži podatak, ti ga zatraži; ako sistem preporučuje, objasni preporuku;
  ako sistem uslovljava savet, navedi uslov. Ne daj suprotan savet.
- Proračune sistema smeš da navedeš kao orijentaciju, uz napomenu da parametri još nisu stručno provereni ako je tako označeno.
  Druge brojeve ne izmišljaj: broj smeš da navedeš samo ako je u podacima, pasusu ili proračunu.
- Dozu azota sistem još ne računa: objasni kako se određuje (bilans: potreba prema prinosu, minus zemljište, minus već dato)
  i zatraži podatke koji nedostaju, umesto da daš broj.
- Na službu za zaštitu bilja uputi samo za izbor sredstva za zaštitu bilja, njegovu dozu i dijagnozu bolesti ili štetočina.
- Iz indeksa vegetacije (NDVI) ne zaključuj uzrok; on pokazuje gde treba pogledati.
- Ako je podatak nepouzdan ili star, reci to. Ako nedostaje podatak koji menja odgovor, postavi jedno konkretno pitanje.
- Za stručne tvrdnje navedi id pasusa u polju cited. Ne koristi Markdown (bez ** i #); oznake izvora ne upisuj u tekst.
- Odgovor najviše 180 reči; kratki pasusi i, po potrebi, redovi koji počinju sa "- ". Dopunsko pitanje stavi u question_to_user."""

SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "cited": {"type": "array", "items": {"type": "string"}},
        "question_to_user": {"type": "string"},
    },
    "required": ["text", "cited", "question_to_user"],
    "additionalProperties": False,
}
PROMPT_HASH = hashlib.sha256((SYSTEM_PROMPT + json.dumps(SCHEMA, sort_keys=True)).encode("utf-8")).hexdigest()
APP_PROMPT_HASH = hashlib.sha256((APP_SYSTEM_PROMPT + json.dumps(SCHEMA, sort_keys=True)).encode("utf-8")).hexdigest()


# Appended to the app prompt for a parcel whose crop has an active crop pack; the
# conclusion and calculations then come from the crop model (passed in by the service layer as `system_view_fn`, so
# this module never imports it). The VC baseline and the maize app prompt (APP_PROMPT_HASH) are unchanged.
CROP_PACK_NOTE = """Napomena o kulturi: ova parcela nije pod kukuruzom. Kultura je navedena u polju "kultura" i za nju savetuješ.
- Zaključak i proračuni sistema za ovu kulturu dolaze iz paketa parametara kulture (FAO-56 i BBCH; razvojne vrednosti koje
  agronom još nije pregledao). Kada ih navodiš, reci da su to razvojne vrednosti.
- Količinu vode i dozu đubriva za ovu kulturu ne navodi kao preporuku; proračun smeš da navedeš samo kao orijentaciju.
- Stručne tvrdnje o kukuruzu ne prenosi na ovu kulturu."""
CROP_APP_PROMPT_HASH = hashlib.sha256((APP_SYSTEM_PROMPT + "\n\n" + CROP_PACK_NOTE + json.dumps(SCHEMA, sort_keys=True))
                                      .encode("utf-8")).hexdigest()


def app_prompt(scope_note: Optional[str] = None, crop_note: Optional[str] = None) -> str:
    """The app prompt with the optional scope note and crop note appended (in this order)."""
    return APP_SYSTEM_PROMPT + "".join("\n\n" + n for n in (scope_note, crop_note) if n)


def app_prompt_hash(scope_note: Optional[str] = None, crop_note: Optional[str] = None) -> str:
    """APP_PROMPT_HASH, or the hash of the app prompt with the scope note (and the crop note)
    appended. Without the crop note the value is exactly the one recorded before the crop note existed."""
    if not scope_note and not crop_note:
        return APP_PROMPT_HASH
    return hashlib.sha256((app_prompt(scope_note, crop_note) + json.dumps(SCHEMA, sort_keys=True)).encode("utf-8")).hexdigest()

DOSE = re.compile(r"\d+(?:[.,]\d+)?\s*(kg|l|ml|g)\s*(?:N\s*)?/\s*ha", re.I)
REMOVE_BELOW = 0.2        # a sentence sharing less than this with every source and datum is removed
FLAG_BELOW = 0.5          # between REMOVE_BELOW and FLAG_BELOW it is kept and listed as weakly supported
PRESCRIBE = re.compile(r"\b(dajte|daj|primenite|primeni|dodajte|dodaj|rasturite|baci|bacite|stavite|prihranite|treba dati|potrebno je dati|preporucuj)")
META = ("strukturisan", "savetodavn", "strucn", "aplikacij", "proverit", "proveri", "obrat", "obidj", "zabelez", "sluzb",
        "pogledaj", "pogledajte")
CITATION_IN_TEXT = re.compile(r"\s*\((?:[a-z0-9]+(?:-[a-z0-9]+)+)(?:\s*,\s*[a-z0-9]+(?:-[a-z0-9]+)+)*\)")
PROTECTION = ("fungicid", "herbicid", "insekticid", "pesticid", "preparat", "sredstvo za zaštitu")
MAX_PASSAGES = 6
HISTORY_TURNS = 6


def _facts(ctx: Context) -> List[Dict[str, Any]]:
    rows = []
    for r in quality_rows(ctx):
        if r["reliability"] != "missing":
            rows.append({"input": r["input"], "label": r["label"], "value_text": r["value_text"],
                         "reliability": r["reliability"], "reliability_label": r["reliability_label"],
                         "age_days": r["age_days"]})
    return rows


def _passages(ctx: Context, message: str, corpus: Corpus, retriever: Retriever,
              advice_type: Optional[AdviceType] = None, query: Optional[str] = None) -> List[Dict[str, Any]]:
    """Applicable passages for the message. The advice type is classified from the message unless the
    caller knows it (the evaluation scenario states it); `query` replaces the message as search text."""
    t = advice_type or classify(message) or AdviceType.OUT_OF_SCOPE
    ctx.Q.advice_type = t if t != AdviceType.OUT_OF_SCOPE else AdviceType.SCOUTING
    q, vals = annotate_quality(ctx), values(ctx)
    out = []
    for p in retriever.search(query or message, t, k=20):
        r = applicability(p, ctx, q, vals, "parcel_conditions", True)
        if r.hard_fail == "crop":
            continue                                   # a passage about another crop is never shown
        if r.status == Applicability.NOT_APPLICABLE and r.hard_fail != "advice_type":
            continue
        doc = corpus.document(p)
        status = r.status if r.hard_fail != "advice_type" else Applicability.CONDITIONAL
        out.append({"id": p.id, "title": doc.get("title", p.document_id), "url": doc.get("url", ""),
                    "applicability": status.value, "applicability_label": labels.APPLICABILITY[status.value],
                    "conditions": [labels.CHECKS.get(c, c) for c in r.unmet + r.unverifiable], "text": p.text})
        if len(out) >= MAX_PASSAGES:
            break
    return out


def _system_view(ctx: Context, message: str, corpus: Corpus, retriever: Retriever,
                 advice_type: Optional[AdviceType], variant, query: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The decision model's conclusion and calculations for the question (app mode only)."""
    import copy
    from ..core.decide import decide
    from .generate import template_answer
    t = advice_type or classify(message)
    if t is None or t == AdviceType.OUT_OF_SCOPE:
        return None
    c = copy.deepcopy(ctx)
    c.Q.text, c.Q.advice_type = message, t
    d = decide(c, retriever.search(query or message, t), variant)
    a = template_answer(c, d, corpus)
    calcs = []
    for t_ in d.tools:                       # all calculations, flagged when the quantity is not validated
        if t_.output:
            calcs.append({"proracun": t_.tool, "ulazi": t_.inputs, "rezultat": t_.output,
                          "strucno_provereno": bool(d.policy.allow_quantity and a["action"] and a["action"].get("quantity"))})
    return {"cin": a["act_label"], "zakljucak": a["summary"], "radnja": a["action"], "obrazlozenje": a["rationale"],
            "nedostaje": (a.get("basis") or {}).get("missing"), "pitanje_sistema": (a["next_question"] or {}).get("text"),
            "ogranicenja": a["limitations"], "proracuni": calcs}


def answer(provider: Provider, ctx: Context, message: str, history: List[Dict[str, str]],
           corpus: Corpus, retriever: Retriever, advice_type: Optional[AdviceType] = None,
           query: Optional[str] = None, mode: str = "baseline", variant=None, scope_note: Optional[str] = None,
           retrieve: bool = True, system_view_fn: Optional[Callable[..., Optional[Dict[str, Any]]]] = None,
           crop: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """mode="app": the app's advisor, which sees the decision model run under `variant` (the full model);
    mode="baseline": the VC baseline of the experiment, which does not.
    `scope_note` is appended to the app prompt for parcels outside the home tier (the prompt
    hash recorded is then app_prompt_hash(scope_note)); `retrieve=False` gives the model no corpus passages (outside
    tier: the core pack's scope excludes the parcel). The baseline ignores both.
    `system_view_fn(ctx, message, advice_type, query)` replaces the maize system view (a crop
    with an active crop pack: the crop model's conclusion), `crop` ({naziv, paket}) is added to the payload and the crop
    note to the prompt (hash app_prompt_hash(scope_note, CROP_PACK_NOTE)). The checks below are unchanged."""
    started = time.time()
    if mode != "app":
        scope_note, retrieve, system_view_fn, crop = None, True, None, None
    crop_note = CROP_PACK_NOTE if crop is not None else None
    facts = _facts(ctx)
    passages = _passages(ctx, message, corpus, retriever, advice_type, query) if retrieve else []
    payload = {"parcela": {"datum_odluke": ctx.as_of.date().isoformat() if ctx.as_of else None,
                           "podaci": [{k: f[k] for k in ("label", "value_text", "reliability_label", "age_days")} for f in facts]},
               "izvori": [{k: p[k] for k in ("id", "title", "applicability_label", "conditions", "text")} for p in passages],
               "pitanje": message}
    if crop is not None:
        payload["kultura"] = crop
    if system_view_fn is not None and mode == "app" and variant is not None:
        system_view = system_view_fn(ctx, message, advice_type, query)
    else:
        system_view = _system_view(ctx, message, corpus, retriever, advice_type, variant, query) \
            if mode == "app" and variant is not None else None
    if system_view is not None:
        payload["zakljucak_sistema"] = system_view
    messages = list(history[-2 * HISTORY_TURNS:]) + [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
    r = provider.complete(app_prompt(scope_note, crop_note) if mode == "app" else SYSTEM_PROMPT, messages,
                          json_schema=SCHEMA, max_tokens=2000)
    out = r.data if r.data is not None else parse_json_object(r.text)
    text = (out.get("text") or "").strip()
    text = CITATION_IN_TEXT.sub("", text).replace("**", "").replace("__", "")
    question = (out.get("question_to_user") or "").strip()
    if not text and not question:
        raise LLMError("empty answer")

    # Grounding: numbers, support, prohibitions.
    by_id = {p["id"]: p for p in passages}
    cited = [by_id[c] for c in out.get("cited") or [] if c in by_id]
    support_texts = [p["text"] for p in passages] + [f["label"] + " " + f["value_text"] for f in facts]
    if system_view is not None:
        support_texts += [json.dumps(system_view, ensure_ascii=False)] + list(system_view["obrazlozenje"]) + \
            [system_view["zakljucak"]]
    warnings: List[str] = []
    kept, removed_sentences, weak_sentences, bad_numbers = [], [], [], []
    checked = 0
    number_sources = [values(ctx), [p["text"] for p in passages], [f["value_text"] for f in facts],
                      [f["label"] for f in facts], system_view or {}]
    for para in text.split("\n"):
        bullet = para.lstrip().startswith("- ")
        body = para.lstrip()[2:] if bullet else para
        keep = []
        for sentence in (split_sentences(body) if body.strip() else []):
            checked += 1
            nums = unsupported_numbers(sentence, [], number_sources)
            score = support_check([sentence], support_texts)[0]["score"]
            meta = any(w in fold(sentence) for w in META) or sentence.rstrip().endswith("?")
            # Invented figures are always removed; a dose is removed when the sentence prescribes it
            # (stating data, e.g. "već dato 45 kg N/ha", is allowed when the figure comes from the parcel).
            if nums or (DOSE.search(sentence) and PRESCRIBE.search(fold(sentence))):
                removed_sentences.append(sentence)
                bad_numbers += nums
            elif score < REMOVE_BELOW and not meta:
                removed_sentences.append(sentence)
            else:
                if score < FLAG_BELOW and not meta:
                    weak_sentences.append(sentence)
                keep.append(sentence)
        if keep:
            kept.append(("- " if bullet else "") + " ".join(keep))
        elif not body.strip():
            kept.append("")
    clean = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    if question:
        clean = (clean + "\n\n" + question).strip()
    if removed_sentences:
        warnings.append("Deo odgovora je uklonjen jer nije potkrepljen podacima parcele ni izvorima.")
    if not clean:
        clean = "Ne mogu da dam potkrepljen odgovor na osnovu podataka ove parcele i dostupnih izvora."
    referral = None
    low = fold(message + " " + text)
    if (advice_type or classify(message)) == AdviceType.OUT_OF_SCOPE or any(w in low for w in PROTECTION) \
            or (mode == "app" and any(w in low for w in ("bolest", "stetoc", "simptom"))):
        referral = labels.REFERRAL
    stale = [f["label"] for f in facts if f["reliability"] == Reliability.LOW.value]
    if stale:
        warnings.append("Niska pouzdanost podataka: %s." % ", ".join(stale).lower())
    return {
        "text": clean, "citations": [{k: c[k] for k in ("id", "title", "url", "applicability", "applicability_label")}
                                     for c in cited],
        "data_used": facts, "warnings": warnings, "referral": referral, "provider": r.provider, "model": r.model,
        "question_to_user": question,
        "grounding": {"action": "sentences_removed" if removed_sentences else "checked", "checked_sentences": checked,
                      "unsupported_numbers": bad_numbers, "unsupported_sentences": removed_sentences,
                      "weakly_supported_sentences": weak_sentences},
        "_cost": {"seconds": round(time.time() - started, 2), "input_tokens": r.input_tokens,
                  "output_tokens": r.output_tokens, "usd": r.usd},
        "_raw_text": text, "_prompt_hash": app_prompt_hash(scope_note, crop_note) if mode == "app" else PROMPT_HASH,
        **({"_system_view": system_view} if mode == "app" else {}), "_passage_ids": [p["id"] for p in passages],
    }


# ------------------------------------------------------------------ English answers in the app
# The model writes and every check above runs in the local language, exactly as in the default locale (the
# VC baseline of the experiment never comes here). The checked text is then translated by a second call, and
# the translation must keep every number of the checked text (same multiset) and must not prescribe a dose
# (DOSE_EN together with PRESCRIBE_EN in one sentence); otherwise the checked local text is shown with a warning.
DOSE_EN = re.compile(r"\d+(?:[.,]\d+)?\s*(kg|l|ml|g|lb|lbs|t)\s*(?:N\s*)?(?:/|per)\s*(ha|hectare|acre)\b", re.I)
PRESCRIBE_EN = re.compile(r"\b(apply|give|add|spread|broadcast|put on|top-?dress (?:with|at)|use|you should (?:apply|give|add|use)"
                          r"|it is necessary to (?:apply|give|add)|we recommend|i recommend|recommended (?:rate|dose))\b", re.I)
TRANSLATE_PROMPT = """You translate an agronomic answer for a farmer from the local language (Latin script) into plain English.
Translate faithfully, sentence by sentence: do not add, drop, soften or strengthen any statement, and add no advice.
Copy every number, unit and date exactly as written in the source (for example 3,5 mm stays 3,5 mm and 15. 7. 2026.
stays 15. 7. 2026.). Keep names of products, places, sources and identifiers unchanged. Keep lines that start with
"- " as such lines. Return the translated answer in "text" and the translated follow-up question in "question_to_user"
(empty when the source question is empty)."""
TRANSLATE_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}, "question_to_user": {"type": "string"}},
    "required": ["text", "question_to_user"],
    "additionalProperties": False,
}
TRANSLATE_PROMPT_HASH = hashlib.sha256((TRANSLATE_PROMPT + json.dumps(TRANSLATE_SCHEMA, sort_keys=True)).encode("utf-8")).hexdigest()


def _numbers(text: str) -> List[float]:
    from ..core.grounding import _numbers_in
    return sorted(_numbers_in(text or ""))


def translation_problems(local_text: str, local_question: str, text: str, question: str) -> List[str]:
    """Why an English translation may not be shown (empty list = it passes)."""
    problems = []
    a, b = _numbers(local_text + " " + local_question), _numbers(text + " " + question)
    if len(a) != len(b) or any(abs(x - y) > 1e-6 for x, y in zip(a, b)):
        problems.append("numbers_changed")
    for sentence in split_sentences((text + "\n" + question).replace("\n", " ")):
        if DOSE_EN.search(sentence) and PRESCRIBE_EN.search(sentence):
            problems.append("dose_prescribed")
            break
    if local_text.strip() and not text.strip():
        problems.append("empty_translation")
    return problems


def to_english(provider: Provider, out: Dict[str, Any], ctx: Context) -> Dict[str, Any]:
    """The answer of `answer(..., mode="app")` (computed in the default locale) for an English user."""
    from ..i18n import L, T, use
    local_text, local_question = out["text"], out.get("question_to_user") or ""
    body = local_text[: -len(local_question)].rstrip() if local_question and local_text.endswith(local_question) else local_text
    translation: Dict[str, Any] = {"prompt_hash": TRANSLATE_PROMPT_HASH, "problems": []}
    english, english_question = None, ""
    cost = out.get("_cost") or {}
    try:
        r = provider.complete(TRANSLATE_PROMPT, [{"role": "user", "content": json.dumps(
            {"text": body, "question_to_user": local_question}, ensure_ascii=False)}], json_schema=TRANSLATE_SCHEMA,
            max_tokens=2000)
        data = r.data if r.data is not None else parse_json_object(r.text)
        english = (data.get("text") or "").strip()
        english_question = (data.get("question_to_user") or "").strip()
        for k, v in (("input_tokens", r.input_tokens), ("output_tokens", r.output_tokens), ("usd", r.usd)):
            if isinstance(v, (int, float)):
                cost[k] = (cost.get(k) or 0) + v
        translation["problems"] = translation_problems(body, local_question, english, english_question)
    except LLMError as exc:
        translation["problems"] = ["error: %s" % str(exc)[:80]]
    with use("en"):
        facts = _facts(ctx)
        warnings = []
        if out["grounding"].get("unsupported_sentences"):
            warnings.append(T("Deo odgovora je uklonjen jer nije potkrepljen podacima parcele ni izvorima."))
        stale = [f["label"] for f in facts if f["reliability"] == Reliability.LOW.value]
        if stale:
            warnings.append(T("Niska pouzdanost podataka: %s.") % ", ".join(stale).lower())
        ok = english is not None and not translation["problems"]
        if not ok:
            warnings.append(T("Prevod na engleski nije prošao proveru; prikazan je odgovor na lokalnom jeziku."))
        citations = [dict(c, applicability_label=L().APPLICABILITY.get(c["applicability"], c["applicability_label"]))
                     for c in out["citations"]]
        referral = L().REFERRAL if out.get("referral") else None
    if ok:
        text = (english + ("\n\n" + english_question if english_question else "")).strip()
        question = english_question
    else:
        text, question = local_text, local_question
    translation["shown"] = "en" if ok else "local"
    return dict(out, text=text, question_to_user=question, text_local=local_text, data_used=facts, warnings=warnings,
                citations=citations, referral=referral, translation=translation, _cost=cost)


# ------------------------------------------------------------------ chat language (any language)
# The chat answers in the language of the user's message, independently of the interface locale. A message that is
# not in the local language is pivoted: one call names its language and translates it into the local language
# (Latin script); intent, retrieval, the V5 system view and every check above run on that local text exactly as for a
# local message; a second call translates the checked local answer into the message's language. The translation is
# shown only if it passes a language-agnostic gate (same multiset of numbers and units as the checked local text, no
# new number + mass/volume unit per area, the same citation markers); English also keeps DOSE_EN/PRESCRIBE_EN.
# Otherwise the checked local text is shown with a short notice in the user's language (fallback English).
# The VC baseline of the experiment never comes here.
NOTICE_EN = "The translation of this answer could not be verified, so the checked answer is shown in the local language."
PIVOT_PROMPT = """You receive a farmer's chat message about a maize parcel. It can be written in any language.
1. Identify the language of "message": return its BCP 47 code in "language" (for example de, hu, ru, uk, mk, bg, sl,
ro, sq, ar, en) and its English name in "language_name". If the message is in the local language of the service
(Serbian, Croatian, Bosnian or Montenegrin, Latin or Cyrillic script), return "sr" and leave the other fields empty.
2. Translate "message" faithfully into the local language (Serbian, Latin script, ekavian) in "text_local". Do not
answer it, add nothing, drop nothing; copy every number, unit, date, name and identifier exactly as written.
3. Translate the English sentence "notice_en" into the language of the message in "notice"."""
PIVOT_SCHEMA = {
    "type": "object",
    "properties": {"language": {"type": "string"}, "language_name": {"type": "string"},
                   "text_local": {"type": "string"}, "notice": {"type": "string"}},
    "required": ["language", "language_name", "text_local", "notice"],
    "additionalProperties": False,
}
PIVOT_PROMPT_HASH = hashlib.sha256((PIVOT_PROMPT + json.dumps(PIVOT_SCHEMA, sort_keys=True)).encode("utf-8")).hexdigest()
TRANSLATE_ANY_PROMPT = """You translate an agronomic answer for a farmer from the local language (Serbian, Croatian or
Bosnian, Latin script) into the language named in "target_language" (BCP 47 code and English name), in that language's
usual script. Translate faithfully, sentence by sentence: do not add, drop, soften or strengthen any statement, and add
no advice, numbers, doses or product names. Copy every number, unit and date exactly as written in the source, with
digits 0-9 and the source's decimal comma (for example 3,5 mm stays 3,5 mm, 45 kg N/ha stays 45 kg N/ha and 15. 7. 2026.
stays 15. 7. 2026.). Keep names of products, places, sources, identifiers and any source markers unchanged. Keep every
referral to the agricultural advisory service or the plant-protection service. Keep lines that start with "- " as such
lines. Return the translated answer in "text" and the translated follow-up question in "question_to_user" (empty when
the source question is empty)."""
TRANSLATE_ANY_PROMPT_HASH = hashlib.sha256((TRANSLATE_ANY_PROMPT + json.dumps(TRANSLATE_SCHEMA, sort_keys=True))
                                           .encode("utf-8")).hexdigest()


def _add_cost(cost: Dict[str, Any], r) -> None:
    for k, v in (("input_tokens", r.input_tokens), ("output_tokens", r.output_tokens), ("usd", r.usd)):
        if isinstance(v, (int, float)):
            cost[k] = (cost.get(k) or 0) + v


def pivot_in(provider: Provider, message: str) -> Dict[str, Any]:
    """One call: the message's language and its translation into the local language (Latin script).
    Returns {language, language_name, text_local, notice, problems, prompt_hash, cost}; raises LLMError."""
    from . import language as lang
    r = provider.complete(PIVOT_PROMPT, [{"role": "user", "content": json.dumps(
        {"message": message, "notice_en": NOTICE_EN}, ensure_ascii=False)}], json_schema=PIVOT_SCHEMA, max_tokens=1500)
    data = r.data if r.data is not None else parse_json_object(r.text)
    code = re.sub(r"[^A-Za-z0-9-]", "", str(data.get("language") or ""))[:20]
    text_local = (data.get("text_local") or "").strip()
    notice = (data.get("notice") or "").strip()
    problems = []
    if text_local and not lang.same_numbers(message, text_local):
        problems.append("inbound_numbers_changed")
    if not notice or len(notice) > 300 or re.search(r"\d", lang.ascii_digits(notice)):
        notice = NOTICE_EN
    cost: Dict[str, Any] = {}
    _add_cost(cost, r)
    return {"language": code, "language_name": (data.get("language_name") or "").strip()[:60], "text_local": text_local,
            "notice": notice, "problems": problems, "prompt_hash": PIVOT_PROMPT_HASH, "cost": cost}


def gate_problems(local_text: str, local_question: str, text: str, question: str) -> List[str]:
    """Language-agnostic gate for a translation of the checked local text (empty list = it passes)."""
    from . import language as lang
    src, dst = local_text + "\n" + local_question, text + "\n" + question
    problems = []
    if local_text.strip() and not text.strip():
        problems.append("empty_translation")
    if not lang.same_numbers(src, dst):
        problems.append("numbers_changed")
    if sorted(u for _, u in lang.units(src)) != sorted(u for _, u in lang.units(dst)):
        problems.append("units_changed")
    added = list(lang.doses(dst))
    for d in lang.doses(src):
        if d in added:
            added.remove(d)
    if added:
        problems.append("dose_added")
    have = lang.citation_markers(dst)
    for m in lang.citation_markers(src):
        if m in have:
            have.remove(m)
        else:
            problems.append("citation_dropped")
            break
    return problems


def to_language(provider: Provider, out: Dict[str, Any], ctx: Context, target: str, name: str,
                ui_locale: str = "sr-Latn", notice: Optional[str] = None) -> Dict[str, Any]:
    """The checked local answer of `answer(..., mode="app")` translated into `target` (BCP 47) and gated.
    The structured parts (data labels, warnings, citation labels, referral) follow `ui_locale`, not `target`."""
    local_text, local_question = out["text"], out.get("question_to_user") or ""
    body = local_text[: -len(local_question)].rstrip() if local_question and local_text.endswith(local_question) else local_text
    english = target == "en"
    translation: Dict[str, Any] = {"prompt_hash": TRANSLATE_PROMPT_HASH if english else TRANSLATE_ANY_PROMPT_HASH,
                                   "problems": [], "target": target}
    translated, translated_question = None, ""
    cost = out.get("_cost") or {}
    try:
        if english:
            r = provider.complete(TRANSLATE_PROMPT, [{"role": "user", "content": json.dumps(
                {"text": body, "question_to_user": local_question}, ensure_ascii=False)}], json_schema=TRANSLATE_SCHEMA,
                max_tokens=2000)
        else:
            r = provider.complete(TRANSLATE_ANY_PROMPT, [{"role": "user", "content": json.dumps(
                {"target_language": {"code": target, "name": name}, "text": body, "question_to_user": local_question},
                ensure_ascii=False)}], json_schema=TRANSLATE_SCHEMA, max_tokens=2500)
        data = r.data if r.data is not None else parse_json_object(r.text)
        translated = (data.get("text") or "").strip()
        translated_question = (data.get("question_to_user") or "").strip()
        _add_cost(cost, r)
        problems = translation_problems(body, local_question, translated, translated_question) if english else []
        problems += [p for p in gate_problems(body, local_question, translated, translated_question) if p not in problems]
        translation["problems"] = problems
    except LLMError as exc:
        translation["problems"] = ["error: %s" % str(exc)[:80]]
    ok = translated is not None and not translation["problems"]
    failed = None
    if not ok:
        failed = "en" if english and ui_locale == "en" else "any"
    facts, warnings, citations, referral = relabel(out, ctx, ui_locale, failed)
    if ok:
        text = (translated + ("\n\n" + translated_question if translated_question else "")).strip()
        question = translated_question
    else:
        text, question = local_text, local_question
        translation["notice"] = notice or NOTICE_EN
    translation["shown"] = target if ok else "local"
    return dict(out, text=text, question_to_user=question, text_local=local_text, data_used=facts, warnings=warnings,
                citations=citations, referral=referral, translation=translation, _cost=cost)


def relabel(out: Dict[str, Any], ctx: Context, ui_locale: str, failed: Optional[str] = None):
    """The structured parts of a checked answer (data labels, warnings, citation labels, referral) in the interface
    locale: regenerated in English for `en` (as `to_english` does), as computed (default locale) otherwise; the API
    layer transliterates them for sr-Cyrl. `failed` adds the notice that the translation was not shown."""
    from ..i18n import DEFAULT_LOCALE, L, T, use
    if ui_locale == "en":
        with use("en"):
            facts = _facts(ctx)
            warnings = []
            if out["grounding"].get("unsupported_sentences"):
                warnings.append(T("Deo odgovora je uklonjen jer nije potkrepljen podacima parcele ni izvorima."))
            stale = [f["label"] for f in facts if f["reliability"] == Reliability.LOW.value]
            if stale:
                warnings.append(T("Niska pouzdanost podataka: %s.") % ", ".join(stale).lower())
            if failed == "en":
                warnings.append(T("Prevod na engleski nije prošao proveru; prikazan je odgovor na lokalnom jeziku."))
            elif failed:
                warnings.append(T("Prevod odgovora nije prošao proveru; prikazan je odgovor na lokalnom jeziku."))
            citations = [dict(c, applicability_label=L().APPLICABILITY.get(c["applicability"], c["applicability_label"]))
                         for c in out["citations"]]
            referral = L().REFERRAL if out.get("referral") else None
        return facts, warnings, citations, referral
    with use(DEFAULT_LOCALE):
        warnings = list(out["warnings"])
        if failed:
            warnings.append(T("Prevod odgovora nije prošao proveru; prikazan je odgovor na lokalnom jeziku."))
    return out["data_used"], warnings, out["citations"], out.get("referral")
