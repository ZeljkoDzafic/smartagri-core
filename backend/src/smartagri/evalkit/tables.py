"""Markdown tables of the evaluation report, generated only from stored items and ratings.

Every cell without data is "—"; no number is ever typed in by hand (docs/protocol.md). Table and
section numbers follow the evaluation report template. Margins and alpha come from config/analysis.yaml.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..store import Store
from . import report as rep

DASH = "—"
LADDER = ("V0", "V1", "V2", "V3", "V4", "V5")
STEPS = (("V1", "V0", "—"), ("V2", "V1", "—"), ("V3", "V2", "E2"), ("V4", "V3", "E1"), ("V5", "V4", "E3"))
STRATA = (("potpuni ulazi", ("complete",)), ("nedostajući ključni ulaz", ("missing_input",)),
          ("nepouzdan ulaz / konflikt izvora", ("unreliable_input", "conflicting_sources")))
MEASURE_LABELS = (("total", "Rubrika ukupno (0–10)", True), ("r1", "r1 primenljivost radnje", True),
                  ("r2", "r2 uvažavanje uslova parcele", True), ("r3", "r3 utemeljenost", True),
                  ("r4", "r4 naredni korak i nedostajući ulazi", True), ("r5", "r5 odluka o činu i nesigurnost", True),
                  ("critical", "Stopa kritičnih grešaka (bilo koja K)", False),
                  ("K4", "Stopa K4 (preuranjena preporuka)", False),
                  ("K5", "Stopa K5 (neopravdano uzdržavanje / pitanje)", False),
                  ("act_correct", "Tačnost odluke o činu (prvi korak)", False))
E5_PAIR = ("V5", "VC")      # secondary comparison E5: V5 against the LLM baseline with data and sources
E5_RATED = (("total", "Rubrika ukupno (0–10)", True), ("r5", "r5 odluka o činu i nesigurnost", True),
            ("critical", "Stopa kritičnih grešaka (bilo koja K)", False), ("K1", "Stopa K1 (količina bez podataka)", False),
            ("K2", "Stopa K2 (radnja protiv uslova)", False), ("K4", "Stopa K4 (preuranjena preporuka)", False),
            ("K5", "Stopa K5 (neopravdano uzdržavanje / pitanje)", False))
MIN_N_FOR_CI = 10           # docs/protocol.md: no interval for subsets smaller than ten scenarios


def f(x: Any, digits: int = 2) -> str:
    if x is None:
        return DASH
    if isinstance(x, bool):
        return "da" if x else "ne"
    if isinstance(x, int):
        return str(x)
    if isinstance(x, float):
        return ("%.*f" % (digits, x)).replace(".", ",")
    return str(x)


def ci(x: Optional[Sequence[float]]) -> str:
    return DASH if not x else "[%s; %s]" % (f(x[0]), f(x[1]))


def diff_ci(p: Optional[Dict[str, Any]]) -> str:
    return DASH if not p else "%s %s" % (f(p["diff"]), ci(p["ci95"]))


def table(header: Sequence[str], rows: List[Sequence[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


def _variants(items: List[Dict[str, Any]]) -> List[str]:
    seen = sorted({i["variant"] for i in items})
    return list(LADDER) + [v for v in seen if v not in LADDER]


def _by_variant(items):
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for i in items:
        out[i["variant"]].append(i)
    return out


def table_runs(items: List[Dict[str, Any]]) -> str:
    by = _by_variant(items)
    rows, models, hashes = [], set(), set()
    for v in _variants(items):
        g = by.get(v, [])
        if not g:
            rows.append([v] + [DASH] * 8)
            continue
        c = rep.costs(g)
        models.update(c["models"])
        hashes.update(c["corpus_hashes"])
        tokens = DASH if c["input_tokens"] is None else "%s / %s" % (f(int(c["input_tokens"])), f(int(c["output_tokens"] or 0)))
        label = rep.baseline_label(g)
        rows.append([v if not label else "%s (%s)" % (v, label), f(c["n_scenarios"]), f(c["repeats"]), f(c["n_answers"]),
                     f(rep.mean([i["n_turns"] for i in g])), f(None if c["llm_calls"] is None else int(c["llm_calls"])),
                     tokens, f(c["mean_seconds_per_answer"], 3), f(c["usd"])])
    out = table(["Varijanta", "Scenarija", "Ponavljanja", "Odgovora", "Prosečno koraka", "Poziva LLM",
                 "Tokena (ulaz / izlaz)", "Vreme po odgovoru (s)", "Trošak (USD)"], rows)
    note = "Model: %s. corpus_hash: %s." % (", ".join(sorted(models)) or DASH,
                                             ", ".join(h[:12] for h in sorted(hashes)) or DASH)
    return "Tabela 7.1. Izvršeni runovi i trošak po varijanti.\n\n" + out + "\n\n" + note


def template_note(auto: Dict[str, Any]) -> str:
    """A line that says which variants of the report are template output (a fallback), not a baseline; "" for none."""
    names = [v for v in _variants_in(auto) if auto[v].get("baseline_label")]
    if not names:
        return ""
    return ("Napomena: za varijante %s čin nije birao jezički model nego šablon (template, not a baseline): šablon uvek "
            "preporučuje i ne sme se čitati kao osnovna (baseline) vrednost te stepenice. Ove vrednosti služe samo za "
            "proveru razvojnog skupa." % ", ".join(names))


def _variants_in(auto: Dict[str, Any]) -> List[str]:
    return [v for v in LADDER if v in auto] + sorted(v for v in auto if v not in LADDER)


def table_main(scores, meta, a: str, b: str) -> str:
    rows = []
    for key, label, wins in MEASURE_LABELS:
        p = rep.paired_measure(scores, a, b, key, meta)
        wtl = DASH if not (p and wins) else "%d / %d / %d" % (p["wins"], p["ties"], p["losses"])
        rows.append([label, f(rep.variant_mean(scores, b, key)), f(rep.variant_mean(scores, a, key)),
                     DASH if not p else f(p["diff"]), DASH if not p else ci(p["ci95"]), wtl])
    p = rep.paired_measure(scores, a, b, "total", meta)
    n = p["n"] if p else None
    head = ["Mera", b, a, "Razlika %s − %s" % (a, b), "95% CI", "Scenarija u korist %s / izjednačeno / u korist %s" % (a, b)]
    note = "" if not p else "\n\nBootstrap: %s, 10.000 uzoraka, seed 7." % ("klaster (parcela)" if p["bootstrap"] == "cluster" else "po scenariju")
    return ("Tabela 7.2. Primarno poređenje, n = %s scenarija sa ocenom.\n\n" % f(n)) + table(head, rows) + note


def table_strata(scores, meta, a: str, b: str) -> str:
    rows = []
    for label, strata in STRATA:
        scen = [s for s, m in meta.items() if m.get("stratum") in strata]
        both = [s for s in scen if s in scores.get(a, {}) or s in scores.get(b, {})]
        p = rep.paired_measure(scores, a, b, "total", meta, scen)
        interval = DASH if not p or p["n"] < MIN_N_FOR_CI else ci(p["ci95"])
        rows.append([label, f(len(both) or None), f(rep.variant_mean(scores, b, "total", scen)),
                     f(rep.variant_mean(scores, a, "total", scen)), DASH if not p else f(p["diff"]), interval,
                     f(rep.variant_mean(scores, b, "K4", scen)), f(rep.variant_mean(scores, a, "K4", scen)),
                     f(rep.variant_mean(scores, b, "K5", scen)), f(rep.variant_mean(scores, a, "K5", scen))])
    head = ["Stratum", "n", "Rubrika " + b, "Rubrika " + a, "Razlika", "95% CI", "K4 " + b, "K4 " + a, "K5 " + b, "K5 " + a]
    out = ("Tabela 7.3. Primarno poređenje po stratumu scenarija (interval samo za n ≥ %d).\n\n" % MIN_N_FOR_CI) + table(head, rows)
    return out + "\n\n" + equivalence_note(scores, meta)


def _margin_text(m: Optional[float]) -> str:
    return "granica nije zadata" if m is None else "granica ±%s" % f(float(m))


def equivalence_note(scores, meta, settings: Optional[Dict[str, Any]] = None) -> str:
    """Negative control (docs/protocol.md): equivalence (TOST) of the configured comparison on the configured strata."""
    cfg = (settings if settings is not None else rep.analysis_settings()).get("equivalence") or {}
    a, b = (cfg.get("comparison") or ["V4", "V3"])[:2]
    measure, strata, margin = cfg.get("measure", "total"), tuple(cfg.get("strata") or ("complete",)), cfg.get("margin")
    alpha = float((settings if settings is not None else rep.analysis_settings()).get("alpha", 0.05))
    scen = [s for s, m in meta.items() if m.get("stratum") in strata]
    p = rep.paired_measure(scores, a, b, measure, meta, scen)
    if not p:
        return "Negativna kontrola (%s, stratum %s): nema ocenjenih scenarija." % (measure, ", ".join(strata))
    sa, sb = scores.get(a, {}), scores.get(b, {})
    common = [s for s in sorted(set(sa) & set(sb) & set(scen)) if measure in sa[s] and measure in sb[s]]
    diffs = [sa[s][measure] - sb[s][measure] for s in common]
    cl = [meta.get(s, {}).get("cluster", s) for s in common]
    e = rep.equivalence(diffs, margin, cl if len(set(cl)) < len(cl) else None, alpha)
    verdict = "—" if not e or e["equivalent"] is None else ("ekvivalentno" if e["equivalent"] else "nije pokazana ekvivalencija")
    return ("Negativna kontrola (TOST, %s − %s, mera %s, stratum %s, n = %d): razlika %s, %d%% interval %s, %s; %s."
            % (a, b, measure, ", ".join(strata), len(diffs), f(e["diff"]) if e else DASH,
               round(100 * (1 - 2 * alpha)), ci(e["ci"]) if e else DASH, _margin_text(margin), verdict))


def _wilcoxon_p(scores, a: str, b: str, measure: str = "total") -> Optional[float]:
    sa, sb = scores.get(a, {}), scores.get(b, {})
    d = [sa[s][measure] - sb[s][measure] for s in sorted(set(sa) & set(sb)) if measure in sa[s] and measure in sb[s]]
    w = rep.wilcoxon_signed_rank(d)
    return None if w is None else w["p_two_sided"]


def table_ladder(scores, meta, auto) -> str:
    rows = []
    # Secondary family of docs/protocol.md section 4: Holm over the steps that carry a secondary comparison.
    family = {h: _wilcoxon_p(scores, a, b) for a, b, h in STEPS if h not in ("—", "E1")}
    adjusted = rep.holm(family)
    for a, b, h in STEPS:
        cov = DASH
        if a in auto and b in auto:
            cov = f(auto[a]["coverage"] - auto[b]["coverage"])
        p = adjusted.get(h) if h in family else None
        rows.append(["%s − %s" % (a, b), h, diff_ci(rep.paired_measure(scores, a, b, "total", meta)),
                     diff_ci(rep.paired_measure(scores, a, b, "critical", meta)), cov, f(p, 4), DASH])
    head = ["Stepenica", "Poređenje", "Rubrika (razlika, 95% CI)", "Stopa kritičnih grešaka (razlika, 95% CI)",
            "Pokrivenost (razlika)", "p rubrike (Wilcoxon, Holm)", "Glavni nalaz"]
    return "Tabela 7.4. Doprinos pojedinačnih slojeva.\n\n" + table(head, rows)


def table_selective(items, auto, ratings: Dict[str, Dict[str, Any]], variants=("V3", "V4", "V5")) -> str:
    by = _by_variant(items)
    rows: List[List[str]] = [[label] for label in (
        "Udeo odgovora sa pitanjem u prvom koraku", "Ciljanost pitanja", "Prosečan broj razmena do konačnog čina",
        "Pokrivenost (konačna preporuka ili uslovna preporuka)", "Stopa kritičnih grešaka među datim preporukama",
        "Opravdana pitanja / uzdržavanja (po referenci)", "Neopravdana pitanja / uzdržavanja (K5)")]
    for v in variants:
        a, g = auto.get(v), by.get(v, [])
        given = [i for i in g if i["final_act"] in rep.ADVICE_ACTS and i["id"] in ratings]
        crit = rep.mean([1.0 if ratings[i["id"]]["critical"] else 0.0 for i in given])
        asked = [i for i in g if i["first_act"] in ("ask", "abstain")]
        rated_asked = [i for i in asked if i["id"] in ratings]
        k5 = sum(1 for i in rated_asked if "K5" in ratings[i["id"]]["critical"])
        vals = [a and a["first_ask_share"], a and a["question_target_accuracy"], a and a["mean_turns"],
                a and a["coverage"], crit]
        for row, x in zip(rows, vals):
            row.append(f(x))
        rows[5].append(DASH if not a or not a["ask_abstain_with_reference"] else
                       "%d / %d" % (a["justified_ask_abstain"], a["ask_abstain_with_reference"]))
        rows[6].append(DASH if not rated_asked else "%d / %d" % (k5, len(rated_asked)))
    return "Tabela 7.6. Ponašanje selektivnog odgovaranja.\n\n" + table(["Mera"] + list(variants), rows)


def table_e5(items, scores, meta, auto, a: str = E5_PAIR[0], b: str = E5_PAIR[1],
             settings: Optional[Dict[str, Any]] = None) -> str:
    """E5: V5 has a lower critical-error rate (incl. K4) than VC at a rubric score that is not worse (non-inferiority
    with the margin of config/analysis.yaml; no verdict while the margin is not set)."""
    rows = []
    for key, label, wins in E5_RATED:
        p = rep.paired_measure(scores, a, b, key, meta)
        wtl = DASH if not p else "%d / %d / %d" % (p["wins"], p["ties"], p["losses"])
        rows.append([label, f(rep.variant_mean(scores, b, key)), f(rep.variant_mean(scores, a, key)),
                     DASH if not p else f(p["diff"]), DASH if not p else ci(p["ci95"]), wtl])
    by = _by_variant([i for i in items if not i.get("error")])
    def unsupported(v):
        x = auto.get(v) or {}
        if "removed_sentence_rate" in x:
            return x["removed_sentence_rate"]
        return None if x.get("support_rate") is None else 1 - x["support_rate"]
    def usd_per_scenario(v):
        g = by.get(v, [])
        c = rep.costs(g) if g else None
        return None if not c or c["usd"] is None else c["usd"] / float(len(g))
    autos = (("Prosečno koraka razgovora", lambda v: (auto.get(v) or {}).get("mean_turns"), 2),
             ("Udeo prvih odgovora sa pitanjem korisniku", lambda v: rep.first_question_share(by.get(v, [])), 2),
             ("Udeo rečenica bez pokrića (uklonjene ili zamenjene)", unsupported, 3),
             ("Pokrivenost citata", lambda v: (auto.get(v) or {}).get("citation_coverage"), 2),
             ("Trošak po scenariju (USD)", usd_per_scenario, 4))
    for label, get, digits in autos:
        rows.append([label, f(get(b), digits), f(get(a), digits), DASH, DASH, DASH])
    p = rep.paired_measure(scores, a, b, "total", meta)
    cfg = settings if settings is not None else rep.analysis_settings()
    ni_cfg = cfg.get("noninferiority") or {}
    alpha = float(cfg.get("alpha", 0.05))
    sa, sb = scores.get(a, {}), scores.get(b, {})
    common = [s for s in sorted(set(sa) & set(sb)) if "total" in sa[s] and "total" in sb[s]]
    diffs = [sa[s]["total"] - sb[s]["total"] for s in common]
    cl = [meta.get(s, {}).get("cluster", s) for s in common]
    ni = rep.noninferiority(diffs, ni_cfg.get("margin"), cl if len(set(cl)) < len(cl) else None, alpha)
    verdict = DASH if not ni or ni["noninferior"] is None else ("neinferiorno" if ni["noninferior"] else "neinferiornost nije pokazana")
    head = ["Mera", b, a, "Razlika %s − %s" % (a, b), "95% CI", "Scenarija u korist %s / izjednačeno / u korist %s" % (a, b)]
    note = ("Neinferiornost rubrike (jednostrano, alfa/2 = %s): donja granica %s, %s; %s. "
            "E5 je potvrđeno ako je stopa kritičnih grešaka %s niža (interval razlike ispod nule) a rubrika neinferiorna. "
            "Za stope grešaka „u korist %s” znači veću stopu. "
            "%s je slobodan LLM odgovor sa istim podacima i istim primenljivim izvorima, bez modela odlučivanja."
            % (f(alpha / 2.0, 3), f(ni["lower"]) if ni else DASH, _margin_text(ni_cfg.get("margin")), verdict, a, a, b))
    return ("Tabela 7.10. Sekundarno poređenje E5: %s prema %s (LLM sa podacima i izvorima), n = %s scenarija sa ocenom.\n\n"
            % (a, b, f(p["n"] if p else None))) + table(head, rows) + "\n\n" + note


def table_retrieval(auto, variants=("V1", "V2", "V3", "V4", "V5")) -> str:
    rows = [["Recall@k primenljivih izvora"], ["Preciznost primenljivih izvora u budžetu"],
            ["Udeo neprimenljivih izvora u budžetu"], ["Pokrivenost citata"], ["Ispravnost citata"]]
    for v in variants:
        a = auto.get(v) or {}
        for row, key in zip(rows, ("recall_at_k", "precision_applicable", "not_applicable_rate", "citation_coverage", None)):
            row.append(f(a.get(key)) if key else DASH)
    ks = sorted({k for v in variants for k in (auto.get(v) or {}).get("k", [])})
    unresolved = sorted({e for v in variants for e in (auto.get(v) or {}).get("unresolved_sources", [])})
    note = "k (veličina budžeta): %s. Izvori iz referenci kojih nema u korpusu: %s. Ispravnost citata (LLM-NLI) nije realizovana." % (
        ", ".join(str(k) for k in ks) or DASH, ", ".join(unresolved) or DASH)
    return "Tabela 7.7. Mere pronalaženja i citiranja.\n\n" + table(["Mera"] + list(variants), rows) + "\n\n" + note


def table_agreement(agree: Optional[Dict[str, Any]], raters: Optional[Tuple[str, str]]) -> str:
    rows = []
    for c in rep.CRITERIA:
        x = (agree or {}).get(c) or {}
        rows.append([c, f(x.get("kappa_quadratic")), ci(x.get("kappa_ci95")), f(x.get("percent_agreement"))])
    x = (agree or {}).get("critical_any") or {}
    rows.append(["Kritična greška (da / ne)", f(x.get("kappa")), ci(x.get("kappa_ci95")), f(x.get("percent_agreement"))])
    for k in ("K1", "K2", "K3", "K4", "K5"):
        x = (agree or {}).get("critical_" + k) or {}
        rows.append([k, f(x.get("kappa")), ci(x.get("kappa_ci95")), f(x.get("percent_agreement"))])
    who = "%s – %s" % raters if raters else "ocenjivač A – ocenjivač B"
    n = (agree or {}).get("n_items")
    return ("Tabela 7.8. Slaganje ocenjivača (%s), n = %s stavki. Za r1–r5 ponderisani κ (kvadratne težine, Cohen 1968), "
            "za K neponderisani (Cohen 1960); 95%% CI: bootstrap po stavkama.\n\n" % (who, f(n) if n else DASH)) + \
        table(["Kriterijum", "κ", "95% CI", "Udeo potpunog slaganja"], rows)


def render(store: Store, items: List[Dict[str, Any]], rater: Optional[str] = None,
           agreement: Optional[Tuple[str, str]] = None, main: Tuple[str, str] = ("V4", "V3")) -> str:
    auto = rep.automatic(items) if items else {}
    scores = rep.scenario_scores(store, items, rater)
    meta = rep.scenario_meta(items)
    ratings = {r["item_id"]: r for r in store.list_ratings(rater)} if rater else {}
    agree = rep.agreement(store, agreement[0], agreement[1], items) if agreement else None
    a, b = main
    parts = [
        "<!-- Generated by `python -m smartagri.evalkit report --format md`; do not edit by hand. -->",
        "Ocenjivač: %s." % (rater or DASH),
    ]
    note = template_note(auto)
    if note:
        parts.append(note)
    parts += [
        "## 7.1 Izvršeni runovi i trošak", table_runs(items),
        "## 7.2 Primarno poređenje: %s prema %s" % (a, b), table_main(scores, meta, a, b), table_strata(scores, meta, a, b),
        "## 7.3 Stepenice lestvice", table_ladder(scores, meta, auto),
        "## 7.5 Cena aktivnog pitanja", table_selective(items, auto, ratings),
        "## E5 Poređenje sa jakim LLM osnovom (VC)", table_e5(items, scores, meta, auto),
        "## 7.6 Pronalaženje izvora i citati", table_retrieval(auto),
        "## 7.7 Slaganje ocenjivača", table_agreement(agree, agreement),
    ]
    return "\n\n".join(parts) + "\n"
