"""Blinded rating queue. A rater never sees the variant, and sees items in an order fixed per rater.

The queue never mixes scenario sets. Items reach a rater either through an assignment (`evalkit assign`: one set,
named batches, an explicit list of items in a seeded order, written to eval/assignments/<rater>.json and hashed), or,
without one, as every unrated item of one set (and of the named batches) in the same seeded order. The order of an
item is sha256(seed | rater | scenario | variant | repeat): it does not depend on the random item id, so the same
protocol over a new run gives the same order, and the seed is recorded with the assignment.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

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


DEFAULT_SEED = 7
ASSIGNMENT_FORMAT = "smartagri-rating-assignment/1"


def order_key(item: Dict[str, Any], rater: str, seed: int = DEFAULT_SEED) -> str:
    """Seeded order of an item for one rater; independent of the random item id (the id only breaks exact ties)."""
    text = "%s|%s|%s|%s|%s" % (seed, rater, item.get("scenario_id"), item.get("variant"), item.get("repeat"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest() + "|" + str(item.get("id"))


def assignments_dir() -> Path:
    env = os.environ.get("SMARTAGRI_ASSIGNMENTS_DIR")
    return Path(env) if env else Path(__file__).resolve().parents[3] / "eval" / "assignments"


def _safe(rater: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in rater.strip()) or "rater"


def assignment_path(rater: str) -> Path:
    return assignments_dir() / ("%s.json" % _safe(rater))


def load_assignment(rater: str) -> Optional[Dict[str, Any]]:
    path = assignment_path(rater)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format") != ASSIGNMENT_FORMAT or data.get("rater") != rater:
        raise ValueError("Neispravna dodela stavki za ocenjivača %s (%s)." % (rater, path))
    return data


def eligible(store: Store, set_name: str, batches: Optional[Sequence[str]] = None,
             variants: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    """Rateable items of one set (and of the named batches and variants)."""
    return [i for i in store.list_eval_items() if i.get("set") == set_name and i.get("rateable", True)
            and not i.get("error") and (not batches or i.get("batch_id") in batches)
            and (not variants or i.get("variant") in variants)]


def assign(store: Store, rater: str, set_name: str, batches: Optional[Sequence[str]] = None,
           variants: Optional[Sequence[str]] = None, seed: int = DEFAULT_SEED, write: bool = True) -> Dict[str, Any]:
    """Assign items of one set to a rater in the seeded order; the list and its sha256 are written to
    eval/assignments/<rater>.json (hash it, or commit it, before rating starts)."""
    if not rater.strip():
        raise ValueError("Ime ocenjivača je obavezno.")
    items = sorted(eligible(store, set_name, batches, variants), key=lambda i: order_key(i, rater, seed))
    order = [i["id"] for i in items]
    data = {"format": ASSIGNMENT_FORMAT, "rater": rater, "set": set_name, "batches": sorted(batches or []),
            "variants": sorted(variants or []), "seed": seed,
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"), "items": order,
            "items_sha256": hashlib.sha256("\n".join(order).encode("utf-8")).hexdigest()}
    if write:
        path = assignment_path(rater)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        data["path"] = str(path)
    return data


def next_item(store: Store, rater: str, set_name: Optional[str] = None, batches: Optional[Sequence[str]] = None,
              seed: int = DEFAULT_SEED) -> Dict[str, Any]:
    """The rater's next unrated item. With an assignment file for the rater: its items in its order (set_name and
    batches, when given, must agree with it). Without one: unrated items of one set; ValueError when no set is named
    and unrated items of several sets exist (the queue never mixes sets)."""
    done = {r["item_id"] for r in store.list_ratings(rater)}
    a = load_assignment(rater)
    if a is not None:
        if set_name is not None and set_name != a["set"]:
            raise ValueError("Ocenjivač %s ima dodelu za skup %s, ne %s." % (rater, a["set"], set_name))
        by_id = {i["id"]: i for i in store.list_eval_items()}
        todo = [by_id[x] for x in a["items"] if x in by_id and x not in done]
        if not todo:
            return {"item_id": None, "remaining": 0}
        return dict(_blind(todo[0]), remaining=len(todo), set=a["set"])
    pool = [i for i in store.list_eval_items() if i["id"] not in done and i.get("rateable", True) and not i.get("error")
            and (not batches or i.get("batch_id") in batches)]
    if set_name is None:
        sets = sorted({str(i.get("set")) for i in pool})
        if len(sets) > 1:
            raise ValueError("Stavke pripadaju različitim skupovima (%s); izaberite skup." % ", ".join(sets))
        set_name = sets[0] if sets else None
    todo = [i for i in pool if i.get("set") == set_name]
    if not todo:
        return {"item_id": None, "remaining": 0}
    todo.sort(key=lambda i: order_key(i, rater, seed))
    return dict(_blind(todo[0]), remaining=len(todo), set=set_name)


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
