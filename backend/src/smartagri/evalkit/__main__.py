"""Command line: python -m smartagri.evalkit {run,report,export,guard,sweep,lock} ...

Imports of the pipeline are deferred to the commands that run the system, so `guard` never loads
the decision model."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="smartagri.evalkit")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a scenario set under one or more variants")
    r.add_argument("--set", default="dev", help="folder under eval/scenarios (dev or test)")
    r.add_argument("--variant", action="append",
                   help="variant name; repeatable; default: every variant of variants.yaml. VC (LLM baseline, E5) "
                        "runs only when named and needs LLM_PROVIDER")
    r.add_argument("--repeats", type=int, default=1)
    r.add_argument("--decision-hour-utc", type=int, metavar="H",
                   help="fix the decision moment of every scenario to H:00 UTC of its own day (default: as written in the "
                        "files; a locked run must use the locked value)")
    r.add_argument("--locked", action="store_true",
                   help="required for a protected set (test): verify the protocol lock before running")
    r.add_argument("--lock-file", help="default: backend/eval/protocol-lock.json (the repository's lock). Any other file "
                                       "is accepted only together with --lock-sha256")
    r.add_argument("--lock-sha256", help="sha256 of the lock file, as recorded (registration, tag); required with a "
                                         "--lock-file other than the repository's lock, and checked against the file")
    r.add_argument("--scenarios-dir", help="read scenarios from this folder instead of eval/scenarios/<set>")
    q = sub.add_parser("report", help="automatic measures and, with raters, rated measures")
    q.add_argument("--set", help="scenario set to report (required when the store holds more than one set)")
    q.add_argument("--batch", action="append", help="batch id to report; repeatable; default: every batch of the set")
    q.add_argument("--rater", help="rater whose scores are reported")
    q.add_argument("--compare", nargs=2, metavar=("A", "B"), help="paired difference A - B, e.g. V4 V3")
    q.add_argument("--agreement", nargs=2, metavar=("RATER_A", "RATER_B"))
    q.add_argument("--format", choices=("json", "md"), default="json", help="md: tables of the evaluation report")
    e = sub.add_parser("export", help="dump items and ratings as JSON")
    e.add_argument("--set", help="only items of this scenario set")
    e.add_argument("--batch", action="append", help="only items of this batch; repeatable")
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
    a = sub.add_parser("assign", help="assign the items of one set (and batches) to a rater in a seeded order")
    a.add_argument("--set", required=True)
    a.add_argument("--batch", action="append", help="batch id; repeatable; default: every batch of the set")
    a.add_argument("--variant", action="append", help="variant; repeatable; default: every variant")
    a.add_argument("--rater", required=True)
    a.add_argument("--seed", type=int, default=7)
    a.add_argument("--repeat", type=int, help="rate only this repetition of every scenario")
    a.add_argument("--pick-repeat", action="store_true",
                   help="rate one repetition per scenario, chosen with the seed (the same for every variant and rater)")
    a.add_argument("--per-stratum", type=int, metavar="N",
                   help="a balanced subset: N scenarios of each stratum, chosen with the seed (the same for every rater)")
    a.add_argument("--dry-run", action="store_true", help="print the assignment without writing it")
    k = sub.add_parser("lock", help="write (or --check) the protocol lock: sha256 of scenarios, corpus, config, prompt, rater guide")
    k.add_argument("--set", default="test")
    k.add_argument("--scenarios-dir", help="default: eval/scenarios/<set>")
    k.add_argument("--corpus-dir", help="default: SMARTAGRI_CORPUS_DIR or backend/corpus")
    k.add_argument("--rater-guide", help="default: docs/RATER_GUIDE.md")
    k.add_argument("--analysis-plan", help="default: docs/protocol.md")
    k.add_argument("--cache-snapshot", help="external-cache snapshot (python -m smartagri.cache export); mandatory for a "
                                           "protected set (test)")
    k.add_argument("--out", help="default: backend/eval/protocol-lock.json")
    k.add_argument("--tag", default="protocol-v1")
    k.add_argument("--repeats", type=int, default=1, help="generations per scenario and variant of the locked run "
                                                          "(part of the lock; a locked run must use the same number)")
    k.add_argument("--variant", action="append", help="variants of the first lock; repeatable; default: not restricted")
    k.add_argument("--decision-hour-utc", type=int, metavar="H",
                   help="fixed decision hour (UTC) of the locked run; default: the moments as written in the files")
    k.add_argument("--check", action="store_true", help="verify the existing lock instead of writing one")
    k.add_argument("--force", action="store_true", help="overwrite an existing lock file")
    return p


def _lock_inputs(set_name: str, scenarios_dir=None, corpus=None, rater_guide=None, cache_snapshot=None,
                 analysis_plan=None):
    """Current hashes and prompt hash for the protocol lock (the protocol part; see lock.environment for the rest)."""
    from ..config import config_dir
    from ..pipeline.ai_chat import PROMPT_HASH as VC_PROMPT_HASH
    from ..pipeline.generate import FREE_PROMPT_HASH, PROMPT_HASH
    from ..pipeline.judge import JUDGE_PROMPT_HASH
    from ..retrieval.corpus import corpus_dir
    from . import lock
    from .scenarios import scenario_dir
    files = lock.collect(Path(scenarios_dir) if scenarios_dir else scenario_dir(set_name),
                         Path(corpus) if corpus else corpus_dir(), config_dir(),
                         Path(rater_guide) if rater_guide else lock.default_rater_guide(),
                         Path(cache_snapshot) if cache_snapshot else None,
                         Path(analysis_plan) if analysis_plan else None)
    files["prompt/vc_ai_chat"] = VC_PROMPT_HASH     # the LLM baseline VC (E5) is locked with its own prompt
    files["prompt/generator_free_act"] = FREE_PROMPT_HASH   # V0-V3: the generator prompt of the variants whose act the model chooses
    files["prompt/judge"] = JUDGE_PROMPT_HASH        # the entailment judge of gamma (used with GROUNDING_JUDGE=llm)
    return files, PROMPT_HASH


def _lock_environment():
    """The environment part of the lock: code, dependencies, interpreter, model settings, generator selection."""
    from . import lock
    from . import settings as st
    cfg = st.load()
    generator = "llm:%s" % cfg["llm"].get("provider") if st.llm_requested() else "template"
    return lock.environment(cfg, generator)


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
        diff = lock.differences(locked, files, prompt) + lock.environment_differences(locked, _lock_environment())
        print(json.dumps({"lock": str(out), "combined_sha256": locked["combined_sha256"], "differences": diff},
                         ensure_ascii=False, indent=2))
        return 1 if diff else 0
    if out.exists() and not args.force:
        print("lock: %s exists; use --check to verify or --force to replace it" % out, file=sys.stderr)
        return 2
    from .scenarios import PROTECTED_SETS
    if args.set in PROTECTED_SETS and not args.cache_snapshot:
        print("lock: refused, the %r set is locked only with --cache-snapshot (python -m smartagri.cache export)"
              % args.set, file=sys.stderr)
        return 2
    from . import settings as st
    problems = st.check(st.load(), need_model=st.llm_requested())
    if problems:
        print("lock: refused, " + "; ".join(problems), file=sys.stderr)
        return 2
    try:
        files, prompt = _lock_inputs(args.set, args.scenarios_dir, args.corpus_dir, args.rater_guide, args.cache_snapshot,
                                     args.analysis_plan)
    except FileNotFoundError as exc:
        print("lock: %s" % exc, file=sys.stderr)
        return 2
    env = _lock_environment()
    if env["code"]["dirty"]:
        print("lock: refused, uncommitted changes in " + ", ".join(env["code"]["dirty"]), file=sys.stderr)
        return 2
    try:
        run = lock.run_section(args.repeats, args.variant, args.decision_hour_utc)
    except ValueError as exc:
        print("lock: refused, %s" % exc, file=sys.stderr)
        return 2
    data = lock.make_lock(args.set, files, prompt, Path(args.cache_snapshot) if args.cache_snapshot else None, args.tag,
                          env=env, run=run)
    lock.write(data, out)
    print(json.dumps({"lock": str(out), "set": args.set, "files": len(files), "prompt_hash": prompt, "run": run,
                      "protocol_sha256": data["protocol_sha256"], "combined_sha256": data["combined_sha256"],
                      "commit": env["code"]["commit"], "src_sha256": env["code"]["src_sha256"]}, indent=2))
    print("lock: written; tag the commit with `git tag %s` once the human has approved it" % args.tag, file=sys.stderr)
    return 0


def protected_folder(folder) -> Optional[str]:
    """The protected set a scenarios folder belongs to: the set's own folder (or one inside it), or a folder holding a
    byte-identical copy of any of its files. None for an unprotected folder."""
    from . import lock
    from .scenarios import PROTECTED_SETS, scenario_dir
    if not folder:
        return None
    f = Path(folder).resolve()
    for name in PROTECTED_SETS:
        try:
            home = scenario_dir(name).resolve()
        except ValueError:                      # a retrospective set whose folder is not configured has no home to compare
            continue
        if f == home or home in f.parents:
            return name
        if home.is_dir() and f.is_dir():
            protected = {lock.sha256_file(p) for p in home.rglob("*") if p.is_file()}
            if any(lock.sha256_file(p) in protected for p in f.rglob("*") if p.is_file()):
                return name
    return None


def check_run_allowed(args) -> int:
    """0 when `run` may proceed. A protected set needs --locked and a lock that matches the files, the environment and
    the run section (repeats, variants). The lock is the repository's own lock, or a file whose sha256 the operator
    states with --lock-sha256 (an arbitrary lock written to an arbitrary path is refused). On success `args.lock_info`
    holds the lock's identity, which every item of the run records. A --scenarios-dir that holds protected scenarios
    counts as that protected set, whatever --set says."""
    args.lock_info = None
    from . import lock
    from .scenarios import PROTECTED_SETS
    owner = protected_folder(getattr(args, "scenarios_dir", None))
    if owner is not None and args.set != owner:
        print("run: refused, %s holds scenarios of the protected %r set; run them only as --set %s --locked"
              % (args.scenarios_dir, owner, owner), file=sys.stderr)
        return 2
    if args.set not in PROTECTED_SETS and not args.locked:
        return 0
    if not args.locked:
        print("run: refused, the %r set runs only under the locked protocol (pass --locked; see `evalkit lock`)" % args.set,
              file=sys.stderr)
        return 2
    path = Path(args.lock_file) if args.lock_file else lock.default_lock_path()
    if not path.is_file():
        print("run: refused, no protocol lock at %s" % path, file=sys.stderr)
        return 2
    sha = lock.lock_sha256(path)
    if path.resolve() != lock.default_lock_path().resolve():
        stated = (getattr(args, "lock_sha256", None) or "").strip().lower()
        if not stated:
            print("run: refused, %s is not the repository's lock (%s); state its sha256 with --lock-sha256"
                  % (path, lock.default_lock_path()), file=sys.stderr)
            return 2
        if stated != sha:
            print("run: refused, the sha256 of %s (%s) does not match --lock-sha256 (%s)" % (path, sha, stated),
                  file=sys.stderr)
            return 2
    locked = lock.read(path)
    try:
        files, prompt = _lock_inputs(args.set, args.scenarios_dir, None, None, locked.get("cache_snapshot"))
    except FileNotFoundError as exc:
        print("run: refused, %s" % exc, file=sys.stderr)
        return 2
    from ..config import load_variants
    names = args.variant or sorted(load_variants())
    diff = lock.differences(locked, files, prompt, args.set) + lock.environment_differences(locked, _lock_environment()) \
        + lock.run_differences(locked, args.repeats, names, getattr(args, "decision_hour_utc", None))
    if diff:
        print("run: refused, the files differ from the protocol lock:\n  " + "\n  ".join(diff), file=sys.stderr)
        return 2
    args.lock_info = {"lock_sha256": sha, "lock_combined_sha256": locked.get("combined_sha256"),
                      "lock_tag": locked.get("tag")}
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
        from . import settings as st
        from ..llm.base import ModelCallError
        ladder = [n for n in names if n not in vc.EXTERNAL_VARIANTS]
        problems = st.check(st.load(), need_model=bool(ladder) and st.llm_requested())
        if problems:
            print("run: refused, " + "; ".join(problems), file=sys.stderr)
            return 2
        if any(n in vc.EXTERNAL_VARIANTS for n in names):
            try:
                vc.provider_or_refuse()
            except vc.Unavailable as exc:
                print("run: refused, %s" % exc, file=sys.stderr)
                return 2
        failed = 0
        for name in names:
            try:
                res = run_batch(store, args.set, name, args.repeats, Path(args.scenarios_dir) if args.scenarios_dir else None,
                                lock_info=getattr(args, "lock_info", None), decision_hour_utc=args.decision_hour_utc)
            except (ModelCallError, vc.Unavailable) as exc:
                print("run: failed, %s" % exc, file=sys.stderr)
                return 2
            failed += int(res.get("failed") or 0)
            print(json.dumps(res, ensure_ascii=False))
            if res.get("label"):
                print("run: variant %s was produced by the template generator (%s): a fallback that always recommends, "
                      "not a result of that rung; reports show it under this label" % (name, res["label"]), file=sys.stderr)
        if failed:
            # Error items are stored and excluded from every measure; the run as a whole is not usable as is.
            print("run: %d item(s) failed (stored as errors, not rateable); the run exits non-zero" % failed, file=sys.stderr)
            return 1
        return 0

    if args.cmd == "assign":
        from . import rating
        try:
            data = rating.assign(store, args.rater, args.set, args.batch, args.variant, args.seed, write=not args.dry_run,
                                 repeat=args.repeat, pick_repeat=args.pick_repeat, per_stratum=args.per_stratum)
        except ValueError as exc:
            print("assign: refused, %s" % exc, file=sys.stderr)
            return 2
        shown = dict({k: v for k, v in data.items() if k != "items"}, n=len(data["items"]))
        print(json.dumps(shown, ensure_ascii=False, indent=2))
        return 0 if data["items"] else 1

    from . import report as rep
    try:
        items = rep.select(store.list_eval_items(), getattr(args, "set", None), getattr(args, "batch", None))
    except ValueError as exc:
        print("%s: refused, %s" % (args.cmd, exc), file=sys.stderr)
        return 2
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
            out["agreement"] = rep.agreement(store, args.agreement[0], args.agreement[1], items)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    if args.citation_sample is not None:
        from .citations import sample
        data = json.dumps(sample(items, args.citation_sample, args.seed), ensure_ascii=False, indent=2)
    else:
        ids = {i["id"] for i in items}
        data = json.dumps({"items": items, "ratings": [r for r in store.list_ratings() if r["item_id"] in ids]},
                          ensure_ascii=False, indent=2)
    if args.out == "-":
        sys.stdout.write(data + "\n")
    else:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
