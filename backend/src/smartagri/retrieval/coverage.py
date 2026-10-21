"""Corpus coverage check (spec 003 T020, SC-005).

    python -m smartagri.retrieval.coverage [--set dev] [--min 3] [--strict]

For every scenario of a development set, pi (parcel conditions, quality-aware) is applied to every
passage of the corpus (no retrieval, so the count measures the corpus, not the ranker). The report
lists per scenario the number of applicable and conditional passages for its advice type; per
advice type the minimum over its typical scenarios (stratum `complete`, or all of that type when it
has none) against the SC-005 target (>= --min applicable) and the minimum over all scenarios; the
passages still marked `verify: true`, and vocabulary violations. The protected test set is refused.
"""
from __future__ import annotations

import argparse
import sys
from collections import OrderedDict
from typing import Any, Dict, List, Optional

import yaml

from ..core.applicability import applicability
from ..core.quality import annotate_quality, values
from ..core.types import AdviceType, Applicability, Context
from ..evalkit.scenarios import PROTECTED_SETS, load_scenarios
from .corpus import Corpus, corpus_dir, load_corpus, validate_corpus

ADVICE_TYPES = [t.value for t in AdviceType if t != AdviceType.OUT_OF_SCOPE]


def scenario_counts(sc: Dict[str, Any], corpus: Corpus) -> Dict[str, Any]:
    ctx = Context.from_dict(sc["context"])
    q, vals = annotate_quality(ctx, True), values(ctx)
    counts = {s.value: 0 for s in Applicability}
    for p in corpus.passages:
        counts[applicability(p, ctx, q, vals, "parcel_conditions", True).status.value] += 1
    return {"id": sc["id"], "stratum": sc.get("stratum"), "advice_type": ctx.Q.advice_type.value,
            "applicable": counts["applicable"], "conditional": counts["conditional"],
            "not_applicable": counts["not_applicable"]}


def coverage(scenarios: List[Dict[str, Any]], corpus: Corpus, minimum: int = 3) -> Dict[str, Any]:
    rows = [scenario_counts(sc, corpus) for sc in scenarios
            if (sc.get("context") or {}).get("Q", {}).get("advice_type") in ADVICE_TYPES]
    per_type: Dict[str, Dict[str, Any]] = OrderedDict()
    for t in ADVICE_TYPES:
        mine = [r for r in rows if r["advice_type"] == t]
        # "typical" = scenarios with complete inputs; a type without one falls back to all its scenarios
        typical = [r for r in mine if r["stratum"] == "complete"] or mine
        low = min((r["applicable"] for r in typical), default=None)
        per_type[t] = {"scenarios": len(mine), "typical_basis": "complete" if typical is not mine else "all",
                       "typical_min_applicable": low,
                       "min_applicable": min((r["applicable"] for r in mine), default=None),
                       "max_applicable": max((r["applicable"] for r in mine), default=None),
                       "min_applicable_or_conditional": min((r["applicable"] + r["conditional"] for r in mine), default=None),
                       "meets_target": low is not None and low >= minimum}
    raw = yaml.safe_load((corpus_dir() / "passages.yaml").read_text(encoding="utf-8")) or []
    return {"corpus_hash": corpus.hash, "passages": len(corpus.passages), "documents": len(corpus.documents),
            "target_min_applicable": minimum, "scenarios": rows, "per_advice_type": per_type,
            "verify": [p["id"] for p in raw if p.get("verify")],
            "vocabulary_violations": validate_corpus(corpus.documents, raw)}


def render(rep: Dict[str, Any]) -> str:
    out = ["Corpus %s...: %d passages, %d documents; target >= %d applicable passages per advice type"
           % (rep["corpus_hash"][:12], rep["passages"], rep["documents"], rep["target_min_applicable"]), "",
           "%-22s %9s %-9s %8s %8s %8s %8s %s" % ("advice type", "scenarios", "typical", "typ app", "min app",
                                                  "max app", "min a+c", "target")]
    for t, r in rep["per_advice_type"].items():
        def fmt(v):
            return "-" if v is None else str(v)
        out.append("%-22s %9d %-9s %8s %8s %8s %8s %s" % (t, r["scenarios"], r["typical_basis"], fmt(r["typical_min_applicable"]),
                                                          fmt(r["min_applicable"]), fmt(r["max_applicable"]),
                                                fmt(r["min_applicable_or_conditional"]),
                                                "ok" if r["meets_target"] else ("no scenario" if not r["scenarios"] else "BELOW")))
    out += ["", "%-12s %-16s %-22s %5s %5s %5s" % ("scenario", "stratum", "advice type", "app", "cond", "n/a")]
    for r in rep["scenarios"]:
        out.append("%-12s %-16s %-22s %5d %5d %5d" % (r["id"], r["stratum"] or "-", r["advice_type"], r["applicable"],
                                                       r["conditional"], r["not_applicable"]))
    out += ["", "Passages marked verify: %d%s" % (len(rep["verify"]), (" (" + ", ".join(rep["verify"]) + ")") if rep["verify"] else ""),
            "Vocabulary violations: %d" % len(rep["vocabulary_violations"])]
    out += ["  " + e for e in rep["vocabulary_violations"]]
    return "\n".join(out)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m smartagri.retrieval.coverage", description=__doc__.split("\n")[0])
    ap.add_argument("--set", default="dev")
    ap.add_argument("--min", type=int, default=3)
    ap.add_argument("--strict", action="store_true", help="exit 1 when a type is below target or meta is invalid")
    args = ap.parse_args(argv)
    if args.set in PROTECTED_SETS:
        print("Refused: the %s set must not be used before the protocol is locked." % args.set, file=sys.stderr)
        return 2
    corpus = load_corpus(validate=False)
    rep = coverage(load_scenarios(args.set), corpus, args.min)
    print(render(rep))
    bad = rep["vocabulary_violations"] or not all(r["meets_target"] for r in rep["per_advice_type"].values())
    return 1 if (args.strict and bad) else 0


if __name__ == "__main__":
    sys.exit(main())
