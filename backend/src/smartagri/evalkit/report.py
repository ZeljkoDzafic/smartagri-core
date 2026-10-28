"""Metrics over stored evaluation items and ratings. Standard library only."""
from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..store import Store
from . import sources as src

CRITERIA = ("r1", "r2", "r3", "r4", "r5")
ADVICE_ACTS = ("recommend", "conditional")


def _r(x: Optional[float], digits: int = 3) -> Optional[float]:
    return None if x is None else round(x, digits)


def retrieval_measures(group: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Mean Recall@k, precision of applicable sources and not-applicable rate over items whose
    scenario names reference sources; citation coverage = share of advice-giving answers
    (recommend or conditional, any turn) that cite at least one source."""
    per = [src.scores(i["retrieval"]) for i in group if i.get("retrieval")]
    def avg(key):
        xs = [p[key] for p in per if p[key] is not None]
        return _r(mean(xs)), len(xs)
    recall, n_recall = avg("recall_at_k")
    precision, n_precision = avg("precision_applicable")
    na_rate, n_na = avg("not_applicable_rate")
    answers = [t["answer"] for i in group for t in i.get("turns", []) if t["answer"].get("act") in ADVICE_ACTS]
    cited = [a for a in answers if a.get("sources")]
    ks = sorted({i["retrieval"]["k"] for i in group if i.get("retrieval")})
    return {"recall_at_k": recall, "recall_n": n_recall, "precision_applicable": precision, "precision_n": n_precision,
            "not_applicable_rate": na_rate, "not_applicable_n": n_na, "k": ks,
            "unresolved_sources": sorted({e for i in group if i.get("retrieval") for e in i["retrieval"]["unresolved"]}),
            "citation_coverage": _r(len(cited) / float(len(answers))) if answers else None, "citation_n": len(answers)}


def support_measures(group: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Passage-support part of gamma per variant.

    support_rate = 1 - unsupported / checked over every turn whose model text went through the
    support check (`decisions.grounding.checked_sentences`); unit = rationale sentence or summary
    sentence. `grounding_actions` counts every grounding outcome (template, not_checked, checked,
    summary_replaced_by_template, replaced_by_template, template_after_*), so fallbacks are visible."""
    checked = unsupported = 0
    actions: Dict[str, int] = defaultdict(int)
    for i in group:
        for r in i.get("records", []):
            g = (r.get("decisions") or {}).get("grounding") or {}
            actions[g.get("action") or "none"] += 1
            if g.get("checked_sentences"):
                checked += int(g["checked_sentences"])
                unsupported += len(g.get("unsupported_sentences") or [])
    return {"support_rate": _r(1 - unsupported / float(checked)) if checked else None, "support_n": checked,
            "unsupported_sentences": unsupported, "grounding_actions": dict(sorted(actions.items()))}


def costs(group: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Cost per variant from each turn's `cost` record: model calls, tokens, seconds and, when the
    generator reports it, money (`usd`)."""
    recs = [r.get("cost") or {} for i in group for r in i.get("records", [])]
    def total(key):
        xs = [float(c[key]) for c in recs if c.get(key) is not None]
        return sum(xs) if xs else None
    seconds = [sum(float((r.get("cost") or {}).get("seconds") or 0) for r in i.get("records", [])) for i in group]
    return {"n_scenarios": len({i["scenario_id"] for i in group}),
            "repeats": max([int(i.get("repeat") or 1) for i in group] or [0]),
            "n_answers": len(group), "llm_calls": total("llm_calls"), "input_tokens": total("input_tokens"),
            "output_tokens": total("output_tokens"), "usd": total("usd"),
            "mean_seconds_per_answer": _r(mean(seconds)) if seconds else None,
            "models": sorted({str(r.get("provenance", {}).get("model")) for i in group for r in i.get("records", [])
                              if r.get("provenance", {}).get("model")}),
            "corpus_hashes": sorted({r.get("provenance", {}).get("corpus_hash") for i in group for r in i.get("records", [])
                                     if r.get("provenance", {}).get("corpus_hash")})}


def mean(xs: Sequence[float]) -> Optional[float]:
    return sum(xs) / float(len(xs)) if xs else None


def bootstrap_ci(diffs: Sequence[float], n: int = 10000, seed: int = 7,
                 clusters: Optional[Sequence[str]] = None, level: float = 0.95) -> Optional[Tuple[float, float]]:
    """Percentile interval (default 95 %) for the mean paired difference.

    Without clusters, scenarios are resampled. With clusters (e.g. scenarios sharing a parcel),
    whole clusters are resampled with replacement, which respects the dependence between them.
    """
    if len(diffs) < 2:
        return None
    rng = random.Random(seed)
    if clusters is None:
        groups = [[d] for d in diffs]
    else:
        by: Dict[str, List[float]] = defaultdict(list)
        for d, c in zip(diffs, clusters):
            by[c].append(d)
        groups = [by[c] for c in sorted(by)]
        if len(groups) < 2:
            return None
    means = []
    for _ in range(n):
        sample = [x for _g in groups for x in rng.choice(groups)]
        means.append(mean(sample))
    means.sort()
    tail = (1.0 - level) / 2.0
    return means[int(round(tail * n))], means[int(round((1.0 - tail) * n)) - 1]


def noninferiority(diffs: Sequence[float], margin: Optional[float], clusters: Optional[Sequence[str]] = None,
                   alpha: float = 0.05, n: int = 10000, seed: int = 7) -> Optional[Dict[str, Any]]:
    """Non-inferiority of a against b on a measure where higher is better, diffs = a - b.

    One-sided test at alpha/2 (the lower limit of the two-sided 1 - alpha percentile interval): a is non-inferior
    when that lower limit lies above -margin. margin None = not decided: the interval is returned without a verdict."""
    ci = bootstrap_ci(diffs, n, seed, clusters, level=1.0 - alpha)
    if ci is None:
        return None
    verdict = None if margin is None else ci[0] > -abs(float(margin))
    return {"diff": _r(mean(diffs)), "ci": ci, "lower": ci[0], "margin": margin, "noninferior": verdict,
            "test": "one-sided, alpha/2 = %.3f, percentile bootstrap" % (alpha / 2.0)}


def equivalence(diffs: Sequence[float], margin: Optional[float], clusters: Optional[Sequence[str]] = None,
                alpha: float = 0.05, n: int = 10000, seed: int = 7) -> Optional[Dict[str, Any]]:
    """Two one-sided tests (TOST) at alpha: equivalent when the 1 - 2 alpha percentile interval of the mean difference
    lies inside (-margin, +margin). margin None = not decided: the interval is returned without a verdict."""
    ci = bootstrap_ci(diffs, n, seed, clusters, level=1.0 - 2.0 * alpha)
    if ci is None:
        return None
    m = None if margin is None else abs(float(margin))
    verdict = None if m is None else (-m < ci[0] and ci[1] < m)
    return {"diff": _r(mean(diffs)), "ci": ci, "margin": margin, "equivalent": verdict,
            "test": "TOST, alpha = %.3f, %d %% percentile bootstrap interval" % (alpha, round(100 * (1 - 2 * alpha)))}


def wilcoxon_signed_rank(diffs: Sequence[float]) -> Optional[Dict[str, float]]:
    """Two-sided Wilcoxon signed-rank test, normal approximation with tie correction.

    Zero differences are dropped (Wilcoxon's convention). Supplementary only: it assumes
    independent scenarios, which the protocol states is not fully met.
    """
    d = [x for x in diffs if x != 0]
    n = len(d)
    if n < 6:
        return None
    order = sorted(range(n), key=lambda i: abs(d[i]))
    ranks = [0.0] * n
    i, ties = 0, 0.0
    while i < n:
        j = i
        while j + 1 < n and abs(d[order[j + 1]]) == abs(d[order[i]]):
            j += 1
        r = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = r
        t = j - i + 1
        ties += t ** 3 - t
        i = j + 1
    w_plus = sum(r for r, x in zip(ranks, d) if x > 0)
    mu = n * (n + 1) / 4.0
    sigma = math.sqrt(n * (n + 1) * (2 * n + 1) / 24.0 - ties / 48.0)
    if sigma == 0:
        return None
    z = (w_plus - mu) / sigma
    p = math.erfc(abs(z) / math.sqrt(2))
    return {"n": n, "w_plus": w_plus, "z": round(z, 3), "p_two_sided": round(p, 4)}


def holm(pvalues: Dict[str, Optional[float]]) -> Dict[str, Optional[float]]:
    """Holm step-down adjustment of a family of p-values ({name: p}); None stays None and is not counted."""
    named = sorted(((p, k) for k, p in pvalues.items() if p is not None))
    m, out, running = len(named), {k: None for k in pvalues}, 0.0
    for rank, (p, k) in enumerate(named):
        running = max(running, min(1.0, (m - rank) * p))
        out[k] = round(running, 4)
    return out


def weighted_kappa(a: Sequence[int], b: Sequence[int], categories: int = 3, weights: str = "quadratic") -> Optional[float]:
    """Cohen's kappa for two raters on an ordinal 0..categories-1 scale.

    weights: "quadratic" (protocol default), "linear", or "none" (unweighted kappa).
    """
    if not a or len(a) != len(b):
        return None
    n = float(len(a))
    power = {"quadratic": 2, "linear": 1}.get(weights)
    if power is None:
        w = [[0.0 if i == j else 1.0 for j in range(categories)] for i in range(categories)]
    else:
        w = [[(abs(i - j) / float(categories - 1)) ** power for j in range(categories)] for i in range(categories)]
    obs = sum(w[x][y] for x, y in zip(a, b)) / n
    pa = [sum(1 for x in a if x == i) / n for i in range(categories)]
    pb = [sum(1 for y in b if y == j) / n for j in range(categories)]
    exp = sum(w[i][j] * pa[i] * pb[j] for i in range(categories) for j in range(categories))
    return None if exp == 0 else 1.0 - obs / exp


def kappa_ci(a: Sequence[int], b: Sequence[int], categories: int = 3, weights: str = "quadratic",
             n: int = 2000, seed: int = 7, level: float = 0.95) -> Optional[Tuple[float, float]]:
    """Percentile bootstrap interval for Cohen's kappa (weighted kappa: Cohen, 1968), resampling rated items.
    Resamples where kappa is undefined (one category only) are skipped; None with fewer than 2 items or when more
    than half of the resamples are undefined."""
    if len(a) < 2 or len(a) != len(b):
        return None
    rng = random.Random(seed)
    idx = list(range(len(a)))
    vals = []
    for _ in range(n):
        pick = [rng.choice(idx) for _ in idx]
        k = weighted_kappa([a[i] for i in pick], [b[i] for i in pick], categories, weights)
        if k is not None:
            vals.append(k)
    if len(vals) < n / 2.0:
        return None
    vals.sort()
    tail = (1.0 - level) / 2.0
    return round(vals[int(round(tail * len(vals)))], 3), round(vals[int(round((1.0 - tail) * len(vals))) - 1], 3)


def is_text(item: Dict[str, Any]) -> bool:
    """A free-text item (the LLM baseline VC): no explicit act; judged only by raters."""
    return item.get("answer_format") == "text"


def acceptable_acts(item: Dict[str, Any]) -> List[str]:
    """Acts accepted as correct in the first turn: the dev `expect` block for this variant,
    or the test `reference` block (correct act plus any equally acceptable alternatives).
    Empty for free-text items, which state no act."""
    if is_text(item):
        return []
    if item.get("expect") and "act" in item["expect"]:
        return [item["expect"]["act"]]
    ref = item.get("reference") or {}
    if "correct_act_first_turn" in ref:
        return [ref["correct_act_first_turn"]] + list(ref.get("also_acceptable_first_turn") or [])
    return []


def acceptable_questions(item: Dict[str, Any]) -> Optional[List[Optional[str]]]:
    """Inputs a first-turn question may target; None when the scenario does not say."""
    if item.get("expect") and "question" in item["expect"]:
        return [item["expect"]["question"]]
    ref = item.get("reference") or {}
    if item["first_act"] in ("ask", "conditional") and ref.get("acceptable_question_inputs"):
        return list(ref["acceptable_question_inputs"])
    return None


def text_measures(group: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Automatic measures for free-text items (VC), which have no act: turns, share of first answers
    that end with a question to the user, sentences removed by the grounding check, referrals,
    citation coverage, retrieval and cost."""
    first_q = [bool((i.get("ends_with_question") or [False])[0]) for i in group]
    all_q = [bool(x) for i in group for x in (i.get("ends_with_question") or [])]
    checked = removed = 0
    for i in group:
        for r in i.get("records", []):
            g = (r.get("decisions") or {}).get("grounding") or {}
            checked += int(g.get("checked_sentences") or 0)
            removed += len(g.get("unsupported_sentences") or [])
    answers = [t["answer"] for i in group for t in i.get("turns", [])]
    c = costs(group)
    out = {"n": len(group), "answer_format": "text", "first_act_counts": {}, "act_accuracy": None, "act_accuracy_n": 0,
           "question_target_accuracy": None, "mean_turns": round(mean([i["n_turns"] for i in group]), 2),
           "coverage": None, "first_ask_share": None, "justified_ask_abstain": 0, "ask_abstain_with_reference": 0,
           "first_ends_with_question_share": round(mean([1.0 if x else 0.0 for x in first_q]), 3),
           "ends_with_question_share": _r(mean([1.0 if x else 0.0 for x in all_q])) if all_q else None,
           "reply_matched_share": _r(mean([1.0 if i.get("first_question_input") else 0.0 for i, q in zip(group, first_q) if q]))
           if any(first_q) else None,
           "removed_sentence_rate": _r(removed / float(checked)) if checked else None, "removed_sentences": removed,
           "checked_sentences": checked,
           "referral_share": _r(mean([1.0 if a.get("referral") else 0.0 for a in answers])) if answers else None,
           "usd": c["usd"], "usd_per_scenario": _r(c["usd"] / float(len(group)), 4) if c["usd"] is not None else None,
           "mean_seconds_per_answer": c["mean_seconds_per_answer"], "models": c["models"]}
    rm = retrieval_measures(group)
    rm["citation_coverage"] = _r(sum(1 for a in answers if a.get("citations")) / float(len(answers))) if answers else None
    rm["citation_n"] = len(answers)
    out.update(rm)
    out.update(support_measures(group))
    return out


def first_question_share(group: List[Dict[str, Any]]) -> Optional[float]:
    """Share of first answers that put a question to the user: a pending `next_question` in a structured
    answer, or a free-text answer that ends with a question."""
    xs = []
    for i in group:
        if i.get("error") or not i.get("turns"):
            continue
        if is_text(i):
            xs.append(1.0 if (i.get("ends_with_question") or [False])[0] else 0.0)
        else:
            xs.append(1.0 if i["turns"][0]["answer"].get("next_question") else 0.0)
    return _r(mean(xs))


def automatic(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Measures that need no rater: act distribution, agreement with the scenario's expected act, turns.
    Items whose run failed (`error`) are counted apart and left out of every measure."""
    by_variant: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    failed: Dict[str, int] = defaultdict(int)
    for i in items:
        if i.get("error"):
            failed[i["variant"]] += 1
        else:
            by_variant[i["variant"]].append(i)
    out: Dict[str, Any] = {}
    for variant, group in sorted(by_variant.items()):
        if all(is_text(i) for i in group):
            out[variant] = dict(text_measures(group), failed=failed.get(variant, 0))
            continue
        acts = defaultdict(int)
        for i in group:
            acts[i["first_act"]] += 1
        expected = [i for i in group if acceptable_acts(i)]
        hits = [i for i in expected if i["first_act"] in acceptable_acts(i)]
        q_expected = [i for i in expected if acceptable_questions(i) is not None]
        q_hits = [i for i in q_expected if i["first_question_input"] in acceptable_questions(i)]
        out[variant] = {
            "n": len(group), "first_act_counts": dict(acts),
            "act_accuracy": None if not expected else round(len(hits) / float(len(expected)), 3),
            "act_accuracy_n": len(expected),
            "question_target_accuracy": None if not q_expected else round(len(q_hits) / float(len(q_expected)), 3),
            "mean_turns": round(mean([i["n_turns"] for i in group]), 2),
            "coverage": round(sum(1 for i in group if i["final_act"] in ADVICE_ACTS) / float(len(group)), 3),
            "first_ask_share": round(sum(1 for i in group if i["first_act"] == "ask") / float(len(group)), 3),
            "justified_ask_abstain": sum(1 for i in group if i["first_act"] in ("ask", "abstain") and i["first_act"] in acceptable_acts(i)),
            "ask_abstain_with_reference": sum(1 for i in group if i["first_act"] in ("ask", "abstain") and acceptable_acts(i)),
            "failed": failed.get(variant, 0),
        }
        out[variant].update(retrieval_measures(group))
        out[variant].update(support_measures(group))
        label = baseline_label(group)
        if label:
            out[variant]["baseline_label"] = label
    return out


def baseline_label(group: List[Dict[str, Any]]) -> Optional[str]:
    """"template, not a baseline" when any item of a variant whose act the model chooses (V0-V3) was produced by the
    template generator; None otherwise. Such a group is a fallback of the dev-set check, never a result of the rung."""
    labels = sorted({(i.get("baseline") or {}).get("label") for i in group} - {None})
    return labels[0] if labels else None


def rated(store: Store, items: List[Dict[str, Any]], rater: str) -> Dict[str, Dict[str, Any]]:
    """Per variant: mean rubric total and critical-error rate, averaging repeats within a scenario first."""
    ratings = {r["item_id"]: r for r in store.list_ratings(rater)}
    per: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for i in items:
        if i["id"] in ratings:
            per[i["variant"]][i["scenario_id"]].append(ratings[i["id"]])
    clusters = {i["scenario_id"]: i.get("cluster") or i["scenario_id"] for i in items}
    out = {}
    for variant, scenarios in sorted(per.items()):
        totals = {s: mean([sum(r[c] for c in CRITERIA) for r in rs]) for s, rs in scenarios.items()}
        critical = {s: mean([1.0 if r["critical"] else 0.0 for r in rs]) for s, rs in scenarios.items()}
        k4 = {s: mean([1.0 if "K4" in r["critical"] else 0.0 for r in rs]) for s, rs in scenarios.items()}
        out[variant] = {"n_scenarios": len(scenarios), "rubric_total": round(mean(list(totals.values())), 3),
                        "critical_rate": round(mean(list(critical.values())), 3), "k4_rate": round(mean(list(k4.values())), 3),
                        "_totals": totals, "_critical": critical, "_clusters": clusters}
    return out


def paired(rated_out: Dict[str, Dict[str, Any]], a: str, b: str) -> Optional[Dict[str, Any]]:
    """Paired difference a - b over the scenarios both variants were rated on."""
    if a not in rated_out or b not in rated_out:
        return None
    common = sorted(set(rated_out[a]["_totals"]) & set(rated_out[b]["_totals"]))
    if not common:
        return None
    d_total = [rated_out[a]["_totals"][s] - rated_out[b]["_totals"][s] for s in common]
    d_crit = [rated_out[a]["_critical"][s] - rated_out[b]["_critical"][s] for s in common]
    cl = [rated_out[a]["_clusters"].get(s, s) for s in common]
    clustered = len(set(cl)) < len(cl)
    return {"a": a, "b": b, "n_scenarios": len(common), "n_clusters": len(set(cl)),
            "bootstrap": "cluster" if clustered else "scenario",
            "rubric_diff": round(mean(d_total), 3), "rubric_ci95": bootstrap_ci(d_total, clusters=cl if clustered else None),
            "critical_rate_diff": round(mean(d_crit), 3),
            "critical_ci95": bootstrap_ci(d_crit, clusters=cl if clustered else None),
            "rubric_wilcoxon": wilcoxon_signed_rank(d_total)}


def agreement(store: Store, rater_a: str, rater_b: str, items: Optional[List[Dict[str, Any]]] = None,
              kappa_samples: int = 2000, seed: int = 7) -> Dict[str, Any]:
    """Agreement of two raters on the items both rated (restricted to `items` when given: one set and its batches).
    r1-r5: quadratic-weighted kappa (Cohen, 1968) with a percentile bootstrap interval over items; K classes:
    unweighted kappa (Cohen, 1960) with interval; percent agreement for both."""
    ra = {r["item_id"]: r for r in store.list_ratings(rater_a)}
    rb = {r["item_id"]: r for r in store.list_ratings(rater_b)}
    common = sorted(set(ra) & set(rb))
    if items is not None:
        allowed = {i["id"] for i in items}
        common = [i for i in common if i in allowed]
    out: Dict[str, Any] = {"n_items": len(common)}
    def r(x):
        return None if x is None else round(x, 3)
    for c in CRITERIA:
        xa, xb = [ra[i][c] for i in common], [rb[i][c] for i in common]
        out[c] = {"kappa_quadratic": r(weighted_kappa(xa, xb)),
                  "kappa_ci95": kappa_ci(xa, xb, n=kappa_samples, seed=seed),
                  "percent_agreement": r(mean([1.0 if x == y else 0.0 for x, y in zip(xa, xb)]))}
    flags = [("any", lambda rt: bool(rt["critical"]))] + \
        [(k, (lambda key: lambda rt: key in rt["critical"])(k)) for k in ("K1", "K2", "K3", "K4", "K5")]
    for name, has in flags:
        xa, xb = [1 if has(ra[i]) else 0 for i in common], [1 if has(rb[i]) else 0 for i in common]
        out["critical_" + name] = {"kappa": r(weighted_kappa(xa, xb, 2, "none")),
                                   "kappa_ci95": kappa_ci(xa, xb, 2, "none", n=kappa_samples, seed=seed),
                                   "percent_agreement": r(mean([1.0 if x == y else 0.0 for x, y in zip(xa, xb)]))}
    return out


# ---------------------------------------------------------------- per-scenario measures for the report tables

RATED_MEASURES = ("total",) + CRITERIA + ("critical", "K1", "K2", "K3", "K4", "K5")


def scenario_scores(store: Store, items: List[Dict[str, Any]], rater: Optional[str]) -> Dict[str, Dict[str, Dict[str, float]]]:
    """variant -> scenario -> measure -> value, repeats averaged first (docs/protocol.md).

    Rated measures (total, r1..r5, critical, K1..K5) need `rater`; `act_correct` is automatic and
    present whenever the scenario states acceptable first-turn acts."""
    ratings = {r["item_id"]: r for r in store.list_ratings(rater)} if rater else {}
    per: Dict[str, Dict[str, Dict[str, List[float]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for i in items:
        cell = per[i["variant"]][i["scenario_id"]]
        ok = acceptable_acts(i)
        if ok:
            cell["act_correct"].append(1.0 if i["first_act"] in ok else 0.0)
        r = ratings.get(i["id"])
        if r is not None:
            cell["total"].append(float(sum(r[c] for c in CRITERIA)))
            for c in CRITERIA:
                cell[c].append(float(r[c]))
            cell["critical"].append(1.0 if r["critical"] else 0.0)
            for k in ("K1", "K2", "K3", "K4", "K5"):
                cell[k].append(1.0 if k in r["critical"] else 0.0)
    return {v: {s: {m: mean(xs) for m, xs in cell.items()} for s, cell in scen.items()} for v, scen in per.items()}


def scenario_meta(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {i["scenario_id"]: {"stratum": i.get("stratum"), "cluster": i.get("cluster") or i["scenario_id"]} for i in items}


def paired_measure(scores: Dict[str, Dict[str, Dict[str, float]]], a: str, b: str, measure: str,
                   meta: Dict[str, Dict[str, Any]], scenarios: Optional[Sequence[str]] = None) -> Optional[Dict[str, Any]]:
    """Paired a - b on one measure over scenarios both variants have it for; cluster bootstrap when
    scenarios share a parcel. wins/ties/losses count scenarios in favour of a, equal, in favour of b
    (for error rates lower is better, so the caller reads the sign)."""
    sa, sb = scores.get(a, {}), scores.get(b, {})
    common = sorted(s for s in set(sa) & set(sb) if measure in sa[s] and measure in sb[s]
                    and (scenarios is None or s in scenarios))
    if not common:
        return None
    d = [sa[s][measure] - sb[s][measure] for s in common]
    cl = [meta.get(s, {}).get("cluster", s) for s in common]
    clustered = len(set(cl)) < len(cl)
    return {"n": len(common), "a": _r(mean([sa[s][measure] for s in common])), "b": _r(mean([sb[s][measure] for s in common])),
            "diff": _r(mean(d)), "ci95": bootstrap_ci(d, clusters=cl if clustered else None),
            "bootstrap": "cluster" if clustered else "scenario",
            "wins": sum(1 for x in d if x > 0), "ties": sum(1 for x in d if x == 0), "losses": sum(1 for x in d if x < 0)}


def select(items: List[Dict[str, Any]], set_name: Optional[str] = None,
           batches: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    """Items of one scenario set and, when given, of the named batches only. Raises ValueError when no set is named
    and the items span more than one set: a report never mixes dev and test."""
    out = [i for i in items if (set_name is None or i.get("set") == set_name)
           and (not batches or i.get("batch_id") in batches)]
    sets = sorted({str(i.get("set")) for i in out})
    if len(sets) > 1:
        raise ValueError("the items span several scenario sets (%s); choose one with --set" % ", ".join(sets))
    return out


def analysis_settings() -> Dict[str, Any]:
    """config/analysis.yaml (alpha, bootstrap, margins); defaults when absent."""
    from .. import config
    try:
        data = config.load("analysis") or {}
    except FileNotFoundError:
        data = {}
    return data


def variant_mean(scores: Dict[str, Dict[str, Dict[str, float]]], variant: str, measure: str,
                 scenarios: Optional[Sequence[str]] = None) -> Optional[float]:
    xs = [m[measure] for s, m in scores.get(variant, {}).items() if measure in m and (scenarios is None or s in scenarios)]
    return _r(mean(xs))
