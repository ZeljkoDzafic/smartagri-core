"""Manual-check sample of cited answer sentences.

Population: every sentence of the summary and rationale of an advice-giving turn (recommend or
conditional) that cites at least one source, plus every sentence the support check dropped (as
recorded in `decisions.grounding.unsupported_sentences`). A fixed-seed sample is exported for a
person to judge whether the cited passages support each sentence; the automatic verdict is kept so
the lexical check can be compared with the manual one. Rows carry the item id but not the variant
or generator, so the manual check is blind to the system variant.
"""
from __future__ import annotations

import random
from typing import Any, Dict, List

from ..core.grounding import split_sentences

ADVICE_ACTS = ("recommend", "conditional")


def population(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for item in sorted(items, key=lambda i: i["id"]):
        for t, (turn, rec) in enumerate(zip(item.get("turns", []), item.get("records", [])), start=1):
            a = turn["answer"]
            if a.get("act") not in ADVICE_ACTS or not a.get("sources"):
                continue
            g = (rec.get("decisions") or {}).get("grounding") or {}
            unsupported = set(g.get("unsupported_sentences") or [])
            srcs = [{"passage_id": s["passage_id"], "title": s.get("title"), "excerpt": s.get("excerpt")} for s in a["sources"]]
            sentences = [("summary", s) for s in split_sentences(a.get("summary") or "")]
            sentences += [("rationale", s) for r in a.get("rationale") or [] for s in split_sentences(r)]
            sentences += [("dropped", s) for s in sorted(unsupported)]
            for k, (kind, sentence) in enumerate(sentences):
                rows.append({"item_id": item["id"], "scenario_id": item.get("scenario_id"), "turn": t, "kind": kind,
                             "index": k, "sentence": sentence,
                             "automatic_supported": None if g.get("action") not in ("checked", "summary_replaced_by_template")
                             else sentence not in unsupported,
                             "sources": srcs, "manual_supported": None, "manual_note": ""})
    return rows


def sample(items: List[Dict[str, Any]], n: int, seed: int = 7) -> Dict[str, Any]:
    pop = population(items)
    chosen = sorted(random.Random(seed).sample(range(len(pop)), min(n, len(pop))))
    return {"seed": seed, "population": len(pop), "n": len(chosen), "rows": [pop[i] for i in chosen]}
