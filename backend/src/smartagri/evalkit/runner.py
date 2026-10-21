"""Run scenarios under a variant, simulating the user's replies from the scenario file."""
from __future__ import annotations

import dataclasses
from typing import Any, Dict, List

from .. import labels
from ..config import load_variants
from ..core.quality import values
from ..core.types import Agronomic, Context
from ..pipeline import intent
from ..pipeline.generate import make_generator
from ..pipeline.profile import quality_rows
from ..pipeline.run import advise
from ..retrieval import load_corpus, make_retriever
from ..store import Store, new_id, now_iso
from .scenarios import load_scenarios, scenario_dir  # noqa: F401  (re-exported)
from .sources import retrieval_record

MAX_TURNS = 3


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


def run_scenario(sc: Dict[str, Any], variant_name: str, corpus, retriever, generator) -> Dict[str, Any]:
    """Play one scenario. A question the scenario has no reply for is answered with 'I do not know'."""
    variant = load_variants()[variant_name]
    ctx = Context.from_dict(sc["context"])
    view = scenario_view(sc, ctx)
    replies = sc.get("user_replies") or {}
    today = ctx.as_of.date().isoformat()
    turns, records = [], []
    for _ in range(MAX_TURNS):
        out = advise(ctx, corpus, retriever, variant, generator)
        turn = {"question": ctx.Q.text if not turns else turns[-1]["user_reply"], "answer": out["answer"], "user_reply": None}
        records.append({"decisions": out["decisions"], "provenance": out["provenance"], "cost": out["cost"]})
        turns.append(turn)
        nq = out["answer"]["next_question"]
        if not nq:
            break
        name = nq["input"]
        if name in replies:
            kind, value = intent.parse_reply(name, str(replies[name]))
            if kind != "value":
                kind, value = "value", replies[name]            # the scenario gave a structured value
            turn["user_reply"] = str(replies[name])
            ctx.A = Agronomic(**intent.apply_reply(dataclasses.asdict(ctx.A), name, value, today))
            ctx.questions_asked += 1
        else:
            turn["user_reply"] = "Ne znam."
            ctx.declined_inputs.append(name)
    first = turns[0]["answer"]
    return {"scenario": view, "turns": turns, "records": records, "stratum": sc.get("stratum"), "cluster": cluster_of(sc),
            "expect": (sc.get("expect") or {}).get(variant_name), "reference": sc.get("reference"), "first_act": first["act"],
            "final_act": turns[-1]["answer"]["act"], "n_turns": len(turns),
            "first_question_input": (first["next_question"] or {}).get("input"),
            "first_sufficiency": (records[0]["decisions"].get("sufficiency") or {}).get("status"),
            "retrieval": retrieval_record(sc, [(p.id, p.document_id) for p in corpus.passages],
                                          records[0]["decisions"].get("passage_budget") or [])}


def run_batch(store: Store, set_name: str, variant_name: str, repeats: int = 1, folder=None) -> Dict[str, Any]:
    """Run every scenario of a set (or of `folder`). Protected sets are refused by the CLI before this is called.
    External baselines (VC) run through their own runner in evalkit.vc, never through core.decide."""
    from . import vc
    if variant_name in vc.EXTERNAL_VARIANTS:
        return vc.run_batch(store, set_name, variant_name, repeats, folder)
    corpus = load_corpus()
    retriever, generator = make_retriever(corpus, store), make_generator()
    batch_id = new_id()
    items = []
    for sc in load_scenarios(set_name, folder):
        for repeat in range(1, repeats + 1):
            result = run_scenario(sc, variant_name, corpus, retriever, generator)
            item = dict(result, id=new_id(), batch_id=batch_id, scenario_id=sc["id"], variant=variant_name,
                        repeat=repeat, set=set_name, created_at=now_iso(), generator=generator.name)
            items.append(store.save_eval_item(item))
    return {"batch_id": batch_id, "variant": variant_name, "set": set_name, "n": len(items), "generator": generator.name}
