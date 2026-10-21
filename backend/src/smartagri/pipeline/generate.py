"""Turn a core Decision into a structured answer.

The template generator is deterministic and needs no language model. The Anthropic generator
lets a model phrase the summary and rationale (and, for variants without a sufficiency layer,
choose the act); every number it writes is then checked against tool outputs and context values.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from .. import config
from ..i18n import L, T, current
from ..core.grounding import split_sentences, support_check, unsupported_numbers
from ..core.quality import values
from ..core.rules import decide_action_core, n_credit
from ..core.types import AdviceType, Applicability, Context, Decision, Reliability
from ..retrieval.corpus import Corpus
from .judge import make_judge

# Tools whose inputs or outputs reveal an irrigation amount; shown only when the policy allows a quantity.
QUANTITY_TOOLS = ("net_irrigation_need", "gross_irrigation", "application_time")


# ------------------------------------------------------------------ deterministic parts

def _inputs_for(t: AdviceType) -> List[str]:
    spec = config.load("requirements")["advice_types"].get(t.value, {})
    names = [r["input"] for r in spec.get("required", [])]
    for group in spec.get("one_of", []):
        names += [g["input"] for g in group]
    return names + list(spec.get("desirable", []))


def data_used(ctx: Context, d: Decision) -> List[Dict[str, Any]]:
    vals = values(ctx)
    rows = []
    for name in _inputs_for(d.advice_type):
        q = d.quality[name]
        if q.reliability == Reliability.MISSING and name == "soil_moisture_sensor":
            continue
        rows.append({"input": name, "label": L().INPUTS.get(name, name), "value_text": L().value_text(name, vals.get(name)),
                     "reliability": q.reliability.value, "reliability_label": L().RELIABILITY[q.reliability.value],
                     "age_days": q.age_days})
    return rows


def sources(d: Decision, corpus: Corpus) -> List[Dict[str, Any]]:
    by_id = {r.passage_id: r for r in d.applicability}
    out = []
    for pid in d.passage_budget:
        p, r = corpus.passage(pid), by_id[pid]
        if p is None:
            continue
        doc = corpus.document(p)
        conditions = [T("nije zadovoljeno: ") + L().CHECKS.get(c, c) for c in r.unmet]
        conditions += [T("nije proverljivo: ") + L().CHECKS.get(c, c) for c in r.unverifiable]
        out.append({"passage_id": pid, "title": doc.get("title", p.document_id), "url": doc.get("url", ""),
                    "applicability": r.status.value, "applicability_label": L().APPLICABILITY[r.status.value],
                    "conditions": conditions, "excerpt": p.text})
    return out


def calculations(d: Decision) -> List[Dict[str, Any]]:
    out = []
    for t in d.tools:
        if t.tool in QUANTITY_TOOLS and not d.policy.allow_quantity:
            continue                                  # no quantity is shown unless the policy allows one
        out.append({"tool": t.tool, "label": L().TOOLS.get(t.tool, t.tool), "formula": t.formula,
                    "inputs": t.inputs, "output": t.output, "source_ref": t.source_ref, "reason": t.reason})
    return out


def _phrase(core: Optional[str]) -> Optional[Tuple[str, str]]:
    return L().CORE_ACTIONS.get((core or "").split("|")[0])


def _quantity(d: Decision) -> Optional[str]:
    if not d.policy.allow_quantity or d.advice_type != AdviceType.IRRIGATION_AMOUNT:
        return None
    if not config.load("rules")["irrigation"]["quantity_validated"]:
        return None                                   # parameters of the balance are not yet reviewed
    gross = next((t for t in d.tools if t.tool == "gross_irrigation" and t.output), None)
    net = next((t for t in d.tools if t.tool == "net_irrigation_need" and t.output), None)
    if not gross or not net or gross.output["gross_mm"] <= 0:
        return None
    text = T("Bruto norma %s mm po navodnjavanju, odnosno %s m³ po hektaru.") % (
        L().num(gross.output["gross_mm"]), L().num(gross.output["m3_per_ha"]))
    if net.output["applications"] > 1:
        text += T(" Ukupan deficit pokriti u %d navodnjavanja.") % net.output["applications"]
    return text


def _missing_text(d: Decision) -> str:
    names = d.sufficiency.missing_inputs() if d.sufficiency else []
    names = [n for n in names if n != "soil_moisture_sensor"]
    return ", ".join(L().INPUTS.get(n, n).lower() for n in names)


def _plan_by_answer(ctx: Context, d: Decision) -> List[str]:
    """For a conditional answer with a question: what we would advise for each possible reply."""
    q = d.question
    if not q or not q.input:
        return []
    vals, lines = values(ctx), []
    for option in config.load("asking")["inputs"][q.input].get("plausible_values", []):
        phrase = _phrase(decide_action_core(d.advice_type, dict(vals, **{q.input: option})))
        word = L().VALUE_WORDS.get(str(option), L().value_text(q.input, option))
        if phrase:
            lines.append(T("Ako je odgovor „%s”: %s %s") % (word, phrase[0], phrase[1]))
    return lines


def rationale(ctx: Context, d: Decision) -> List[str]:
    v, t, out = values(ctx), d.advice_type, []
    def rel(name):
        return L().RELIABILITY[d.quality[name].reliability.value]
    if v.get("phenophase") is not None and t != AdviceType.SCOUTING:
        out.append(T("Faza razvoja: BBCH %s (pouzdanost: %s).") % (v["phenophase"], rel("phenophase")))
    if t in (AdviceType.IRRIGATION_TIMING, AdviceType.IRRIGATION_AMOUNT):
        if v.get("precip_forecast_3d") is not None:
            out.append(T("Prognoza padavina za naredna tri dana: %s mm.") % L().num(v["precip_forecast_3d"]))
        if v.get("et0_past_7d") is not None:
            out.append(T("Referentna evapotranspiracija u prethodnih sedam dana: %s mm; padavine: %s mm.")
                       % (L().num(v["et0_past_7d"]), L().num(v.get("precip_past_7d"))))
        if v.get("soil_water_status"):
            sw = d.quality["soil_water_status"]
            word = L().VALUE_WORDS[v["soil_water_status"]]
            if (sw.source_ref or "").startswith("last_irrigation:"):
                out.append(T("Stanje vode u zemljištu procenjeno je kao %s jer je parcela navodnjavana %s sa %s mm "
                             "(procena, pouzdanost: %s).") % (word, L().fmt_date(ctx.A.last_irrigation_date),
                                                            L().num(ctx.A.last_irrigation_mm), rel("soil_water_status")))
            elif (sw.source_ref or "").startswith("observation:wilting"):
                out.append(T("Stanje vode u zemljištu procenjeno je kao %s prema prijavljenom venjenju (pouzdanost: %s); "
                             "potvrdite ga na njivi.") % (word, rel("soil_water_status")))
            else:
                out.append(T("Stanje vode u zemljištu prema vašem navodu: %s.") % word)
    elif t in (AdviceType.FERTILIZATION_PLAN, AdviceType.FERTILIZATION_TIMING):
        if v.get("precip_forecast_7d") is not None:
            out.append(T("Prognoza padavina za narednih sedam dana: %s mm.") % L().num(v["precip_forecast_7d"]))
        if v.get("previous_fertilization") is not None:
            out.append(T("Dosadašnje đubrenje: %s.") % L().value_text("previous_fertilization", v["previous_fertilization"]))
        if t == AdviceType.FERTILIZATION_PLAN and "|dose:" in (d.core_action or "") \
                and not d.core_action.endswith("dose:?") and n_credit(v):
            legume = v.get("previous_crop") in config.load("rules")["optional_inputs"]["legumes"]
            source = T("preduseva i stajnjaka") if legume and v.get("manure") else (T("preduseva") if legume else T("stajnjaka"))
            out.append(T("Zbog %s računa se sa delom azota iz zemljišta, pa je preporučeni opseg doze niži.") % source)
    elif t == AdviceType.FIELD_OPS_WINDOW:
        if v.get("precip_forecast_3d") is not None:
            out.append(T("Prognoza padavina za naredna tri dana: %s mm.") % L().num(v["precip_forecast_3d"]))
        if v.get("wind_forecast") is not None:
            out.append(T("Najjači prognozirani vetar u narednih sedam dana: %s m/s.") % L().num(v["wind_forecast"]))
        if v.get("temp_forecast"):
            out.append(T("Prognozirana temperatura: %s.") % L().value_text("temp_forecast", v["temp_forecast"]))
    elif t == AdviceType.SCOUTING and v.get("ndvi_latest") is not None:
        q = d.quality["ndvi_latest"]
        out.append(T("Poslednji upotrebljiv snimak je star %s dana, sa %s %% upotrebljivih piksela (pouzdanost: %s).")
                   % (L().num(q.age_days), L().num((q.coverage or 0) * 100), rel("ndvi_latest")))
        if v.get("ndvi_spatial_contrast") is not None:
            out.append(T("Razlika između bujnijih i slabijih delova parcele (NDVI): %s.") % L().num(v["ndvi_spatial_contrast"], 2))
        if v.get("ndvi_trend") is not None:
            out.append(T("Promena indeksa u poslednjih 14 dana: %s.") % L().num(v["ndvi_trend"], 2))
    return out


def recent_referral_events(ctx: Context) -> List[str]:
    """Kinds of recent field observations (within rules.optional_inputs.field_event_days) that need plant protection."""
    opt = config.load("rules")["optional_inputs"]
    return [k for k in (values(ctx).get("field_observation") or []) if k in opt["referral_events"]]


def limitations(ctx: Context, d: Decision, used: List[Dict[str, Any]]) -> List[str]:
    out = []
    if recent_referral_events(ctx):
        out.append(L().PLANT_PROTECTION_REFERRAL)            # never a product (spec 009 FR-004)
    analysis = values(ctx).get("soil_analysis")
    if d.advice_type in (AdviceType.FERTILIZATION_PLAN, AdviceType.FERTILIZATION_TIMING) and isinstance(analysis, dict) \
            and analysis.get("ph") is not None:
        lo, hi = config.load("rules")["optional_inputs"]["ph_range"]
        if not lo <= float(analysis["ph"]) <= hi:
            out.append(T("pH zemljišta (%s) je van opsega %s–%s; proverite sa savetodavcem potrebu za kalcifikacijom "
                         "ili korekcijom pH.") % (L().num(analysis["ph"]), L().num(lo), L().num(hi)))
    if d.quality["phenophase"].origin.value == "derived" and d.advice_type != AdviceType.SCOUTING:
        out.append(T("Faza razvoja je procenjena iz datuma setve; potvrdite je na njivi."))
    for row in used:
        if row["reliability"] == "low":
            out.append(T("%s: niska pouzdanost (%s).") % (row["label"], d.quality[row["input"]].basis))
    if d.advice_type == AdviceType.SCOUTING:
        out.append(L().NO_DIAGNOSIS)
        if d.quality["ndvi_latest"].reliability == Reliability.MISSING:
            out.append(T("Nema upotrebljivog satelitskog snimka; savet se ne oslanja na satelitske podatke."))
    if d.advice_type == AdviceType.FERTILIZATION_PLAN:
        out.append(L().DOSE_NOTE)
    if d.advice_type == AdviceType.IRRIGATION_AMOUNT and not config.load("rules")["irrigation"]["quantity_validated"]:
        out.append(L().QUANTITY_NOTE)
    for c in d.conflicts:
        if c.resolution == "prefer_applicable":
            out.append(T("Izvori se razlikuju; prednost je data izvoru koji je primenljiv na ovu parcelu."))
        elif c.resolution == "report":
            out.append(T("Izvori se razlikuju u jednom delu saveta; oba stava su navedena među izvorima."))
    if any(s.status == Applicability.CONDITIONAL for s in d.applicability if s.passage_id in d.passage_budget):
        out.append(T("Deo izvora je samo uslovno primenljiv na ovu parcelu; uslovi su navedeni uz izvor."))
    return out


def next_question(d: Decision) -> Optional[Dict[str, Any]]:
    q = d.question
    if not q or not q.input or d.policy.act is None or d.policy.act.value not in ("ask", "conditional"):
        return None
    options = list(L().OPTIONS.get(q.input, [])) + [L().DECLINE_OPTION]
    text, how = q.text, q.how_to_obtain
    localized = getattr(L(), "QUESTIONS", {}).get(q.input)     # spec 017: the question of asking.yaml in English
    if localized:
        text, how = localized
    return {"input": q.input, "text": text, "how_to_obtain": how, "options": options}


def _required_groups(t: AdviceType) -> List[List[str]]:
    """R_t of requirements.yaml as groups: each required input alone, each one_of group together."""
    spec = config.load("requirements")["advice_types"].get(t.value, {})
    return [[r["input"]] for r in spec.get("required", [])] + \
        [[g["input"] for g in group] for group in spec.get("one_of", [])]


def basis(ctx: Context, d: Decision) -> Dict[str, Any]:
    """The "Na osnovu čega" line (spec 010): which inputs of R_t decided, with their reliability, and which are missing.

    Deciding = the required and one_of inputs of R_t that are present (any reliability except missing).
    Missing = the sufficiency layer's missing inputs, without those already listed as deciding (an input that is
    present but below its minimum reliability is shown once, as deciding with its low grade). Variants without a
    sufficiency layer list the R_t groups none of whose inputs is present. Display only: never changes the act.
    """
    vals = values(ctx)
    deciding: List[Dict[str, Any]] = []
    for group in _required_groups(d.advice_type):
        for name in group:
            q = d.quality.get(name)
            if q is None or q.reliability == Reliability.MISSING:
                continue
            deciding.append({"input": name, "label": L().INPUTS.get(name, name),
                             "value_text": L().value_text(name, vals.get(name)),
                             "phrase": L().basis_phrase(name, vals.get(name)),
                             "reliability": q.reliability.value,
                             "reliability_label": L().RELIABILITY[q.reliability.value]})
    shown = {r["input"] for r in deciding}
    if d.sufficiency is not None:
        names = d.sufficiency.missing_inputs()
    else:
        names = [g[0] for g in _required_groups(d.advice_type) if not shown & set(g)]
    missing_names = [n for n in names if n not in shown and n != "soil_moisture_sensor"]
    if not missing_names and any(n == "soil_moisture_sensor" for n in names) and "soil_water_status" not in shown:
        missing_names = ["soil_water_status"]
    missing = [L().lower_first(L().INPUTS.get(n, n)) for n in missing_names]
    parts = []
    if deciding:
        parts.append(T("Odlučilo: ") + ", ".join("%s (%s)" % (r["phrase"], r["reliability_label"]) for r in deciding))
    else:
        parts.append(T("Odlučilo: nijedan podatak o parceli"))
    if missing:
        parts.append(T("nedostaje: ") + ", ".join(missing))
    return {"deciding": deciding, "missing": missing, "text": "; ".join(parts) + "."}


def template_answer(ctx: Context, d: Decision, corpus: Corpus) -> Dict[str, Any]:
    """Deterministic answer. Used as is without a language model, and as the fact sheet for one."""
    act = d.policy.act.value if d.policy.act else None
    used = data_used(ctx, d)
    core = _phrase(d.core_action)
    action, summary, referral, extra = None, "", None, []
    generic = L().GENERIC_ADVICE.get(d.advice_type.value, "")

    if act == "recommend":
        if core:
            action = {"what": core[0], "when_or_condition": core[1], "quantity": _quantity(d)}
            summary = core[0]
            app_time = next((t for t in d.tools if t.tool == "application_time" and t.output), None)
            if action["quantity"] and app_time:      # capacity is stated only next to a quantity that is shown
                extra.append(T("Sistem jednu normu daje za oko %s dana.") % L().num(app_time.output["days_per_application"]))
        else:
            summary = generic
        if d.advice_type == AdviceType.SCOUTING and (d.core_action or "").startswith("priority"):
            extra.append(T("Na terenu proverite: ") + ", ".join(L().SCOUTING_CHECKLIST) + ".")
        if d.advice_type == AdviceType.FERTILIZATION_PLAN and "|dose:" in (d.core_action or ""):
            band = d.core_action.split("|dose:")[1]
            if band in L().DOSE_BAND:
                extra.append(T("Orijentaciono: ") + L().DOSE_BAND[band] + ".")
    elif act == "conditional":
        code = d.policy.reason_code
        if code == "conditional_with_question":
            summary = T("Odluka zavisi od jednog podatka koji nedostaje: %s.") % L().INPUTS[d.question.input].lower()
            extra = _plan_by_answer(ctx, d)
        elif code.startswith("degraded_to_"):
            degraded = _phrase(decide_action_core(d.sufficiency.degraded_to, values(ctx)))
            if degraded:
                action = {"what": degraded[0], "when_or_condition": degraded[1], "quantity": None}
            summary = (degraded[0] + " " if degraded else "") + T("Količinu ili dozu nije moguće odrediti; nedostaje: %s.") % _missing_text(d)
        else:
            if core:
                action = {"what": core[0], "when_or_condition": core[1], "quantity": None}
            summary = (core[0] + " " if core else generic + " ") + T("Nije poznato: %s.") % _missing_text(d)
            if code == "decision_insensitive":
                extra.append(T("Podatak koji nedostaje ne menja ovu odluku, pa ga ne tražimo."))
            if code == "source_conflict":
                summary = (core[0] + " " if core else generic + " ") + \
                    T("Primenljivi izvori se ne slažu u ovoj odluci; oba stava su navedena, a odluku proverite sa savetodavcem.")
                for c in d.conflicts:
                    if c.resolution == "degrade":
                        for value, ids in sorted(c.values.items()):
                            extra.append(T("Izvori %s preporučuju: %s.") % (", ".join(ids), value))
            if code == "unreliable_inputs_stated":
                summary = (core[0] + " " if core else generic + " ") + \
                    T("Savet se oslanja na podatke niske pouzdanosti: %s; proverite ih pre odluke.") % _missing_text(d)
    elif act == "ask":
        summary = T("Pre preporuke potreban je jedan podatak: %s.") % L().INPUTS[d.question.input].lower()
        if not d.policy.allow_quantity and config.load("requirements")["advice_types"][d.advice_type.value].get("quantity"):
            extra.append(T("Količina ili doza se ne navodi dok ovaj podatak nije poznat."))
    elif act == "abstain":
        summary = L().ABSTAIN_REASONS.get(d.policy.reason_code) or \
            T("Nema dovoljno pouzdanih podataka za preporuku; nedostaje: %s.") % _missing_text(d)
        referral = L().REFERRAL if d.policy.reason_code in ("out_of_scope", "corpus_insufficient") else \
            T("Osvežite podatke o parceli kasnije ili se obratite savetodavnoj službi.")
        if d.advice_type == AdviceType.SCOUTING:
            extra.append(T("Do novog upotrebljivog snimka obilazite parcelu po uobičajenom rasporedu."))
    else:
        # Variants without a sufficiency layer leave the act to the text generator.
        act = "recommend"
        if core:
            action = {"what": core[0], "when_or_condition": core[1], "quantity": None}
            summary = core[0]
        else:
            summary = generic

    if referral is None and recent_referral_events(ctx):
        referral = L().PLANT_PROTECTION_REFERRAL
    return {"act": act, "act_label": L().ACTS[act], "summary": summary.strip(), "action": action,
            "rationale": rationale(ctx, d) + extra, "data_used": used, "sources": sources(d, corpus),
            "calculations": calculations(d), "next_question": next_question(d),
            "limitations": limitations(ctx, d, used), "referral": referral, "basis": basis(ctx, d),
            "generator": "template"}


# ------------------------------------------------------------------ language-model phrasing

SYSTEM_PROMPT = """You phrase agronomic advice for a maize grower in Bosnia and Herzegovina.
You receive a fact sheet in JSON produced by a rule-based advisory core: the chosen act, the action,
the parcel data with their reliability, the applicable source passages, and calculation results.

Write in Serbian, Latin script, ekavian, in plain language a farmer would use.

What you may and may not do:
- The act and the action are decided by the core. Do not change them, and do not add a different action.
  When the fact sheet's field "act_is_free" is true, no act was decided: choose one of recommend,
  conditional, ask, abstain yourself, based only on the fact sheet, and say what you would do.
- Use only facts from the fact sheet. State no number that does not appear in it. Do not compute.
- Never give an irrigation amount or a fertiliser dose unless the fact sheet's action.quantity holds one.
- Never name a cause for a vegetation difference seen in satellite data, and never name a plant
  protection product or dose.
- When a datum has low reliability or is missing, say so in one short clause where it matters.

Return a short summary (one or two sentences) and a rationale of two to four short sentences that
tie the advice to the parcel's own data and to the sources."""

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "act": {"type": "string", "enum": ["recommend", "conditional", "ask", "abstain"]},
        "summary": {"type": "string"},
        "rationale": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["act", "summary", "rationale"],
    "additionalProperties": False,
}
PROMPT_HASH = hashlib.sha256((SYSTEM_PROMPT + json.dumps(ANSWER_SCHEMA, sort_keys=True)).encode("utf-8")).hexdigest()
LANGUAGE_LINE = "Write in Serbian, Latin script, ekavian, in plain language a farmer would use."
LANGUAGE_LINE_EN = "Write in English, in plain language a farmer would use."


def system_prompt() -> str:
    """SYSTEM_PROMPT for the active locale (spec 017): English output for `en`; the local language (Latin script)
    otherwise, since Cyrillic is produced by deterministic transliteration after every check."""
    return SYSTEM_PROMPT.replace(LANGUAGE_LINE, LANGUAGE_LINE_EN) if current() == "en" else SYSTEM_PROMPT


def prompt_hash() -> str:
    if current() != "en":
        return PROMPT_HASH
    return hashlib.sha256((system_prompt() + json.dumps(ANSWER_SCHEMA, sort_keys=True)).encode("utf-8")).hexdigest()


class TemplateGenerator:
    name, model = "template", "none"

    def generate(self, ctx: Context, d: Decision, corpus: Corpus,
                 grounding_check: bool = True) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, int]]:
        return template_answer(ctx, d, corpus), {"unsupported_numbers": [], "action": "none"}, \
            {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0}


class AnthropicGenerator:
    """Phrases the answer with Claude. Requires the `anthropic` package and credentials in the environment."""
    name = "anthropic"

    def __init__(self, model: Optional[str] = None, judge=None):
        import anthropic                      # imported lazily so the package stays optional
        self._anthropic = anthropic
        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("LLM_MODEL", "claude-opus-5-5")
        # GROUNDING_JUDGE=llm plugs the Claude entailment judge into the support check (spec 004 T021)
        self.judge = judge if judge is not None else make_judge()

    @property
    def judge_prompt_hash(self) -> Optional[str]:
        judge = getattr(self, "judge", None)
        return getattr(judge, "prompt_hash", None) if judge is not None else None

    def generate(self, ctx: Context, d: Decision, corpus: Corpus,
                 grounding_check: bool = True) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, int]]:
        answer = template_answer(ctx, d, corpus)
        usage = {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0}
        grounding = {"unsupported_numbers": [], "action": "none"}
        facts = {"question": ctx.Q.text, "advice_type": L().ADVICE_TYPES[d.advice_type.value],
                 "act": answer["act"], "act_is_free": d.policy.act is None, "action": answer["action"],
                 "facts": answer["rationale"], "data": answer["data_used"], "limitations": answer["limitations"],
                 "next_question": (answer["next_question"] or {}).get("text"),
                 "sources": [{"title": s["title"], "applicability": s["applicability_label"],
                              "conditions": s["conditions"], "text": s["excerpt"]} for s in answer["sources"]],
                 "calculations": [c for c in answer["calculations"] if c["output"]]}
        out, usage, failure = self._request(facts)
        if failure:
            grounding["action"] = failure
            return answer, grounding, usage

        if not grounding_check:                     # variants below the gamma layer get the model's text as is
            answer.update(summary=out["summary"], rationale=out["rationale"], generator="anthropic")
            if d.policy.act is None:
                answer.update(act=out["act"], act_label=L().ACTS[out["act"]])
            grounding["action"] = "not_checked"
            return answer, grounding, usage
        bad = unsupported_numbers(out["summary"] + " " + " ".join(out["rationale"]), d.tools,
                                  [values(ctx), facts["facts"], facts["data"], facts["action"], facts["sources"]])
        if bad:
            grounding = {"unsupported_numbers": bad, "action": "replaced_by_template"}
            return answer, grounding, usage
        # Support part of gamma: sentences no applicable passage or fact supports are dropped;
        # an unsupported summary falls back to the template summary.
        support_texts = [s["excerpt"] for s in answer["sources"]] + answer["rationale"] + \
            [r["label"] + " " + r["value_text"] for r in answer["data_used"]] + answer["limitations"] + \
            [answer["summary"]] + ([answer["action"]["what"] + " " + (answer["action"]["when_or_condition"] or "")]
                                   if answer["action"] else [])
        judge = getattr(self, "judge", None)
        before = dict(judge.usage) if judge is not None and hasattr(judge, "usage") else None
        summary_check = support_check(split_sentences(out["summary"]), support_texts, judge=judge)
        kept, dropped = [], []
        for sentence in out["rationale"]:
            verdicts = support_check(split_sentences(sentence), support_texts, judge=judge)
            (kept if all(v["supported"] for v in verdicts) else dropped).append(sentence)
        grounding = {"unsupported_numbers": [], "unsupported_sentences": dropped +
                     [v["sentence"] for v in summary_check if not v["supported"]],
                     "checked_sentences": len(out["rationale"]) + len(summary_check),   # denominator of the support rate
                     "action": "checked", "judge": "llm" if judge is not None else "lexical"}
        if before is not None:               # judge calls are part of the answer's cost
            for k in usage:
                usage[k] += judge.usage.get(k, 0) - before.get(k, 0)
        if all(v["supported"] for v in summary_check):
            answer["summary"] = out["summary"]
        else:
            grounding["action"] = "summary_replaced_by_template"
        answer.update(rationale=kept or answer["rationale"], generator="anthropic")
        if d.policy.act is None:
            answer.update(act=out["act"], act_label=L().ACTS[out["act"]])
        return answer, grounding, usage


class _AnthropicRequest:
    """The Anthropic SDK call used by AnthropicGenerator."""

    def _request(self, facts: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Dict[str, int], Optional[str]]:
        usage = {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0}
        try:
            # Structured output keeps the reply parseable; a server-side fallback re-runs the request
            # on another model if a safety classifier declines it.
            response = self.client.beta.messages.create(
                model=self.model, max_tokens=16000, system=system_prompt(),
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": ANSWER_SCHEMA}},
                messages=[{"role": "user", "content": json.dumps(facts, ensure_ascii=False)}],
            )
        except self._anthropic.APIError as exc:
            return None, usage, "template_after_error:" + exc.__class__.__name__
        usage = {"llm_calls": 1, "input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
        if response.stop_reason != "end_turn":      # refusal, max_tokens: keep the deterministic text
            return None, usage, "template_after_" + str(response.stop_reason)
        try:
            text = next(b.text for b in response.content if b.type == "text")
            return json.loads(text), usage, None
        except (StopIteration, ValueError):
            return None, usage, "template_after_unparseable_output"


class ProviderGenerator(AnthropicGenerator):
    """The same phrasing step through any provider of smartagri.llm (Claude CLI, bridge, OpenAI-compatible...).

    Used so that the ladder V0-V5 and the VC baseline can run on the same model.
    """

    def __init__(self, provider, judge=None):
        self.provider = provider
        self.name = provider.name
        self.model = provider.model
        self.judge = judge

    def _request(self, facts):
        from ..llm import LLMError, parse_json_object
        usage = {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0}
        try:
            r = self.provider.complete(system_prompt(), [{"role": "user", "content": json.dumps(facts, ensure_ascii=False)}],
                                       json_schema=ANSWER_SCHEMA, max_tokens=4000)
        except LLMError as exc:
            return None, usage, "template_after_error:" + str(exc)[:80]
        usage = {"llm_calls": 1, "input_tokens": r.input_tokens, "output_tokens": r.output_tokens}
        try:
            out = r.data if r.data is not None else parse_json_object(r.text)
        except LLMError:
            return None, usage, "template_after_unparseable_output"
        if not {"act", "summary", "rationale"} <= set(out):
            return None, usage, "template_after_unparseable_output"
        return out, usage, None


AnthropicGenerator._request = _AnthropicRequest._request


def make_generator():
    """Generator for structured advice.

    LLM_PROVIDER=anthropic uses the Anthropic SDK path (with the optional LLM judge); any other configured
    provider (claude-cli, bridge, openai, deepseek, kimi, mistral, ollama, lmstudio, openai-compatible)
    goes through the provider layer; `template` or a misconfigured provider gives the deterministic template.
    """
    # ADVICE_GENERATOR=template keeps the structured advice deterministic and fast even when a model is
    # configured for the free AI chat; ADVICE_GENERATOR=llm (or unset with LLM_PROVIDER=anthropic, for
    # backward compatibility) phrases it with the configured model.
    mode = os.environ.get("ADVICE_GENERATOR", "")
    name = os.environ.get("LLM_PROVIDER", "template")
    if mode == "template" or (mode != "llm" and name != "anthropic"):
        return TemplateGenerator()
    if name == "anthropic":
        try:
            return AnthropicGenerator()
        except Exception:                     # missing package or credentials: stay usable offline
            return TemplateGenerator()
    try:
        from ..llm import make_provider
        provider = make_provider(name)
    except Exception:
        return TemplateGenerator()
    return ProviderGenerator(provider) if provider is not None else TemplateGenerator()
