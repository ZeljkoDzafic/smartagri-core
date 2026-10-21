"""Protocol lock (spec 007 FR-011, US7): sha256 of everything a test-set run depends on.

The lock file (default `backend/eval/protocol-lock.json`) records the hash of every file of the
locked scenario set, the corpus, the config files (thresholds, requirements, variants, ...), the
rater guide, the generator prompt hash and, when given, the external-cache snapshot. A run on a
protected set (`run --set test --locked`) recomputes the hashes and refuses on any difference.

Reading files only; nothing here imports the decision model. The prompt hash is passed in by the
caller so the lock module stays importable without the pipeline.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

FORMAT = "smartagri-protocol-lock/1"
BACKEND = Path(__file__).resolve().parents[3]
REPO = BACKEND.parent


def default_lock_path() -> Path:
    return BACKEND / "eval" / "protocol-lock.json"


def default_rater_guide() -> Path:
    return REPO / "docs" / "RATER_GUIDE.md"


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
            cache_snapshot: Optional[Path] = None) -> Dict[str, str]:
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
    if cache_snapshot is not None:
        if not cache_snapshot.is_file():
            raise FileNotFoundError("cache snapshot not found: %s" % cache_snapshot)
        files["cache_snapshot/" + cache_snapshot.name] = sha256_file(cache_snapshot)
    return files


def combined(files: Dict[str, str], prompt_hash: str) -> str:
    """One hash over all parts, as a short protocol fingerprint."""
    lines = ["%s %s" % (k, files[k]) for k in sorted(files)] + ["prompt %s" % prompt_hash]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def make_lock(set_name: str, files: Dict[str, str], prompt_hash: str, cache_snapshot: Optional[Path] = None,
              tag: str = "protocol-v1") -> Dict[str, Any]:
    return {"format": FORMAT, "tag": tag, "set": set_name, "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "prompt_hash": prompt_hash, "cache_snapshot": str(cache_snapshot) if cache_snapshot else None,
            "files": files, "combined_sha256": combined(files, prompt_hash)}


def write(lock: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lock, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def read(path: Path) -> Dict[str, Any]:
    lock = json.loads(path.read_text(encoding="utf-8"))
    if lock.get("format") != FORMAT:
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
