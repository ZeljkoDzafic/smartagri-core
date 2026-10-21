from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .. import config
from ..core.types import Passage, PassageMeta, to_date


@dataclass
class Corpus:
    documents: Dict[str, Dict[str, Any]]
    passages: List[Passage]
    hash: str

    def passage(self, passage_id: str) -> Optional[Passage]:
        for p in self.passages:
            if p.id == passage_id:
                return p
        return None

    def document(self, passage: Passage) -> Dict[str, Any]:
        return self.documents.get(passage.document_id, {})


def corpus_dir() -> Path:
    env = os.environ.get("SMARTAGRI_CORPUS_DIR")
    return Path(env) if env else Path(__file__).resolve().parents[3] / "corpus"


def _vocab_errors(pid: str, meta: Dict[str, Any], vocab: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    for key, allowed in (("crop", "crops"), ("advice_types", "advice_types"), ("region_scope", "regions"),
                         ("soil_scope", "soil_textures")):
        values = meta.get(key)
        if values is None:
            continue
        if not isinstance(values, list) or not values:
            errors.append("%s: %s must be a non-empty list" % (pid, key))
            continue
        errors += ["%s: %s value '%s' is not in vocab.yaml" % (pid, key, v) for v in values if v not in vocab[allowed]]
    if meta.get("source_type") is not None and meta["source_type"] not in vocab["source_types"]:
        errors.append("%s: source_type '%s' is not in vocab.yaml" % (pid, meta["source_type"]))
    lo, hi = vocab["bbch_bounds"]["min"], vocab["bbch_bounds"]["max"]
    for key in ("bbch_min", "bbch_max"):
        v = meta.get(key)
        if v is not None and (not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi):
            errors.append("%s: %s must be an integer BBCH code %d-%d" % (pid, key, lo, hi))
    if isinstance(meta.get("bbch_min"), int) and isinstance(meta.get("bbch_max"), int) and meta["bbch_min"] > meta["bbch_max"]:
        errors.append("%s: bbch_min is greater than bbch_max" % pid)
    for key in ("irrigated", "rainfed", "requires_no_rain_3d", "claims_numeric"):
        if meta.get(key) is not None and not isinstance(meta[key], bool):
            errors.append("%s: %s must be true or false" % (pid, key))
    dates = {}
    for key in ("valid_from", "valid_until"):
        if meta.get(key) is not None:
            try:
                dates[key] = to_date(meta[key])
            except ValueError:
                errors.append("%s: %s is not an ISO date" % (pid, key))
    if len(dates) == 2 and dates["valid_from"] > dates["valid_until"]:
        errors.append("%s: valid_from is after valid_until" % pid)
    rec = meta.get("recommends")
    if rec is not None and not (isinstance(rec, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in rec.items())):
        errors.append("%s: recommends must map decision keys to string values" % pid)
    return errors


def validate_corpus(documents: Dict[str, Dict[str, Any]], raw_passages: List[Dict[str, Any]],
                    vocab: Optional[Dict[str, Any]] = None) -> List[str]:
    """Every vocabulary or structure violation in the manifest and the passages (empty list = valid)."""
    vocab = vocab or config.load("vocab")
    errors: List[str] = []
    for doc_id, d in documents.items():
        if d.get("source_type") not in vocab["source_types"]:
            errors.append("document %s: source_type '%s' is not in vocab.yaml" % (doc_id, d.get("source_type")))
        if d.get("language") is not None and d["language"] not in vocab["languages"]:
            errors.append("document %s: language '%s' is not in vocab.yaml" % (doc_id, d["language"]))
    known = set(PassageMeta.__dataclass_fields__)
    seen = set()
    for raw in raw_passages:
        pid = str(raw.get("id"))
        if pid in seen:
            errors.append("%s: duplicate passage id" % pid)
        seen.add(pid)
        if not str(raw.get("text") or "").strip():
            errors.append("%s: empty text" % pid)
        meta = raw.get("meta") or {}
        unknown = sorted(set(meta) - known)
        if unknown:
            errors.append("%s: unknown meta field(s) %s" % (pid, ", ".join(unknown)))
        errors += _vocab_errors(pid, meta, vocab)
    return errors


def passages_hash(passages: List[Passage]) -> str:
    """sha256 over the sorted JSON of [id, text, meta] of all passages (FR-003); manifest edits do not change it."""
    return hashlib.sha256(json.dumps([[p.id, p.text, p.meta.to_dict()] for p in passages],
                                     sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def load_corpus(path: Optional[Path] = None, validate: bool = True) -> Corpus:
    path = path or corpus_dir()
    manifest = yaml.safe_load((path / "manifest.yaml").read_text(encoding="utf-8"))
    raw = yaml.safe_load((path / "passages.yaml").read_text(encoding="utf-8")) or []
    documents = {d["id"]: d for d in manifest["documents"]}
    if validate:
        errors = validate_corpus(documents, raw)
        if errors:
            raise ValueError("Corpus metadata violates config/vocab.yaml:\n  " + "\n  ".join(errors))
    passages = [Passage.from_dict(p) for p in raw]
    unknown = sorted({p.document_id for p in passages} - set(documents))
    if unknown:
        raise ValueError("Passages refer to documents missing from the manifest: %s" % ", ".join(unknown))
    return Corpus(documents, passages, passages_hash(passages))
