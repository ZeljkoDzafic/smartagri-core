"""Retrieval baseline: Recall@k of labelled applicable sources and query latency.

    python -m smartagri.retrieval.bench [--set dev] [--repeats 20] [--json]

Measures the retrieval stage alone (Retriever.search, before pi and the passage budget), so the
number isolates the ranker. For every scenario with `applicable_sources`, the entries are resolved
against the corpus in use (evalkit.sources); entries naming no passage of this corpus are counted
as unresolved and left out, as in the evaluation report. Recall@k = share of resolved entries with
at least one passage in the top k. Latency is wall time of one search call, repeated per question
after one warm-up call; the retrieval mode (lexical or hybrid) comes from the environment as in the API.
The protected test set is refused.
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Sequence

from ..core.types import AdviceType
from ..evalkit.scenarios import PROTECTED_SETS, load_scenarios
from ..evalkit.sources import reference_sources, resolve
from . import load_corpus, make_retriever

KS = (6, 20)


def recall(ranked: Sequence[str], resolved: Dict[str, List[str]], k: int) -> Optional[float]:
    found = {e: ids for e, ids in resolved.items() if ids}
    if not found:
        return None
    top = set(ranked[:k])
    return sum(1 for ids in found.values() if top & set(ids)) / float(len(found))


def _pct(values: List[float], q: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


def bench(scenarios: List[Dict[str, Any]], store=None, repeats: int = 20) -> Dict[str, Any]:
    corpus = load_corpus()
    retriever = make_retriever(corpus, store)
    pairs = [(p.id, p.document_id) for p in corpus.passages]
    rows, timings = [], []
    for sc in scenarios:
        q = (sc.get("context") or {}).get("Q") or {}
        t = AdviceType(q.get("advice_type", "scouting"))
        if t == AdviceType.OUT_OF_SCOPE:
            continue
        retriever.search(q.get("text", ""), t)                       # warm-up (lazy model, caches)
        times = []
        for _ in range(repeats):
            start = time.perf_counter()
            hits = retriever.search(q.get("text", ""), t, k=max(KS))
            times.append((time.perf_counter() - start) * 1000.0)
        timings += times
        applicable, _ = reference_sources(sc)
        if not applicable:
            continue
        res = resolve(applicable, pairs)
        ranked = [p.id for p in hits]
        rows.append(OrderedDict([("id", sc["id"]), ("advice_type", t.value),
                                 ("resolved", sum(1 for ids in res.values() if ids)),
                                 ("unresolved", sum(1 for ids in res.values() if not ids))] +
                                [("recall_at_%d" % k, recall(ranked, res, k)) for k in KS]))
    per_type: Dict[str, Dict[str, Any]] = OrderedDict()
    for t in sorted({r["advice_type"] for r in rows}):
        mine = [r for r in rows if r["advice_type"] == t]
        per_type[t] = OrderedDict([("scenarios", len(mine))] + [
            ("recall_at_%d" % k, _mean([r["recall_at_%d" % k] for r in mine])) for k in KS])
    return {"corpus_hash": corpus.hash, "passages": len(corpus.passages), "mode": retriever.mode,
            "scenarios": rows, "per_advice_type": per_type,
            "overall": OrderedDict(("recall_at_%d" % k, _mean([r["recall_at_%d" % k] for r in rows])) for k in KS),
            "latency_ms": {"queries": len(timings), "median": round(statistics.median(timings), 2) if timings else None,
                           "p95": round(_pct(timings, 0.95), 2) if timings else None,
                           "max": round(max(timings), 2) if timings else None},
            "host": "%s %s, Python %s" % (platform.system(), platform.machine(), platform.python_version())}


def _mean(values: List[Optional[float]]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def render(rep: Dict[str, Any]) -> str:
    def f(v):
        return "-" if v is None else "%.2f" % v
    out = ["Retrieval baseline: corpus %s... (%d passages), mode %s, %s" % (rep["corpus_hash"][:12], rep["passages"],
                                                                         rep["mode"], rep["host"]), "",
           "%-12s %-22s %8s %10s %6s %6s" % ("scenario", "advice type", "resolved", "unresolved", "R@6", "R@20")]
    for r in rep["scenarios"]:
        out.append("%-12s %-22s %8d %10d %6s %6s" % (r["id"], r["advice_type"], r["resolved"], r["unresolved"],
                                                     f(r["recall_at_6"]), f(r["recall_at_20"])))
    out += ["", "%-22s %9s %6s %6s" % ("advice type", "scenarios", "R@6", "R@20")]
    for t, r in rep["per_advice_type"].items():
        out.append("%-22s %9d %6s %6s" % (t, r["scenarios"], f(r["recall_at_6"]), f(r["recall_at_20"])))
    out.append("%-22s %9d %6s %6s" % ("all (mean)", len(rep["scenarios"]), f(rep["overall"]["recall_at_6"]),
                                     f(rep["overall"]["recall_at_20"])))
    lat = rep["latency_ms"]
    out += ["", "Latency per query (ms): median %s, p95 %s, max %s over %d calls" % (lat["median"], lat["p95"], lat["max"],
                                                                                   lat["queries"])]
    return "\n".join(out)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m smartagri.retrieval.bench", description=__doc__.split("\n")[0])
    ap.add_argument("--set", default="dev")
    ap.add_argument("--repeats", type=int, default=20)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--db", action="store_true", help="use DATABASE_URL (pgvector when PostgreSQL)")
    args = ap.parse_args(argv)
    if args.set in PROTECTED_SETS:
        print("Refused: the %s set must not be used before the protocol is locked." % args.set, file=sys.stderr)
        return 2
    store = None
    if args.db:
        from ..store import make_store
        store = make_store()
    rep = bench(load_scenarios(args.set), store, args.repeats)
    print(json.dumps(rep, indent=1, ensure_ascii=False) if args.json else render(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
