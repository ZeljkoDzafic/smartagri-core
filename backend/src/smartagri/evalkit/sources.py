"""Reference sources of a scenario and retrieval measures over the passage budget.

A reference entry names a source in one of three forms:
  "<passage_id>"              exactly that passage, or every passage of a document with that id;
  "<document_id>#<section>"   passages of that document whose id equals or starts with <section>;
  "<document_id>#"            every passage of that document.
Entries that match no passage of the corpus in use are reported as `unresolved` and left out of
Recall@k: a source the corpus does not contain is a corpus-coverage finding, not a retrieval miss.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

APPLICABLE_KEYS = ("applicable_sources",)
NOT_APPLICABLE_KEYS = ("not_applicable_sources", "not_applicable")   # dev `expect.not_applicable` is the same list


def _collect(blocks: Iterable[Dict[str, Any]], keys: Sequence[str]) -> List[str]:
    out: List[str] = []
    for block in blocks:
        for key in keys:
            for entry in block.get(key) or []:
                if str(entry) not in out:
                    out.append(str(entry))
    return out


def reference_sources(sc: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """(applicable, not_applicable) entries from the scenario top level, `reference` and `expect`."""
    blocks = [sc, sc.get("reference") or {}, sc.get("expect") or {}]
    return _collect(blocks, APPLICABLE_KEYS), _collect(blocks, NOT_APPLICABLE_KEYS)


def matches(entry: str, passage_id: str, document_id: str) -> bool:
    if "#" in entry:
        doc, section = entry.split("#", 1)
        return doc == document_id and (not section or passage_id == section or passage_id.startswith(section))
    return entry == passage_id or entry == document_id


def resolve(entries: Sequence[str], passages: Sequence[Tuple[str, str]]) -> Dict[str, List[str]]:
    """entry -> ids of corpus passages it names; passages are (passage_id, document_id) pairs."""
    return {e: [pid for pid, doc in passages if matches(e, pid, doc)] for e in entries}


def retrieval_record(sc: Dict[str, Any], passages: Sequence[Tuple[str, str]], budget: Sequence[str]) -> Optional[Dict[str, Any]]:
    """What the report needs to score retrieval for one item; None when the scenario names no sources."""
    applicable, not_applicable = reference_sources(sc)
    if not applicable and not not_applicable:
        return None
    app, na = resolve(applicable, passages), resolve(not_applicable, passages)
    return {"k": len(budget), "budget": list(budget),
            "applicable": {e: p for e, p in app.items() if p}, "not_applicable": {e: p for e, p in na.items() if p},
            "unresolved": sorted([e for e, p in app.items() if not p] + [e for e, p in na.items() if not p])}


def scores(rec: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """Recall@k over applicable entries; precision and not-applicable rate over the budget."""
    budget = set(rec["budget"])
    app, na = rec["applicable"], rec["not_applicable"]
    app_ids = {p for ps in app.values() for p in ps}
    na_ids = {p for ps in na.values() for p in ps}
    recall = None if not app else sum(1 for ps in app.values() if budget & set(ps)) / float(len(app))
    precision = None if not budget or not app else len(budget & app_ids) / float(len(budget))
    na_rate = None if not budget or not na else len(budget & na_ids) / float(len(budget))
    return {"recall_at_k": recall, "precision_applicable": precision, "not_applicable_rate": na_rate}
