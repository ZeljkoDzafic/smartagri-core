"""Blinded rating queue. A rater never sees the variant, and sees items in an order fixed per rater."""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

from .. import labels
from ..store import Store, new_id, now_iso

CRITICAL_KEYS = {c["key"] for c in labels.RUBRIC["critical"]}


def batches(store: Store, set_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """Evaluation batches, newest first; only those of one scenario set when `set_name` is given."""
    out: Dict[str, Dict[str, Any]] = {}
    for item in store.list_eval_items():
        if set_name is not None and item.get("set") != set_name:
            continue
        b = out.setdefault(item["batch_id"], {"batch_id": item["batch_id"], "variant": item["variant"],
                                              "set": item.get("set"), "created_at": item["created_at"], "n": 0})
        b["n"] += 1
    return sorted(out.values(), key=lambda b: b["created_at"], reverse=True)


HIDDEN = ("generator", "provider", "model")
# A free-text answer (variant VC) is shown with exactly these fields; never the provider, model or
# grounding check, which would reveal how it was produced.
TEXT_FIELDS = ("format", "text", "citations", "data_used", "warnings", "referral")
CITATION_FIELDS = ("id", "title", "url", "applicability", "applicability_label")


def blind_answer(answer: Dict[str, Any]) -> Dict[str, Any]:
    if answer.get("format") == "text":
        out = {k: answer.get(k) for k in TEXT_FIELDS}
        out["citations"] = [{k: c.get(k) for k in CITATION_FIELDS} for c in answer.get("citations") or []]
        out["warnings"], out["data_used"] = list(out["warnings"] or []), list(out["data_used"] or [])
        return out
    return {k: v for k, v in answer.items() if k not in HIDDEN and not k.startswith("_")}


def _blind(item: Dict[str, Any]) -> Dict[str, Any]:
    turns = []
    for t in item["turns"]:
        answer = blind_answer(t["answer"])
        turns.append({"question": t["question"], "answer": answer, "user_reply": t.get("user_reply")})
    return {"item_id": item["id"], "scenario": item["scenario"], "turns": turns}


def next_item(store: Store, rater: str) -> Dict[str, Any]:
    done = {r["item_id"] for r in store.list_ratings(rater)}
    todo = [i for i in store.list_eval_items() if i["id"] not in done and i.get("rateable", True)]
    if not todo:
        return {"item_id": None, "remaining": 0}
    todo.sort(key=lambda i: hashlib.sha256((rater + i["id"]).encode("utf-8")).hexdigest())
    return dict(_blind(todo[0]), remaining=len(todo))


def save(store: Store, body: Dict[str, Any]) -> Dict[str, Any]:
    if store.get_eval_item(body["item_id"]) is None:
        raise KeyError(body["item_id"])
    unknown = set(body.get("critical", [])) - CRITICAL_KEYS
    if unknown:
        raise ValueError("Nepoznata klasa kritične greške: %s." % ", ".join(sorted(unknown)))
    if not body["rater"].strip():
        raise ValueError("Ime ocenjivača je obavezno.")
    rating = dict(body, id=new_id(), created_at=now_iso(), critical=sorted(set(body.get("critical", []))))
    store.save_rating(rating)
    return {"id": rating["id"]}
