"""Core-path service of the research API (spec 057). Maize only, default locale, no product layers."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .. import config, geo, labels
from ..config import load_variants
from ..core.types import AdviceType, Question
from ..i18n import T
from ..evalkit import rating
from ..pipeline import intent
from ..pipeline.generate import make_generator
from ..pipeline.profile import AGRONOMIC_FIELDS, build_profile, context_from
from ..pipeline.run import advise
from ..providers import satellite
from ..providers.base import offline
from ..retrieval import load_corpus, make_retriever
from ..store import Store, make_store, new_id, now_iso

DEFAULT_VARIANT = "V5"
PROFILE_MAX_AGE_HOURS = 6


class NotFound(Exception):
    pass


class BadRequest(Exception):
    pass


class Unavailable(Exception):
    pass


class ResearchService:
    def __init__(self, store: Optional[Store] = None):
        self.store = store or make_store()
        self.corpus = load_corpus()
        self.retriever = make_retriever(self.corpus, self.store)
        self.variants = load_variants()
        self.generator = make_generator()

    # ------------------------------------------------------------ metadata
    def health(self) -> Dict[str, Any]:
        from .. import __version__
        return {"status": "ok", "version": __version__, "llm": self.generator.name,
                "satellite": "cdse" if satellite.configured() else "disabled", "offline": offline(),
                "database": self.store.backend, "retrieval": self.retriever.mode}

    def meta(self) -> Dict[str, Any]:
        inputs = {k: {"label": labels.INPUTS[k], "options": labels.OPTIONS.get(k, [])} for k in labels.INPUTS}
        return {"variants": sorted(self.variants), "default_variant": DEFAULT_VARIANT,
                "advice_types": [{"value": k, "label": labels.ADVICE_TYPES[k]} for k in labels.USER_ADVICE_TYPES],
                "inputs": inputs, "config_hashes": config.config_hashes(), "corpus_hash": self.corpus.hash}

    # ------------------------------------------------------------ parcels
    @staticmethod
    def _today() -> str:
        return datetime.now().astimezone().date().isoformat()

    def _parcel(self, parcel_id: str) -> Dict[str, Any]:
        parcel = self.store.get_parcel(parcel_id)
        if not parcel:
            raise NotFound("Parcela nije pronađena.")
        return parcel

    def create_parcel(self, body: Dict[str, Any]) -> Dict[str, Any]:
        try:
            g = geo.validate(body.get("geometry"))
        except geo.GeometryError as exc:
            raise BadRequest(str(exc))
        if not (body.get("name") or "").strip():
            raise BadRequest("Naziv parcele je obavezan.")
        agronomic = {"crop": "maize", "irrigation_available": body.get("irrigation_available") or "unknown"}
        for key in ("sowing_date", "irrigation_system_type", "soil_texture"):
            if body.get(key):
                agronomic[key] = body[key]
        if body.get("bbch") is not None:
            agronomic.update(bbch=int(body["bbch"]), bbch_origin="user_reported", bbch_reported_on=self._today())
        lat, lon = g["centroid"]["lat"], g["centroid"]["lon"]
        parcel = {"id": new_id(), "created_at": now_iso(), "name": body["name"].strip(), "geometry": body["geometry"],
                  "area_ha": g["area_ha"], "centroid": g["centroid"], "warnings": g["warnings"],
                  "notes": body.get("notes") or "", "agronomic": agronomic, "region_class": geo.region_class(lat, lon)}
        if body.get("pinned_as_of"):
            parcel["pinned_as_of"] = datetime.fromisoformat(body["pinned_as_of"]).isoformat()
        return self.store.save_parcel(parcel)

    def list_parcels(self) -> List[Dict[str, Any]]:
        return self.store.list_parcels()

    def get_parcel(self, parcel_id: str) -> Dict[str, Any]:
        return self._parcel(parcel_id)

    # ------------------------------------------------------------ profile
    @staticmethod
    def _pinned(parcel: Dict[str, Any]) -> Optional[datetime]:
        value = parcel.get("pinned_as_of")
        return datetime.fromisoformat(value) if value else None

    def refresh_profile(self, parcel_id: str) -> Dict[str, Any]:
        parcel = self._parcel(parcel_id)
        return build_profile(self.store, parcel, as_of=self._pinned(parcel), refresh=True)

    def get_profile(self, parcel_id: str) -> Dict[str, Any]:
        self._parcel(parcel_id)
        profile = self.store.latest_profile(parcel_id)
        if not profile:
            raise NotFound("Podaci o parceli još nisu pribavljeni.")
        return profile

    def _profile_for_chat(self, parcel: Dict[str, Any]) -> Dict[str, Any]:
        profile = self.store.latest_profile(parcel["id"])
        pinned = self._pinned(parcel)
        if pinned is not None:
            if profile and datetime.fromisoformat(profile["as_of"]) == pinned:
                return profile
            return build_profile(self.store, parcel, as_of=pinned, refresh=False)
        if profile:
            age = datetime.now().astimezone() - datetime.fromisoformat(profile["as_of"])
            if age < timedelta(hours=PROFILE_MAX_AGE_HOURS) or offline():
                return profile
        return build_profile(self.store, parcel, refresh=False)

    # ------------------------------------------------------------ conversation
    def _record(self, conv: Dict[str, Any], shown: str, out: Dict[str, Any], profile_id: Optional[str]) -> Dict[str, Any]:
        out["provenance"]["profile_id"] = profile_id
        run = dict(out, id=new_id(), conversation_id=conv["id"], turn=len(self.store.list_runs(conv["id"])) + 1,
                   variant=conv["variant"], created_at=now_iso(), question=shown)
        return self.store.save_run(run)

    def _ask_advice_type(self, conv: Dict[str, Any], text: str) -> Dict[str, Any]:
        """The question names no advice type: ask for it (same turn shape as the product API)."""
        question = {"input": "advice_type", "text": T("Na šta se pitanje odnosi?"), "how_to_obtain": "",
                    "options": labels.OPTIONS["advice_type"]}
        answer = {"act": "ask", "act_label": labels.ACTS["ask"],
                  "summary": T("Nisam siguran na koju vrstu saveta se pitanje odnosi."), "action": None, "rationale": [],
                  "data_used": [], "sources": [], "calculations": [], "next_question": question, "limitations": [],
                  "referral": None, "basis": {"deciding": [], "missing": [], "text": ""}, "generator": "template"}
        out = {"advice_type": None, "advice_type_label": None, "answer": answer,
               "decisions": {"quality": {}, "applicability": [], "passage_budget": [], "sufficiency": None,
                             "question": None, "core_action": None,
                             "policy": {"act": "ask", "reason_code": "advice_type_unclear", "allow_quantity": False,
                                        "warnings": []},
                             "grounding": {"unsupported_numbers": [], "action": "none"}},
               "provenance": {"as_of": None, "config_hashes": config.config_hashes(), "corpus_hash": self.corpus.hash,
                              "model": "none", "prompt_hash": None, "judge_prompt_hash": None, "scene_dates": [],
                              "forecast_issued_at": None},
               "cost": {"seconds": 0.0, "llm_calls": 0, "input_tokens": 0, "output_tokens": 0}}
        conv["pending"] = {"input": "advice_type", "question_text": text, "advice_type": None}
        self.store.save_conversation(conv)
        return self._record(conv, text, out, None)

    def chat(self, parcel_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """One turn: a new question (advice type given or classified) or a reply to the pending follow-up question."""
        parcel = self._parcel(parcel_id)
        text = (body.get("text") or "").strip()
        reply = body.get("reply")
        variant_name = body.get("variant") or DEFAULT_VARIANT
        if variant_name not in self.variants:
            raise BadRequest("Nepoznata varijanta: %s." % variant_name)
        conv = self.store.get_conversation(body["conversation_id"]) if body.get("conversation_id") else None
        if body.get("conversation_id") and (not conv or conv["parcel_id"] != parcel_id):
            raise NotFound("Razgovor nije pronađen.")
        if not conv:
            conv = {"id": new_id(), "parcel_id": parcel_id, "created_at": now_iso(), "variant": variant_name,
                    "pending": None, "questions_asked": 0, "declined": [], "first_question": text}
        conv["variant"] = variant_name
        pending = conv.get("pending")
        if pending and not reply and text and pending["input"] != "advice_type":
            kind, value = intent.parse_reply(pending["input"], text)
            if kind == "value":
                reply = {"input": pending["input"], "value": value}
            elif kind == "declined":
                reply = {"input": pending["input"], "value": labels.DECLINE_OPTION["value"]}
        if reply:
            if not pending or reply.get("input") != pending["input"]:
                raise BadRequest("Nema otvorenog pitanja na koje se ovaj odgovor odnosi.")
            name, value = reply["input"], reply.get("value")
            question_text, advice_type = pending["question_text"], pending["advice_type"]
            shown = text or str(value)
            if name == "advice_type":
                if value not in labels.ADVICE_TYPES:
                    raise BadRequest("Nepoznata vrsta saveta.")
                advice_type = value
            elif value == labels.DECLINE_OPTION["value"]:
                conv["declined"] = sorted(set(conv.get("declined", []) + [name]))
            else:
                parcel["agronomic"] = {k: v for k, v in intent.apply_reply(parcel["agronomic"], name, value,
                                                                           self._today()).items() if k in AGRONOMIC_FIELDS}
                self.store.save_parcel(parcel)
                conv["questions_asked"] = conv.get("questions_asked", 0) + 1
        else:
            if not text:
                raise BadRequest("Pitanje je prazno.")
            conv.update(questions_asked=0, declined=[], pending=None)
            question_text, shown = text, text
            advice_type = body.get("advice_type")
            if advice_type and advice_type not in labels.ADVICE_TYPES:
                raise BadRequest("Nepoznata vrsta saveta.")
            if not advice_type:
                classified = intent.classify(text)
                if classified is None:
                    return self._ask_advice_type(conv, text)
                advice_type = classified.value
        profile = self._profile_for_chat(parcel)
        ctx = context_from(parcel, profile, Question(question_text, AdviceType(advice_type)),
                           conv.get("questions_asked", 0), conv.get("declined", []))
        out = advise(ctx, self.corpus, self.retriever, self.variants[variant_name], self.generator)
        nq = out["answer"]["next_question"]
        conv["pending"] = {"input": nq["input"], "question_text": question_text, "advice_type": advice_type} if nq else None
        self.store.save_conversation(conv)
        return self._record(conv, shown, out, profile["id"])

    def ai_chat(self, parcel_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Free AI conversation, local language only: mode "baseline" is the VC variant of the experiment (the model
        does not see the decision model), mode "app" sees the decision model run under the default variant."""
        from ..llm import LLMError, make_provider
        from ..pipeline import ai_chat as ai
        parcel = self._parcel(parcel_id)
        message = (body.get("message") or "").strip()
        if not message:
            raise BadRequest("Poruka je prazna.")
        if len(message) > 2000:
            raise BadRequest("Poruka je predugačka (najviše 2000 znakova).")
        mode = body.get("mode") or "baseline"
        if mode not in ("baseline", "app"):
            raise BadRequest("Nepoznata varijanta: %s." % mode)
        try:
            provider = make_provider()
        except LLMError as exc:
            raise Unavailable("AI razgovor nije podešen: %s." % exc)
        if provider is None:
            raise Unavailable("AI razgovor nije podešen (LLM_PROVIDER).")
        conv = self.store.get_conversation(body["conversation_id"]) if body.get("conversation_id") else None
        if body.get("conversation_id") and (not conv or conv["parcel_id"] != parcel_id or conv.get("kind") != "ai"):
            raise NotFound("Razgovor nije pronađen.")
        if not conv:
            conv = {"id": new_id(), "parcel_id": parcel_id, "created_at": now_iso(), "kind": "ai", "variant": "ai",
                    "first_question": message}
            self.store.save_conversation(conv)
        turns = self.store.list_runs(conv["id"])
        history: List[Dict[str, str]] = []
        for t in turns:
            history += [{"role": "user", "content": t["question"]}, {"role": "assistant", "content": t["answer"]["text"]}]
        profile = self._profile_for_chat(parcel)
        ctx = context_from(parcel, profile, Question(message))
        try:
            out = ai.answer(provider, ctx, message, history, self.corpus, self.retriever, mode=mode,
                            variant=self.variants[DEFAULT_VARIANT] if mode == "app" else None)
        except LLMError as exc:
            raise Unavailable("AI model nije odgovorio: %s." % exc)
        cost = out.pop("_cost")
        provenance = {"system_view": out.pop("_system_view", None), "profile_id": profile["id"], "as_of": profile["as_of"],
                      "prompt_hash": out.pop("_prompt_hash"), "passages": out.pop("_passage_ids"),
                      "model_text": out.pop("_raw_text"), "corpus_hash": self.corpus.hash, "mode": mode}
        run = {"id": new_id(), "conversation_id": conv["id"], "turn": len(turns) + 1, "created_at": now_iso(),
               "question": message, "answer": out, "cost": cost, "provenance": provenance, "kind": "ai"}
        return self.store.save_run(run)

    def get_conversation(self, conversation_id: str) -> Dict[str, Any]:
        conv = self.store.get_conversation(conversation_id)
        if not conv:
            raise NotFound("Razgovor nije pronađen.")
        return dict(conv, runs=self.store.list_runs(conversation_id))

    def get_run(self, run_id: str) -> Dict[str, Any]:
        run = self.store.get_run(run_id)
        if not run:
            raise NotFound("Odgovor nije pronađen.")
        return run

    # ------------------------------------------------------------ LLM and evaluation
    def llm_info(self) -> Dict[str, Any]:
        from ..llm import describe
        return describe()

    def rubric(self) -> Any:
        return labels.RUBRIC

    def eval_runs(self, set_name: Optional[str] = None) -> List[Dict[str, Any]]:
        return rating.batches(self.store, set_name)

    def rating_next(self, rater: str) -> Dict[str, Any]:
        return rating.next_item(self.store, rater)

    def rating_save(self, body: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return rating.save(self.store, body)
        except KeyError:
            raise NotFound("Stavka za ocenjivanje nije pronađena.")
        except ValueError as exc:
            raise BadRequest(str(exc))
