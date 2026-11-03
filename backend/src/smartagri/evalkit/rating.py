"""Blinded rating queue. A rater never sees the variant, and sees items in an order fixed per rater.

The queue never mixes scenario sets. Items reach a rater either through an assignment (`evalkit assign`: one set,
named batches, an explicit list of items in a seeded order, written to eval/assignments/<rater>.json and hashed), or,
without one, as every unrated item of one set (and of the named batches) in the same seeded order. The order of an
item is sha256(seed | rater | scenario | variant | repeat): it does not depend on the random item id, so the same
protocol over a new run gives the same order, and the seed is recorded with the assignment.

An assignment can also choose what is rated: one repetition per scenario (`repeat`: a fixed number, or `pick_repeat`: a
seeded choice per scenario, the same for every variant and every rater) and a balanced subset (`per_stratum`: n
scenarios per stratum, seeded and independent of the rater, so every rater gets the same scenarios in an order of
their own). The rule, the picked repetitions, the chosen scenarios and the lock the items come from are recorded in the
assignment file. The queue refuses to mix batches of one variant (a re-run would be rated twice) and items of
different protocol locks.
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
from . import lock as lock_mod

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
    from . import settings as st
    from .runner import raw_rows
    turns = []
    for t in item["turns"]:
        answer = blind_answer(t["answer"])
        turns.append({"question": t["question"], "answer": answer, "user_reply": t.get("user_reply")})
    scenario = dict(item["scenario"])
    if st.rater_view() == "raw" and scenario.get("quality"):
        scenario["quality"], scenario["rater_view"] = raw_rows(scenario["quality"]), "raw"     # also an item stored graded
    return {"item_id": item["id"], "scenario": scenario, "turns": turns}


DEFAULT_SEED = 7
ASSIGNMENT_FORMAT = "smartagri-rating-assignment/2"
FORMATS_READ = ("smartagri-rating-assignment/1", ASSIGNMENT_FORMAT)
ORDER_RULE = "sha256(seed|rater|scenario|variant|repeat), ties by item id"


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
    if data.get("format") not in FORMATS_READ or data.get("rater") != rater:
        raise ValueError("Neispravna dodela stavki za ocenjivača %s (%s)." % (rater, path))
    return data


def eligible(store: Store, set_name: str, batches: Optional[Sequence[str]] = None,
             variants: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    """Rateable items of one set (and of the named batches and variants)."""
    return [i for i in store.list_eval_items() if i.get("set") == set_name and i.get("rateable", True)
            and not i.get("error") and (not batches or i.get("batch_id") in batches)
            and (not variants or i.get("variant") in variants)]


def check_pool(items: List[Dict[str, Any]]) -> Optional[str]:
    """The one lock of the items; ValueError when they mix locks, or hold one scenario, variant and repetition in
    several batches (a re-run of a variant): name the batches to rate."""
    lock = lock_mod.single_lock(items)
    seen: Dict[Any, set] = {}
    for i in items:
        seen.setdefault((i.get("scenario_id"), i.get("variant"), i.get("repeat")), set()).add(i.get("batch_id"))
    dup = sorted({b for bs in seen.values() if len(bs) > 1 for b in bs})
    if dup:
        raise ValueError("The items of several batches repeat the same scenario, variant and repetition (%s); name the "
                         "batches to rate." % ", ".join(dup))
    return lock


def _pick(seed: int, *parts: Any) -> int:
    return int(hashlib.sha256(("%s|" % seed + "|".join(str(p) for p in parts)).encode("utf-8")).hexdigest()[:12], 16)


def choose_repeats(items: List[Dict[str, Any]], repeat: Optional[int], pick_repeat: bool, seed: int):
    """Items of one repetition per scenario, and the rule recorded for the assignment."""
    if repeat is not None and pick_repeat:
        raise ValueError("Choose one repetition (repeat) or a seeded choice per scenario (pick_repeat), not both.")
    if repeat is not None:
        kept = [i for i in items if i.get("repeat") == repeat]
        if not kept:
            raise ValueError("No item has repetition %s." % repeat)
        return kept, {"mode": "fixed", "repeat": repeat}
    if pick_repeat:
        available: Dict[str, List[int]] = {}
        for i in items:
            available.setdefault(i["scenario_id"], [])
            if i.get("repeat") not in available[i["scenario_id"]]:
                available[i["scenario_id"]].append(i.get("repeat"))
        picked = {s: sorted(r)[_pick(seed, "repeat", s) % len(r)] for s, r in available.items()}
        return [i for i in items if i.get("repeat") == picked[i["scenario_id"]]], \
            {"mode": "seeded", "seed": seed, "picked": picked}
    return items, {"mode": "all"}


def choose_subset(items: List[Dict[str, Any]], per_stratum: Optional[int], seed: int):
    """Items of a balanced subset: `per_stratum` scenarios of each stratum, in a seeded order that does not depend on the
    rater. Only scenarios present in every variant of the pool are chosen (a paired design)."""
    if per_stratum is None:
        return items, None
    if per_stratum < 1:
        raise ValueError("per_stratum must be at least 1")
    variants = {i["variant"] for i in items}
    have: Dict[str, set] = {}
    stratum_of: Dict[str, str] = {}
    for i in items:
        have.setdefault(i["scenario_id"], set()).add(i["variant"])
        stratum_of[i["scenario_id"]] = str(i.get("stratum"))
    complete = sorted(s for s, v in have.items() if v == variants)
    by: Dict[str, List[str]] = {}
    for s in sorted(complete, key=lambda s: (_pick(seed, "subset", s), s)):
        by.setdefault(stratum_of[s], []).append(s)
    chosen = {k: v[:per_stratum] for k, v in sorted(by.items())}
    subset = {"per_stratum": per_stratum, "seed": seed, "scenarios": chosen,
              "short": {k: len(v) for k, v in sorted(chosen.items()) if len(v) < per_stratum},
              "incomplete": sorted(set(have) - set(complete))}
    keep = {s for v in chosen.values() for s in v}
    return [i for i in items if i["scenario_id"] in keep], subset


def assign(store: Store, rater: str, set_name: str, batches: Optional[Sequence[str]] = None,
           variants: Optional[Sequence[str]] = None, seed: int = DEFAULT_SEED, write: bool = True,
           repeat: Optional[int] = None, pick_repeat: bool = False,
           per_stratum: Optional[int] = None) -> Dict[str, Any]:
    """Assign items of one set to a rater in the seeded order; the list and its sha256 are written to
    eval/assignments/<rater>.json (hash it, or commit it, before rating starts). `repeat` / `pick_repeat` keep one
    repetition per scenario, `per_stratum` a balanced seeded subset; both rules are recorded."""
    if not rater.strip():
        raise ValueError("Ime ocenjivača je obavezno.")
    pool = eligible(store, set_name, batches, variants)
    lock = check_pool(pool)
    pool, repeat_rule = choose_repeats(pool, repeat, pick_repeat, seed)
    pool, subset = choose_subset(pool, per_stratum, seed)
    items = sorted(pool, key=lambda i: order_key(i, rater, seed))
    order = [i["id"] for i in items]
    data = {"format": ASSIGNMENT_FORMAT, "rater": rater, "set": set_name, "batches": sorted(batches or []),
            "variants": sorted(variants or []), "seed": seed, "order_rule": ORDER_RULE, "lock_sha256": lock,
            "repeat_rule": repeat_rule, "subset": subset,
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
    check_pool([i for i in store.list_eval_items() if i.get("set") == set_name and i.get("rateable", True)
                and not i.get("error") and (not batches or i.get("batch_id") in batches)])
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
