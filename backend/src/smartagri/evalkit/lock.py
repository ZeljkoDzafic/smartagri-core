"""Protocol lock (spec 007 FR-011, US7): sha256 of everything a test-set run depends on.

The lock file (default `backend/eval/protocol-lock.json`) has two parts:

- `files` (the protocol): every file of the locked scenario set, the corpus, the config files (thresholds,
  requirements, variants, evaluation, analysis, ...), the rater guide, the analysis plan (docs/protocol.md), the
  prompt hashes (generator, VC, judge) and the external-cache snapshot (mandatory for a protected set);
- `environment` (what runs the protocol): git commit and dirty paths, sha256 over the source tree `src/smartagri`,
  sha256 of requirements.lock, the Python version, the model settings of config/evaluation.yaml, the generator the
  environment selects (ADVICE_GENERATOR, LLM_PROVIDER, LLM_MODEL, LLM_EFFORT), the embedding settings and the
  grounding judge.

`combined_sha256` covers both. A run on a protected set (`run --set test --locked`) recomputes them and refuses on any
difference, except the git commit itself (committing the lock file moves HEAD; the source hash binds the code).

Reading files only; nothing here imports the decision model. The prompt hashes are passed in by the
caller so the lock module stays importable without the pipeline.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

FORMAT = "smartagri-protocol-lock/2"
FORMATS_READ = ("smartagri-protocol-lock/1", FORMAT)
BACKEND = Path(__file__).resolve().parents[3]
REPO = BACKEND.parent
SRC = Path(__file__).resolve().parents[1]                 # backend/src/smartagri
# Environment variables that select or shape what a run produces (recorded; compared by run --locked).
ENV_KEYS = ("ADVICE_GENERATOR", "LLM_PROVIDER", "LLM_MODEL", "LLM_EFFORT", "EMBEDDINGS_PROVIDER", "EMBEDDINGS_MODEL",
            "GROUNDING_JUDGE", "JUDGE_MODEL", "SMARTAGRI_LOCALE")
# Paths whose uncommitted changes make a locked run refuse (git checkouts only).
GUARDED_PATHS = ("backend/src", "backend/config", "backend/corpus", "backend/requirements.lock", "docs/RATER_GUIDE.md",
                 "docs/protocol.md")


def default_lock_path() -> Path:
    return BACKEND / "eval" / "protocol-lock.json"


def default_rater_guide() -> Path:
    return REPO / "docs" / "RATER_GUIDE.md"


def default_analysis_plan() -> Path:
    return REPO / "docs" / "protocol.md"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def _tree(prefix: str, folder: Path) -> Dict[str, str]:
    """Hashes of every regular, non-hidden file under folder, keyed by prefix/relative path."""
    out = {}
    for p in sorted(folder.rglob("*")):
        rel = p.relative_to(folder)
        if p.is_file() and not any(part.startswith(".") for part in rel.parts) and "__pycache__" not in rel.parts:
            out["%s/%s" % (prefix, rel.as_posix())] = sha256_file(p)
    return out


def collect(scenarios_dir: Path, corpus_dir: Path, config_dir: Path, rater_guide: Path,
            cache_snapshot: Optional[Path] = None, analysis_plan: Optional[Path] = None) -> Dict[str, str]:
    """{label: sha256} for every locked file. Raises FileNotFoundError when a required part is missing."""
    for label, path in (("scenario set", scenarios_dir), ("corpus", corpus_dir), ("config", config_dir)):
        if not path.is_dir():
            raise FileNotFoundError("%s folder not found: %s" % (label, path))
    if not rater_guide.is_file():
        raise FileNotFoundError("rater guide not found: %s" % rater_guide)
    files = _tree("scenarios", scenarios_dir)
    if not any(k.endswith(".yaml") for k in files):
        raise FileNotFoundError("no scenario files in %s" % scenarios_dir)
    files.update(_tree("corpus", corpus_dir))
    files.update({"config/" + p.name: sha256_file(p) for p in sorted(config_dir.glob("*.yaml"))})
    files["rater_guide/" + rater_guide.name] = sha256_file(rater_guide)
    plan = analysis_plan if analysis_plan is not None else default_analysis_plan()
    if not plan.is_file():
        raise FileNotFoundError("analysis plan not found: %s" % plan)
    files["analysis_plan/" + plan.name] = sha256_file(plan)
    if cache_snapshot is not None:
        if not cache_snapshot.is_file():
            raise FileNotFoundError("cache snapshot not found: %s" % cache_snapshot)
        files["cache_snapshot/" + cache_snapshot.name] = sha256_file(cache_snapshot)
    return files


def combined(files: Dict[str, str], prompt_hash: str, environment: Optional[Dict[str, Any]] = None) -> str:
    """One hash over all parts, as a short protocol fingerprint. Without `environment` it is the protocol
    fingerprint pinned in the tests (files and prompt only)."""
    lines = ["%s %s" % (k, files[k]) for k in sorted(files)] + ["prompt %s" % prompt_hash]
    if environment is not None:
        lines.append("environment %s" % json.dumps(comparable(environment), sort_keys=True, ensure_ascii=False))
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def tree_sha256(folder: Path) -> str:
    """One sha256 over every source file under folder (relative path + content hash), without caches."""
    lines = []
    for p in sorted(folder.rglob("*")):
        rel = p.relative_to(folder)
        if p.is_file() and "__pycache__" not in rel.parts and p.suffix not in (".pyc", ".pyo") \
                and not any(part.startswith(".") for part in rel.parts):
            lines.append("%s %s" % (rel.as_posix(), sha256_file(p)))
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _git(*args: str) -> Optional[str]:
    try:
        out = subprocess.run(["git", "-C", str(REPO)] + list(args), capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def git_state() -> Dict[str, Any]:
    """HEAD and the guarded paths with uncommitted changes; {"git": False} outside a git checkout."""
    head = _git("rev-parse", "HEAD")
    if head is None:
        return {"git": False, "commit": None, "dirty": []}
    status = _git("status", "--porcelain", "--untracked-files=no", "--", *GUARDED_PATHS) or ""
    return {"git": True, "commit": head, "dirty": sorted(line[3:] for line in status.splitlines() if line.strip())}


def environment(settings: Dict[str, Any], generator: Optional[str] = None,
                requirements: Optional[Path] = None) -> Dict[str, Any]:
    """What runs the protocol: code, dependencies, interpreter, model settings and environment variables."""
    req = requirements if requirements is not None else BACKEND / "requirements.lock"
    return {"code": dict(git_state(), src_sha256=tree_sha256(SRC)),
            "requirements_lock_sha256": sha256_file(req) if req.is_file() else None,
            "python": platform.python_version(),
            "generator": generator,
            "model_settings": settings,
            "env": {k: os.environ.get(k) for k in ENV_KEYS}}


def comparable(env: Dict[str, Any]) -> Dict[str, Any]:
    """The part of `environment` a locked run must reproduce: everything except the commit and the dirty list."""
    out = json.loads(json.dumps(env, sort_keys=True))
    code = out.get("code") or {}
    for k in ("commit", "dirty", "git"):
        code.pop(k, None)
    return out


def make_lock(set_name: str, files: Dict[str, str], prompt_hash: str, cache_snapshot: Optional[Path] = None,
              tag: str = "protocol-v1", env: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out = {"format": FORMAT, "tag": tag, "set": set_name, "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
           "prompt_hash": prompt_hash, "cache_snapshot": str(cache_snapshot) if cache_snapshot else None,
           "files": files, "protocol_sha256": combined(files, prompt_hash)}
    if env is not None:
        out["environment"] = env
    out["combined_sha256"] = combined(files, prompt_hash, env)
    return out


def write(lock: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lock, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def read(path: Path) -> Dict[str, Any]:
    lock = json.loads(path.read_text(encoding="utf-8"))
    if lock.get("format") not in FORMATS_READ:
        raise ValueError("unknown lock format: %s" % lock.get("format"))
    return lock


def differences(lock: Dict[str, Any], files: Dict[str, str], prompt_hash: str, set_name: Optional[str] = None) -> List[str]:
    """Human-readable list of every difference between a lock and the current files; empty = locked state."""
    out = []
    if set_name is not None and lock.get("set") != set_name:
        out.append("lock is for set %r, not %r" % (lock.get("set"), set_name))
    locked = lock.get("files") or {}
    for k in sorted(set(locked) | set(files)):
        if k not in files:
            out.append("missing: " + k)
        elif k not in locked:
            out.append("not in lock: " + k)
        elif locked[k] != files[k]:
            out.append("changed: " + k)
    if lock.get("prompt_hash") != prompt_hash:
        out.append("changed: generator prompt")
    return out


def environment_differences(lock: Dict[str, Any], env: Dict[str, Any]) -> List[str]:
    """Differences between the locked environment and the current one (the commit itself is not compared)."""
    locked = lock.get("environment")
    if locked is None:
        return ["lock has no environment (format %s): re-lock with this version" % lock.get("format")]
    a, b = comparable(locked), comparable(env)
    out = []

    def walk(prefix, x, y):
        if isinstance(x, dict) and isinstance(y, dict):
            for k in sorted(set(x) | set(y)):
                walk(prefix + "/" + k if prefix else k, x.get(k), y.get(k))
        elif x != y:
            out.append("changed: environment %s (%r -> %r)" % (prefix, x, y))
    walk("", a, b)
    dirty = (env.get("code") or {}).get("dirty") or []
    if dirty:
        out.append("uncommitted changes in guarded paths: " + ", ".join(dirty))
    return out
