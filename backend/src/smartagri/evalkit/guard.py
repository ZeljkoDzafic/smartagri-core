"""Leakage guard: no scenario text may appear in the corpus (see docs/architecture.md).

Compares scenario text fields (question, notes, every string in `reference`, user replies) with
corpus passages by word n-gram overlap. Text is folded exactly as for retrieval
(`retrieval.search.fold`: lowercase, no diacritics, đ -> dj) and tokenised the same way (stop
words and one-character tokens dropped) but without stem truncation. A passage is flagged when it
shares at least `share` of a field's 8-grams or any 12-word span with it.

The guard only reads files. It never imports the decision model or the pipeline, so it is safe on
the locked test set.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import yaml

from ..retrieval.search import STOP, fold

N = 8
SPAN = 12
SHARE = 0.5


def words(text: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9]+", fold(text)) if t not in STOP and len(t) > 1]


def ngrams(tokens: Sequence[str], n: int) -> Set[Tuple[str, ...]]:
    return {tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def _strings(value: Any, path: str) -> Iterable[Tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _strings(v, "%s.%s" % (path, k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _strings(v, "%s[%d]" % (path, i))


SOURCE_KEYS = ("applicable_sources", "not_applicable_sources", "acceptable_question_inputs",
               "unacceptable_question_inputs", "correct_act_first_turn", "correct_act_final",
               "also_acceptable_first_turn", "also_acceptable_final")


def scenario_fields(sc: Dict[str, Any]) -> List[Tuple[str, str]]:
    """(field path, text) for every free-text field of a scenario."""
    out: List[Tuple[str, str]] = []
    for key in ("question", "note", "scenario_note", "notes"):
        if isinstance(sc.get(key), str):
            out.append((key, sc[key]))
    q = ((sc.get("context") or {}).get("Q") or {}).get("text")
    if isinstance(q, str) and q != sc.get("question"):
        out.append(("context.Q.text", q))
    ref = {k: v for k, v in (sc.get("reference") or {}).items() if k not in SOURCE_KEYS}   # ids, not text
    out += list(_strings(ref, "reference"))
    out += list(_strings(sc.get("user_replies") or {}, "user_replies"))
    return out


def check(scenarios: Sequence[Dict[str, Any]], passages: Sequence[Dict[str, Any]], n: int = N, span: int = SPAN,
          share: float = SHARE) -> Dict[str, Any]:
    """Return every (scenario field, passage) pair that overlaps; `hits` empty means clean."""
    corpus = []
    for p in passages:
        toks = words(p.get("text", ""))
        corpus.append((p["id"], ngrams(toks, n), ngrams(toks, span)))
    hits, n_fields, n_short = [], 0, 0
    for sc in scenarios:
        for path, text in scenario_fields(sc):
            toks = words(text)
            n_fields += 1
            grams = ngrams(toks, n)
            if not grams:
                n_short += 1                       # shorter than n words: nothing to compare
                continue
            spans = ngrams(toks, span)
            for pid, pgrams, pspans in corpus:
                shared = len(grams & pgrams) / float(len(grams))
                exact = bool(spans & pspans)
                if shared >= share or exact:
                    hits.append({"scenario": sc.get("id"), "field": path, "passage": pid,
                                 "shared_8gram_share": round(shared, 3), "exact_12_span": exact})
    return {"n_scenarios": len(scenarios), "n_fields": n_fields, "n_fields_shorter_than_n": n_short,
            "n_passages": len(passages), "n": n, "span": span, "share": share, "hits": hits}


def load_passages(corpus_dir: Path, extra: Optional[Sequence[Path]] = None) -> List[Dict[str, Any]]:
    """Raw passages of the corpus (and any extra passage files), without building a retriever."""
    out = list(yaml.safe_load((corpus_dir / "passages.yaml").read_text(encoding="utf-8")) or [])
    for path in extra or []:
        out += list(yaml.safe_load(path.read_text(encoding="utf-8")) or [])
    return out


def scenario_passages(scenarios: Sequence[Dict[str, Any]], prefix: str = "dev") -> List[Dict[str, Any]]:
    """Free-text fields of (development) scenarios as pseudo-passages, so test scenarios are compared
    with development material the same way as with the corpus."""
    return [{"id": "%s:%s:%s" % (prefix, sc.get("id"), path), "text": text}
            for sc in scenarios for path, text in scenario_fields(sc)]


PROTECTED_DIR = "backend/eval/scenarios/test"


def _ignored_by(gitignore: Path, rel: str) -> bool:
    """True when a line of .gitignore ignores `rel` (a folder path relative to the repository root).

    Handles the forms used in this repository: an anchored or unanchored folder path with or
    without a trailing slash, and a parent folder of it. Negations are honoured in order."""
    ignored = False
    for raw in gitignore.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        negate = line.startswith("!")
        pattern = line[1:] if negate else line
        pattern = pattern.strip("/")
        if not pattern or any(c in pattern for c in "*?["):
            continue
        hit = rel == pattern or rel.startswith(pattern + "/") or ("/" not in pattern and pattern in rel.split("/"))
        if hit:
            ignored = not negate
    return ignored


# Modules that load the corpus and build the index. Reporting tools in the same package (e.g.
# retrieval/coverage.py) read development scenarios on purpose and refuse protected sets themselves.
INDEX_MODULES = ("__init__.py", "corpus.py", "search.py", "embed.py", "ingest.py")

_trace: Optional[List[str]] = None
_hooked = False


def _audit(event: str, args: Tuple[Any, ...]) -> None:
    if _trace is not None and event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
        _trace.append(os.fsdecode(args[0]))


def traced_reads(fn: Callable[[], Any]) -> List[str]:
    """Every file path opened while fn() runs (Python audit hook; the hook stays idle otherwise)."""
    global _trace, _hooked
    if not _hooked:
        sys.addaudithook(_audit)
        _hooked = True
    _trace = []
    try:
        fn()
        return list(_trace)
    finally:
        _trace = None


def _build_index(corpus_dir: Path) -> None:
    from ..retrieval.corpus import load_corpus
    from ..retrieval.search import Retriever
    Retriever(load_corpus(corpus_dir).passages)          # BM25 index; dense vectors are built from the same passages


def isolation_checks(repo_root: Path, corpus_dir: Path, retrieval_src: Path, trace_index: bool = False) -> Dict[str, Any]:
    """Checks that the test set cannot reach the index.

    - `.gitignore` at the repository root ignores backend/eval/scenarios/test/ (when the file is
      absent, e.g. inside a container image, the check is reported as not verifiable);
    - the corpus folder is not the scenarios folder or inside it;
    - no index-building module of the retrieval package (INDEX_MODULES) mentions the scenarios folder;
    - with trace_index: loading the corpus and building the BM25 index opens no file under the
      scenarios folder (traced with an audit hook).
    Returns {"problems": [...], "notes": [...]}; problems make the guard fail."""
    problems, notes = [], []
    gitignore = repo_root / ".gitignore"
    if gitignore.is_file():
        if not _ignored_by(gitignore, PROTECTED_DIR):
            problems.append("%s is not ignored by %s" % (PROTECTED_DIR, gitignore))
    else:
        notes.append("no .gitignore at %s; git-ignore check not verifiable" % repo_root)
    scenarios_root = (repo_root / "backend" / "eval" / "scenarios").resolve()
    c = corpus_dir.resolve()
    if c == scenarios_root or scenarios_root in c.parents:
        problems.append("corpus folder %s is inside the scenarios folder" % corpus_dir)
    for path in sorted(retrieval_src.glob("*.py")):
        if path.name not in INDEX_MODULES:
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"scenarios|eval[/\\]", text):
            problems.append("%s refers to the evaluation scenarios" % path.name)
    if trace_index:
        try:
            opened = traced_reads(lambda: _build_index(corpus_dir))
        except Exception as exc:                 # e.g. a bare passages file without a manifest
            notes.append("index build not traced: %s" % exc)
        else:
            bad = sorted({p for p in opened if scenarios_root in Path(p).resolve().parents})
            problems += ["index build opened %s" % p for p in bad]
            notes.append("index build opened %d file(s), none under the scenarios folder" % len(opened) if not bad else "")
    return {"problems": problems, "notes": [n for n in notes if n]}
