"""Load YAML configuration and expose content hashes for provenance."""
from __future__ import annotations

import contextlib
import contextvars
import copy
import hashlib
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

import yaml

CONFIG_FILES = ("thresholds", "requirements", "variants", "asking", "kc_maize", "rules", "parcel_features")

# Environment variables are named SMARTAGRI_<NAME>.


def env(name: str, default: str = "") -> str:
    """SMARTAGRI_<name>, else default."""
    value = os.environ.get("SMARTAGRI_" + name)
    return default if value is None or value == "" else value


def config_dir() -> Path:
    env = os.environ.get("SMARTAGRI_CONFIG_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "config"


@lru_cache(maxsize=None)
def load_file(name: str) -> Dict[str, Any]:
    """The configuration file as it is on disk (cached). Never affected by an overlay: evalkit, the protocol lock and
    the file hashes read the files through this view."""
    path = config_dir() / (name + ".yaml")
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# Per-request overlay of web settings (smartagri.web_settings). A context variable, so nothing global is mutated and a
# thread or task that never entered `use_overlay` sees the files unchanged. Only the research API sets it, once per
# request that computes an answer; evalkit, the CLI and the rating endpoints never do.
_OVERLAY: "contextvars.ContextVar[Optional[Overlay]]" = contextvars.ContextVar("smartagri_config_overlay", default=None)


class Overlay:
    """Values (dotted key -> value, e.g. "rules.irrigation.max_single_net_mm") merged over the file data of one request.

    `meta` is carried for provenance (hash, layer versions, snapshot) and is never read by the decision code. The merged
    dictionary of a file is built once per overlay (a deep copy of the file data with the overrides set); an overlay
    without values returns the cached file data itself."""

    def __init__(self, values: Optional[Dict[str, Any]] = None, meta: Optional[Dict[str, Any]] = None):
        self.values = dict(values or {})
        self.meta = dict(meta or {})
        self._merged: Dict[str, Dict[str, Any]] = {}

    def apply(self, name: str) -> Dict[str, Any]:
        base = load_file(name)
        prefix = name + "."
        mine = {k: v for k, v in self.values.items() if k.startswith(prefix)}
        if not mine:
            return base
        if name not in self._merged:
            data = copy.deepcopy(base)
            for key, value in sorted(mine.items()):
                *parents, leaf = key[len(prefix):].split(".")
                try:
                    node = data
                    for part in parents:
                        node = node[part]
                    if leaf in node:                    # a key the file no longer has is left out, never added
                        node[leaf] = copy.deepcopy(value)
                except (KeyError, TypeError):
                    continue
            self._merged[name] = data
        return self._merged[name]


def active_overlay() -> Optional[Overlay]:
    return _OVERLAY.get()


@contextlib.contextmanager
def use_overlay(overlay: Optional[Overlay]) -> Iterator[Optional[Overlay]]:
    """Make `overlay` the effective configuration of the code run inside the block (this thread or task only)."""
    token = _OVERLAY.set(overlay)
    try:
        yield overlay
    finally:
        _OVERLAY.reset(token)


def load(name: str) -> Dict[str, Any]:
    overlay = _OVERLAY.get()
    return load_file(name) if overlay is None else overlay.apply(name)


load.cache_clear = load_file.cache_clear  # type: ignore[attr-defined]   # callers that reset the cache keep working


def config_hashes() -> Dict[str, str]:
    """sha256 of every config file; stored with each decision so a run can be tied to its protocol."""
    out = {}
    for name in CONFIG_FILES:
        data = (config_dir() / (name + ".yaml")).read_bytes()
        out[name] = hashlib.sha256(data).hexdigest()
    return out


# Context-ablation flags (E4): which parts of the dynamic context C the system may see. They are not
# fields of VariantConfig (the core never reads them); pipeline.run applies them before deciding.
CONTEXT_FLAGS = {"use_weather": True, "use_satellite": True}


def load_variants():
    """VariantConfig per entry of variants.yaml; context flags are attached as plain attributes
    (`use_weather`, `use_satellite`, default True) so the core types stay unchanged."""
    from .core.types import VariantConfig

    out = {}
    for k, v in load("variants").items():
        v = dict(v)
        flags = {f: bool(v.pop(f, default)) for f, default in CONTEXT_FLAGS.items()}
        # YAML 1.1 reads a bare `off` / `none` as a boolean or null; the pi mode and the retrieval mode are strings.
        if v.get("applicability") in (False, None):
            v["applicability"] = "off"
        if v.get("retrieval") in (False, None):
            v["retrieval"] = "none"
        variant = VariantConfig(name=k, **v)
        for f, value in flags.items():
            setattr(variant, f, value)
        out[k] = variant
    return out
