"""Variant VC, "LLM sa podacima i izvorima": the strong LLM baseline of comparison E5.

VC sees what V5 sees (the scenario's parcel data with reliability and age, and the passages the
applicability predicate does not reject) but has no explicit decision model: no q-gated
sufficiency, no alpha (question choice), no delta (policy). It is the free AI conversation
(pipeline.ai_chat.answer) played over a scenario; it is never run through core.decide, and
variants.yaml does not list it, so the core cannot branch on it.

The user is simulated from the scenario: when an answer ends with a question to the user and the
scenario has a reply (`user_replies`) for an input the question is about (matched by the input's
label and keywords), the reply text is sent as the next message, for at most MAX_TURNS answers.
A question with no such reply is answered "Ne znam." (the same wording and the same turn cap as every other variant,
evalkit.runner) and the conversation goes on; it stops when the model asks nothing more or at the cap.

Items have the shape the rating queue and the report expect, with `answer_format: "text"`; the
report branches on that field, never on the variant name."""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from .. import labels
from ..core.types import Context
from ..llm import LLMError, ModelCallError, Provider, make_provider
from ..pipeline import ai_chat
from ..retrieval import load_corpus, make_retriever
from ..retrieval.search import fold
from ..store import Store, new_id, now_iso
from .runner import DECLINE_REPLY, MAX_TURNS, cluster_of, scenario_view
from .scenarios import load_scenarios
from .sources import retrieval_record

EXTERNAL_VARIANTS = {"VC": "LLM sa podacima i izvorima"}
ANSWER_FORMAT = "text"
RETRIES = 1

# Folded (lowercase, no diacritics, đ -> dj) stems that show a question is about an input.
KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "soil_water_status": ("vlazn", "vlag", "suvo", "suvi", "stanje vode", "vode u zemljist", "mrvi", "asov"),
    "irrigation_available": ("mogucnost navodnjav", "mozete li da navodnjav", "mozete li navodnjav",
                             "imate li navodnjav", "imate navodnjav", "da li navodnjavate"),
    "irrigation_efficiency": ("kap po kap", "kisenj", "brazd", "tip sistema", "koji sistem", "efikasnost"),
    "irrigation_capacity": ("kapacitet sistema", "mm/dan", "mm dnevno"),
    "soil_awc": ("tip zemljist", "tekstur", "peskovit", "ilovac", "glinovit", "vodni kapacitet", "vrsta zemljist"),
    "soil_analysis": ("analiz",),
    "phenophase": ("faz", "bbch", "listov", "metlic", "svil", "razvoj"),
    "sowing_date": ("setv", "posejal", "sejali", "posejan"),
    "previous_fertilization": ("djubr", "dubr", "prihran", "azot", "kan ", "urea", "uree"),
    "yield_target": ("prinos",),
    "operation": ("koji rad", "kakav rad", "koju operacij", "prskanj", "medjuredn", "obrad", "planirate"),
    "previous_crop": ("predusev", "prethodn", "pre kukuruza"),
    "manure": ("stajnjak", "stajsk", "organsk"),
    "hybrid_fao": ("hibrid", "fao", "grupa zrenja"),
    "plant_density": ("sklop", "gustin", "biljaka po"),
    "field_observation": ("primetili", "zapaz", "simptom", "stetoc", "zutil", "venjenj"),
}


class Unavailable(Exception):
    """No language model is configured; VC cannot run."""


def provider_or_refuse(name: Optional[str] = None) -> Provider:
    """The evaluation provider for VC: model, effort and the absence of a server-side fallback come from
    config/evaluation.yaml (evalkit.settings); the environment must agree with it."""
    from . import settings as st
    cfg = st.load()
    problems = st.check(cfg, need_model=True)
    if problems:
        raise Unavailable("; ".join(problems))
    llm = cfg["llm"]
    try:
        p = make_provider(name, model=llm.get("model"), server_fallback=bool(llm.get("server_fallback", False)),
                          effort=llm.get("effort"))
    except LLMError as exc:
        raise Unavailable("VC needs a language model, but LLM_PROVIDER is misconfigured: %s" % exc)
    if p is None:
        raise Unavailable("VC needs a language model: set LLM_PROVIDER (claude-cli, anthropic, openai, deepseek, "
                          "kimi, mistral, ollama, lmstudio or openai-compatible); the template has no model")
    return p


class _Recording(Provider):
    """Delegates to the evaluation provider and remembers the request ids of its responses (provenance)."""

    def __init__(self, inner: Provider):
        self.inner, self.name, self.model = inner, inner.name, inner.model
        self.request_ids: List[Optional[str]] = []

    def complete(self, system, messages, json_schema=None, max_tokens=4000):
        r = self.inner.complete(system, messages, json_schema=json_schema, max_tokens=max_tokens)
        self.request_ids.append(getattr(r, "request_id", None))
        return r


def ends_with_question(answer: Dict[str, Any]) -> bool:
    return bool((answer.get("question_to_user") or "").strip()) or answer.get("text", "").rstrip().endswith("?")


def question_text(answer: Dict[str, Any]) -> str:
    q = (answer.get("question_to_user") or "").strip()
    if q:
        return q
    paras = [p for p in answer.get("text", "").split("\n") if p.strip()]
    return paras[-1] if paras else ""


def match_reply(question: str, replies: Dict[str, Any], used: Optional[set] = None) -> Optional[str]:
    """The input of `replies` the question is about: most keyword (or label) hits, at least one; ties go to
    the earlier reply in the scenario file. Inputs already answered are skipped."""
    q = fold(question)
    best, best_score = None, 0
    for name in replies:
        if used and name in used:
            continue
        stems = KEYWORDS.get(name, ()) + (fold(labels.INPUTS.get(name, "")),)
        score = sum(1 for s in stems if s and s in q)
        if score > best_score:
            best, best_score = name, score
    return best


def _answer_view(out: Dict[str, Any]) -> Dict[str, Any]:
    """The stored answer of one VC turn. Provider and model live in the record, not in the answer."""
    return {"format": ANSWER_FORMAT, "text": out["text"], "citations": out["citations"], "data_used": out["data_used"],
            "warnings": out["warnings"], "referral": out["referral"], "grounding": out["grounding"],
            "question_to_user": out.get("question_to_user") or ""}


def _call(provider: Provider, ctx: Context, message: str, history, corpus, retriever, query: str) -> Dict[str, Any]:
    for attempt in range(RETRIES + 1):
        try:
            out = ai_chat.answer(provider, ctx, message, history, corpus, retriever,
                                 advice_type=ctx.Q.advice_type, query=query)
        except LLMError:
            if attempt == RETRIES:
                raise
            continue
        if out.get("model") and provider.model and out["model"] != provider.model:
            # an answer from another model than the pinned one is never a VC answer
            raise ModelCallError("VC answered by model %s, not %s" % (out["model"], provider.model))
        return out
    raise AssertionError("unreachable")


def run_scenario(sc: Dict[str, Any], provider: Provider, corpus, retriever, variant_name: str = "VC") -> Dict[str, Any]:
    """Play one scenario as a free conversation with the model."""
    ctx = Context.from_dict(sc["context"])            # exactly as for the other variants
    view = scenario_view(sc, ctx)
    advice_type = ctx.Q.advice_type
    replies = sc.get("user_replies") or {}
    message, query = ctx.Q.text, ctx.Q.text
    history: List[Dict[str, str]] = []
    turns: List[Dict[str, Any]] = []
    records: List[Dict[str, Any]] = []
    matched: List[Optional[str]] = []
    used: set = set()
    recording = provider if isinstance(provider, _Recording) else _Recording(provider)
    for _ in range(MAX_TURNS):
        ctx.Q.advice_type = advice_type
        recording.request_ids = []
        out = _call(recording, ctx, message, history, corpus, retriever, query)
        answer = _answer_view(out)
        turn = {"question": message, "answer": answer, "user_reply": None}
        turns.append(turn)
        cost = dict(out["_cost"], llm_calls=1)
        records.append({"decisions": {"grounding": out["grounding"]}, "cost": cost,
                        "provenance": {"as_of": ctx.as_of.isoformat() if ctx.as_of else None, "corpus_hash": corpus.hash,
                                       "provider": out["provider"], "model": out["model"],
                                       "request_ids": [x for x in recording.request_ids if x],
                                       "prompt_hash": out["_prompt_hash"], "passages": out["_passage_ids"],
                                       "model_text": out["_raw_text"]}})
        if not ends_with_question(answer) or len(turns) == MAX_TURNS:
            matched.append(None)
            break
        name = match_reply(question_text(answer), replies, used)
        matched.append(name)
        if name is None:
            turn["user_reply"] = DECLINE_REPLY
            ctx.declined_free.append(question_text(answer))
        else:
            used.add(name)
            turn["user_reply"] = str(replies[name])
        history += [{"role": "user", "content": message}, {"role": "assistant", "content": answer["text"]}]
        message = turn["user_reply"]
        query = ctx.Q.text + " " + message
    first_budget = records[0]["provenance"]["passages"]
    return {"scenario": view, "turns": turns, "records": records, "stratum": sc.get("stratum"), "cluster": cluster_of(sc),
            "expect": (sc.get("expect") or {}).get(variant_name), "reference": sc.get("reference"),
            "answer_format": ANSWER_FORMAT, "first_act": None, "final_act": None, "n_turns": len(turns),
            "first_question_input": matched[0] if matched else None,
            "ends_with_question": [ends_with_question(t["answer"]) for t in turns],
            "first_sufficiency": None,
            "retrieval": retrieval_record(sc, [(p.id, p.document_id) for p in corpus.passages], first_budget)}


def run_batch(store: Store, set_name: str, variant_name: str = "VC", repeats: int = 1, folder=None,
              provider: Optional[Provider] = None) -> Dict[str, Any]:
    """Run every scenario of a set under VC. Raises Unavailable without a configured model."""
    provider = provider or provider_or_refuse()
    corpus = load_corpus()
    retriever = make_retriever(corpus, store)
    batch_id = new_id()
    n, failed, usd, started = 0, 0, 0.0, time.time()
    for sc in load_scenarios(set_name, folder):
        for repeat in range(1, repeats + 1):
            base = dict(id=new_id(), batch_id=batch_id, scenario_id=sc["id"], variant=variant_name, repeat=repeat,
                        set=set_name, created_at=now_iso(), generator=provider.name, model=provider.model,
                        prompt_hash=ai_chat.PROMPT_HASH)
            try:
                result = run_scenario(sc, provider, corpus, retriever, variant_name)
            except LLMError as exc:
                # Kept so the failure is visible in the report; never offered for rating.
                failed += 1
                store.save_eval_item(dict(base, answer_format=ANSWER_FORMAT, error=str(exc), rateable=False,
                                          scenario={"id": sc["id"]}, turns=[], records=[], n_turns=0,
                                          first_act=None, final_act=None, stratum=sc.get("stratum"),
                                          cluster=cluster_of(sc)))
                continue
            usd += sum(float(r["cost"].get("usd") or 0) for r in result["records"])
            base["models_used"] = sorted({str(r["provenance"]["model"]) for r in result["records"] if r["provenance"].get("model")})
            base["request_ids"] = [x for r in result["records"] for x in r["provenance"].get("request_ids") or []]
            if result["records"]:
                base["model"] = result["records"][0]["provenance"]["model"] or provider.model
            store.save_eval_item(dict(result, **base))
            n += 1
    return {"batch_id": batch_id, "variant": variant_name, "set": set_name, "n": n, "failed": failed,
            "generator": provider.name, "model": provider.model, "prompt_hash": ai_chat.PROMPT_HASH,
            "usd": round(usd, 4), "seconds": round(time.time() - started, 1)}
