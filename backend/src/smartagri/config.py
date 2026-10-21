"""Load YAML configuration and expose content hashes for provenance."""
from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

import yaml

CONFIG_FILES = ("thresholds", "requirements", "variants", "asking", "kc_maize", "rules")


def config_dir() -> Path:
    env = os.environ.get("SMARTAGRI_CONFIG_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "config"


@lru_cache(maxsize=None)
def load(name: str) -> Dict[str, Any]:
    path = config_dir() / (name + ".yaml")
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


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
        variant = VariantConfig(name=k, **v)
        for f, value in flags.items():
            setattr(variant, f, value)
        out[k] = variant
    return out
