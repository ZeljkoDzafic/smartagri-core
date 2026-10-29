"""Run scenarios under a variant, simulating the user's replies from the scenario file."""
from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Optional

from .. import labels
from ..config import load_variants
from ..core.quality import values
from ..core.types import Agronomic, Context
from ..pipeline import intent
from ..pipeline.generate import TEMPLATE_LABEL, make_generator
from ..pipeline.profile import quality_rows
from ..pipeline.run import advise
from ..retrieval import load_corpus, make_retriever
from ..store import Store, new_id, now_iso
from .scenarios import load_scenarios, scenario_dir  # noqa: F401  (re-exported)
from .sources import retrieval_record

MAX_TURNS = 3
# What the simulated user says to a question the scenario has no prepared reply for. The same for every variant and for
# VC: a question that cannot be answered ends neither a structured nor a free conversation, it is answered "I do not
# know" and the model (or the layers) continue without it. MAX_TURNS is the hard cap that ends a loop.
DECLINE_REPLY = "Ne znam."


def context_text(ctx: Context) -> List[str]:
    """Plain description of the scenario for the rater: what a person looking at the parcel would know."""
    a, v = ctx.A, values(ctx)
    lines = ["Kultura: kukuruz. Datum odluke: %s" % labels.fmt_date(ctx.as_of)]
    if a.sowing_date:
        lines.append("Setva: %s" % labels.fmt_date(a.sowing_date))
    if a.bbch is not None:
        lines.append("Faza razvoja prema korisniku: BBCH %s." % a.bbch)
    lines.append("Navodnjavanje: %s." % {"yes": "moguće", "no": "nije moguće", "unknown": "nije poznato"}[a.irrigation_available])
    if a.soil_texture:
        lines.append("Tekstura zemljišta: %s." % labels.TEXTURES.get(a.soil_texture, a.soil_texture))
    if a.soil_water_status:
        lines.append("Stanje vode u zemljištu prema korisniku: %s." % labels.VALUE_WORDS[a.soil_water_status])
    for name in ("precip_past_7d", "precip_forecast_3d", "precip_forecast_7d", "et0_past_7d"):
        if v.get(name) is not None:
            lines.append("%s: %s." % (labels.INPUTS[name], labels.value_text(name, v[name])))
    return lines


def scenario_view(sc: Dict[str, Any], ctx: Context) -> Dict[str, Any]:
    """What the rater sees of the scenario; the same for every variant."""
    return {"id": sc["id"], "question": ctx.Q.text, "advice_type_label": labels.ADVICE_TYPES[ctx.Q.advice_type.value],
            "context_text": context_text(ctx), "quality": quality_rows(ctx)}


def cluster_of(sc: Dict[str, Any]) -> str:
    # Scenarios that share a parcel are dependent; `cluster` groups them for the bootstrap.
    return sc.get("cluster") or (sc["context"].get("P") or {}).get("parcel_id") or sc["id"]


def baseline_record(turns: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Who chose the act of a variant whose act is not the core's (V0-V3), for the run record; None for the others.

    {"act_chosen_by": "model"|"template", "label": "template, not a baseline"|None}. A template answer is a fallback
    that always recommends: it is shown in reports and tables under this label and is never a result of the rung."""
    marked = [t["answer"] for t in turns if t["answer"].get("baseline_label") or t["answer"].get("act_origin")]
    if not marked:
        return None
    template = any(a.get("baseline_label") for a in marked)
    return {"act_chosen_by": "template" if template else "model", "label": TEMPLATE_LABEL if template else None}


def run_scenario(sc: Dict[str, Any], variant_name: str, corpus, retriever, generator) -> Dict[str, Any]:
    """Play one scenario. A question the scenario has no reply for is answered with 'I do not know' (DECLINE_REPLY).

    A structured question of the alpha layer (V4, V5) is declined by its input name (`ctx.declined_inputs`). A free
    question of the model (variants without the sufficiency layer, `next_question.input` is None) is mapped to a
    prepared reply by keywords exactly as for the LLM baseline VC (`evalkit.vc.match_reply`); when no reply matches it
    is declined too: its text goes into `ctx.declined_free`, the fact sheet tells the model the user did not know, and
    the conversation continues, as it does for V4 and V5 and for VC. The turn cap MAX_TURNS ends it."""
    from .vc import match_reply
    variant = load_variants()[variant_name]
    ctx = Context.from_dict(sc["context"])
    view = scenario_view(sc, ctx)
    replies = sc.get("user_replies") or {}
    today = ctx.as_of.date().isoformat()
    turns, records, matched = [], [], []
    used: set = set()
    for _ in range(MAX_TURNS):
        out = advise(ctx, corpus, retriever, variant, generator)
        turn = {"question": ctx.Q.text if not turns else turns[-1]["user_reply"], "answer": out["answer"], "user_reply": None}
        records.append({"decisions": out["decisions"], "provenance": out["provenance"], "cost": out["cost"]})
        turns.append(turn)
        nq = out["answer"]["next_question"]
        if not nq:
            matched.append(None)
            break
        name = nq.get("input")
        if name is None:                                        # a free question of the model
            name = match_reply(nq.get("text") or "", replies, used)
            matched.append(name)
            if name is None:
                turn["user_reply"] = DECLINE_REPLY
                ctx.declined_free.append((nq.get("text") or "").strip())
                continue
            used.add(name)
        else:
            matched.append(name)
        if name in replies:
            # The same parse_reply as the interactive services use (word boundaries, negation, targeted number patterns);
            # the evaluation does not wait for a confirmation: the scenario's reply is the user's final word.
            kind, value = intent.parse_reply(name, str(replies[name]))
            turn["user_reply"] = str(replies[name])
            if kind == "declined":
                ctx.declined_inputs.append(name)                # the scenario's reply says the user does not know
            else:
                if kind != "value":
                    value = replies[name]                       # the scenario gave a structured value (e.g. "loam", 65)
                ctx.A = Agronomic(**intent.apply_reply(dataclasses.asdict(ctx.A), name, value, today))
                ctx.questions_asked += 1
        else:
            turn["user_reply"] = DECLINE_REPLY
            ctx.declined_inputs.append(name)
    first = turns[0]["answer"]
    baseline = baseline_record(turns)
    extra = {"baseline": baseline} if baseline else {}      # only variants whose act the model chooses carry it
    return {**extra, "scenario": view, "turns": turns, "records": records, "stratum": sc.get("stratum"), "cluster": cluster_of(sc),
            "expect": (sc.get("expect") or {}).get(variant_name), "reference": sc.get("reference"), "first_act": first["act"],
            "final_act": turns[-1]["answer"]["act"], "n_turns": len(turns),
            "first_question_input": matched[0] if matched else None,
            "first_sufficiency": (records[0]["decisions"].get("sufficiency") or {}).get("status"),
            "retrieval": retrieval_record(sc, [(p.id, p.document_id) for p in corpus.passages],
                                          records[0]["decisions"].get("passage_budget") or [])}


def models_used(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Per item: every model that actually answered, with the provider's request ids (from each turn's provenance)."""
    calls = [r.get("provenance", {}).get("llm_call") for r in records]
    calls = [c for c in calls if c]
    return {"models_used": sorted({str(c.get("model")) for c in calls if c.get("model")}),
            "request_ids": [c.get("request_id") for c in calls if c.get("request_id")]}


def run_batch(store: Store, set_name: str, variant_name: str, repeats: int = 1, folder=None) -> Dict[str, Any]:
    """Run every scenario of a set (or of `folder`). Protected sets are refused by the CLI before this is called.
    External baselines (VC) run through their own runner in evalkit.vc, never through core.decide.

    The generator is strict (config/evaluation.yaml): a failed or substituted model call is stored as an error item
    (`error`, `rateable: False`) and counted in `failed`; the CLI then exits non-zero. Raises ModelCallError before
    any item is written when a requested model cannot be built at all."""
    from . import settings as st
    from . import vc
    if variant_name in vc.EXTERNAL_VARIANTS:
        return vc.run_batch(store, set_name, variant_name, repeats, folder)
    from ..llm.base import LLMError
    cfg = st.load()
    corpus = load_corpus()
    retriever, generator = make_retriever(corpus, store), make_generator(strict=True, settings=cfg)
    generation = st.summary(cfg, generator.name)
    batch_id = new_id()
    items, failed = [], 0
    for sc in load_scenarios(set_name, folder):
        for repeat in range(1, repeats + 1):
            base = dict(id=new_id(), batch_id=batch_id, scenario_id=sc["id"], variant=variant_name, repeat=repeat,
                        set=set_name, created_at=now_iso(), generator=generator.name, generation=generation)
            try:
                result = run_scenario(sc, variant_name, corpus, retriever, generator)
            except LLMError as exc:
                # Kept so the failure is visible in the report; never offered for rating, never replaced by a template.
                failed += 1
                store.save_eval_item(dict(base, error=str(exc)[:300], rateable=False, scenario={"id": sc["id"]},
                                          turns=[], records=[], n_turns=0, first_act=None, final_act=None,
                                          stratum=sc.get("stratum"), cluster=cluster_of(sc)))
                continue
            items.append(store.save_eval_item(dict(result, **base, **models_used(result["records"]))))
    summary = {"batch_id": batch_id, "variant": variant_name, "set": set_name, "n": len(items), "failed": failed,
               "generator": generator.name, "model": generation["model"]}
    if any((i.get("baseline") or {}).get("label") for i in items):
        summary["label"] = TEMPLATE_LABEL         # V0-V3 from the template: a fallback, not a baseline result
    return summary
