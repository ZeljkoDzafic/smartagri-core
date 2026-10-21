"""Command line: python -m smartagri.evalkit {run,report,export,guard,sweep,lock} ...

Imports of the pipeline are deferred to the commands that run the system, so `guard` never loads
the decision model."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="smartagri.evalkit")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a scenario set under one or more variants")
    r.add_argument("--set", default="dev", help="folder under eval/scenarios (dev or test)")
    r.add_argument("--variant", action="append",
                   help="variant name; repeatable; default: every variant of variants.yaml. VC (LLM baseline, E5) "
                        "runs only when named and needs LLM_PROVIDER")
    r.add_argument("--repeats", type=int, default=1)
    r.add_argument("--locked", action="store_true",
                   help="required for a protected set (test): verify the protocol lock before running")
    r.add_argument("--lock-file", help="default: backend/eval/protocol-lock.json")
    r.add_argument("--scenarios-dir", help="read scenarios from this folder instead of eval/scenarios/<set>")
    q = sub.add_parser("report", help="automatic measures and, with raters, rated measures")
    q.add_argument("--rater", help="rater whose scores are reported")
    q.add_argument("--compare", nargs=2, metavar=("A", "B"), help="paired difference A - B, e.g. V4 V3")
    q.add_argument("--agreement", nargs=2, metavar=("RATER_A", "RATER_B"))
    q.add_argument("--format", choices=("json", "md"), default="json", help="md: tables of the evaluation report")
    e = sub.add_parser("export", help="dump items and ratings as JSON")
    e.add_argument("--out", default="-")
    e.add_argument("--citation-sample", type=int, metavar="N",
                   help="instead: a fixed-seed sample of N cited sentences for the manual support check")
    e.add_argument("--seed", type=int, default=7)
    g = sub.add_parser("guard", help="n-gram leakage check between scenario texts and the corpus (never runs the system)")
    g.add_argument("--set", default="test")
    g.add_argument("--scenarios-dir", help="read scenarios from this folder instead of eval/scenarios/<set>")
    g.add_argument("--corpus-dir", help="default: SMARTAGRI_CORPUS_DIR or backend/corpus")
    g.add_argument("--share", type=float, default=None, help="flag at this share of shared 8-grams (default 0.5)")
    g.add_argument("--dev-dir", help="development scenarios compared with a non-dev set (default eval/scenarios/dev)")
    g.add_argument("--no-dev", action="store_true", help="compare with the corpus only")
    g.add_argument("--no-isolation", action="store_true", help="skip the git-ignore and index isolation checks")
    s = sub.add_parser("sweep", help="synthetic variations of one development scenario (automatic measures only)")
    s.add_argument("--scenario", required=True)
    s.add_argument("--set", default="dev")
    s.add_argument("--vary", action="append", required=True,
                   help="name=v1,v2,...; names: ndvi_age, forecast_age, soil_water_age, bbch_age (days), usable_share")
    s.add_argument("--variant", default="V5")
    s.add_argument("--format", choices=("json", "text", "both"), default="both")
    k = sub.add_parser("lock", help="write (or --check) the protocol lock: sha256 of scenarios, corpus, config, prompt, rater guide")
    k.add_argument("--set", default="test")
    k.add_argument("--scenarios-dir", help="default: eval/scenarios/<set>")
    k.add_argument("--corpus-dir", help="default: SMARTAGRI_CORPUS_DIR or backend/corpus")
    k.add_argument("--rater-guide", help="default: docs/RATER_GUIDE.md")
    k.add_argument("--cache-snapshot", help="external-cache snapshot (python -m smartagri.cache export) to lock as well")
    k.add_argument("--out", help="default: backend/eval/protocol-lock.json")
    k.add_argument("--tag", default="protocol-v1")
    k.add_argument("--check", action="store_true", help="verify the existing lock instead of writing one")
    k.add_argument("--force", action="store_true", help="overwrite an existing lock file")
    return p


def _lock_inputs(set_name: str, scenarios_dir=None, corpus=None, rater_guide=None, cache_snapshot=None):
    """Current hashes and prompt hash for the protocol lock."""
    from ..config import config_dir
    from ..pipeline.ai_chat import PROMPT_HASH as VC_PROMPT_HASH
    from ..pipeline.generate import PROMPT_HASH
    from ..retrieval.corpus import corpus_dir
    from . import lock
    from .scenarios import scenario_dir
    files = lock.collect(Path(scenarios_dir) if scenarios_dir else scenario_dir(set_name),
                         Path(corpus) if corpus else corpus_dir(), config_dir(),
                         Path(rater_guide) if rater_guide else lock.default_rater_guide(),
                         Path(cache_snapshot) if cache_snapshot else None)
    files["prompt/vc_ai_chat"] = VC_PROMPT_HASH     # the LLM baseline VC (E5) is locked with its own prompt
    return files, PROMPT_HASH


def cmd_lock(args) -> int:
    from . import lock
    out = Path(args.out) if args.out else lock.default_lock_path()
    if args.check:
        if not out.is_file():
            print("lock: no lock file at %s" % out, file=sys.stderr)
            return 2
        locked = lock.read(out)
        try:
            files, prompt = _lock_inputs(locked["set"], args.scenarios_dir, args.corpus_dir, args.rater_guide,
                                         args.cache_snapshot or locked.get("cache_snapshot"))
        except FileNotFoundError as exc:
            print("lock: %s" % exc, file=sys.stderr)
            return 1
        diff = lock.differences(locked, files, prompt)
        print(json.dumps({"lock": str(out), "combined_sha256": locked["combined_sha256"], "differences": diff},
                         ensure_ascii=False, indent=2))
        return 1 if diff else 0
    if out.exists() and not args.force:
        print("lock: %s exists; use --check to verify or --force to replace it" % out, file=sys.stderr)
        return 2
    try:
        files, prompt = _lock_inputs(args.set, args.scenarios_dir, args.corpus_dir, args.rater_guide, args.cache_snapshot)
    except FileNotFoundError as exc:
        print("lock: %s" % exc, file=sys.stderr)
        return 2
    data = lock.make_lock(args.set, files, prompt, Path(args.cache_snapshot) if args.cache_snapshot else None, args.tag)
    lock.write(data, out)
    print(json.dumps({"lock": str(out), "set": args.set, "files": len(files), "prompt_hash": prompt,
                      "combined_sha256": data["combined_sha256"]}, indent=2))
    print("lock: written; tag the commit with `git tag %s` once the human has approved it" % args.tag, file=sys.stderr)
    return 0


def check_run_allowed(args) -> int:
    """0 when `run` may proceed. A protected set needs --locked and a lock that matches the files."""
    from . import lock
    from .scenarios import PROTECTED_SETS
    if args.set not in PROTECTED_SETS:
        return 0
    if not args.locked:
        print("run: refused, the %r set runs only under the locked protocol (pass --locked; see `evalkit lock`)" % args.set,
              file=sys.stderr)
        return 2
    path = Path(args.lock_file) if args.lock_file else lock.default_lock_path()
    if not path.is_file():
        print("run: refused, no protocol lock at %s" % path, file=sys.stderr)
        return 2
    locked = lock.read(path)
    try:
        files, prompt = _lock_inputs(args.set, args.scenarios_dir, None, None, locked.get("cache_snapshot"))
    except FileNotFoundError as exc:
        print("run: refused, %s" % exc, file=sys.stderr)
        return 2
    diff = lock.differences(locked, files, prompt, args.set)
    if diff:
        print("run: refused, the files differ from the protocol lock:\n  " + "\n  ".join(diff), file=sys.stderr)
        return 2
    return 0


def cmd_guard(args) -> int:
    from ..retrieval.corpus import corpus_dir
    from . import guard
    from .scenarios import load_scenarios
    scenarios = load_scenarios(args.set, Path(args.scenarios_dir) if args.scenarios_dir else None)
    cdir = Path(args.corpus_dir) if args.corpus_dir else corpus_dir()
    passages = guard.load_passages(cdir)
    n_corpus = len(passages)
    if args.set != "dev" and not args.no_dev:            # test scenarios must not echo development material
        dev = load_scenarios("dev", Path(args.dev_dir) if args.dev_dir else None)
        passages = passages + guard.scenario_passages(dev)
    res = guard.check(scenarios, passages, share=guard.SHARE if args.share is None else args.share)
    res["n_corpus_passages"], res["n_dev_fields"] = n_corpus, len(passages) - n_corpus
    if not args.no_isolation:
        res["isolation"] = guard.isolation_checks(Path(__file__).resolve().parents[4], cdir,
                                                  Path(__file__).resolve().parents[1] / "retrieval", trace_index=True)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    if not scenarios:
        print("guard: no scenarios in set %r" % args.set, file=sys.stderr)
        return 2
    problems = (res.get("isolation") or {}).get("problems") or []
    print("guard: %d hit(s) over %d scenario field(s), %d corpus passage(s) and %d development field(s); %d isolation problem(s)"
          % (len(res["hits"]), res["n_fields"], n_corpus, res["n_dev_fields"], len(problems)), file=sys.stderr)
    return 1 if res["hits"] or problems else 0


def cmd_sweep(args) -> int:
    from . import sweep as sw
    from .scenarios import PROTECTED_SETS, load_scenario
    if args.set in PROTECTED_SETS:
        print("sweep: refused, the %r set is never run during development" % args.set, file=sys.stderr)
        return 2
    from ..config import load_variants
    from ..pipeline.generate import make_generator
    from ..retrieval import load_corpus, make_retriever
    from .runner import run_scenario
    if args.variant not in load_variants():
        print("sweep: unknown variant %r" % args.variant, file=sys.stderr)
        return 2
    corpus = load_corpus()
    retriever, generator = make_retriever(corpus), make_generator()
    sc = load_scenario(args.set, args.scenario)
    res = sw.sweep(sc, args.set, sw.parse_vary(args.vary), args.variant,
                   lambda s: run_scenario(s, args.variant, corpus, retriever, generator))
    if args.format in ("json", "both"):
        print(json.dumps(res, ensure_ascii=False, indent=2))
    if args.format in ("text", "both"):
        print(sw.text_table(res))
    return 0


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    if args.cmd == "guard":
        return cmd_guard(args)
    if args.cmd == "sweep":
        return cmd_sweep(args)
    if args.cmd == "lock":
        return cmd_lock(args)
    if args.cmd == "run":
        refused = check_run_allowed(args)       # before the store or the pipeline is touched
        if refused:
            return refused

    from ..store import make_store
    store = make_store()
    if args.cmd == "run":
        from ..config import load_variants
        from . import vc
        from .runner import run_batch
        known = set(load_variants()) | set(vc.EXTERNAL_VARIANTS)
        names = args.variant or sorted(load_variants())        # VC needs a model; it runs only when named
        unknown = [n for n in names if n not in known]
        if unknown:
            print("run: unknown variant(s) %s; known: %s" % (", ".join(unknown), ", ".join(sorted(known))), file=sys.stderr)
            return 2
        if any(n in vc.EXTERNAL_VARIANTS for n in names):
            try:
                vc.provider_or_refuse()
            except vc.Unavailable as exc:
                print("run: refused, %s" % exc, file=sys.stderr)
                return 2
        for name in names:
            print(json.dumps(run_batch(store, args.set, name, args.repeats,
                                       Path(args.scenarios_dir) if args.scenarios_dir else None), ensure_ascii=False))
        return 0

    from . import report as rep
    items = store.list_eval_items()
    if args.cmd == "report":
        if args.format == "md":
            from . import tables
            main_pair = tuple(args.compare) if args.compare else ("V4", "V3")
            sys.stdout.write(tables.render(store, items, args.rater, tuple(args.agreement) if args.agreement else None, main_pair))
            return 0
        out = {"automatic": rep.automatic(items)}
        if args.rater:
            rated = rep.rated(store, items, args.rater)
            out["rated"] = {v: {k: x for k, x in m.items() if not k.startswith("_")} for v, m in rated.items()}
            if args.compare:
                out["paired"] = rep.paired(rated, args.compare[0], args.compare[1])
        if args.agreement:
            out["agreement"] = rep.agreement(store, args.agreement[0], args.agreement[1])
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    if args.citation_sample is not None:
        from .citations import sample
        data = json.dumps(sample(items, args.citation_sample, args.seed), ensure_ascii=False, indent=2)
    else:
        data = json.dumps({"items": items, "ratings": store.list_ratings()}, ensure_ascii=False, indent=2)
    if args.out == "-":
        sys.stdout.write(data + "\n")
    else:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
