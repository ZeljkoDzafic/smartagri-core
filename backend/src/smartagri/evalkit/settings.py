"""Language-model settings of an evaluation run (config/evaluation.yaml) and the checks evalkit applies to them.

An evaluation run never changes model silently: the model is an exact id from the config, the environment must agree
with it, there is no server-side fallback, and every failed call is an error item (see evalkit.runner, evalkit.vc).
Reading files only; nothing here calls a model.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from .. import config

# Names that select a moving target rather than one model version.
ALIASES = {"sonnet", "opus", "haiku", "fable", "default", "best", "latest", "auto"}


class SettingsError(ValueError):
    """The evaluation settings or the environment do not allow a reproducible run."""


def load() -> Dict[str, Any]:
    data = config.load("evaluation") or {}
    llm, judge = dict(data.get("llm") or {}), dict(data.get("judge") or {})
    return {"llm": llm, "judge": judge}


def is_exact_model_id(model: Optional[str]) -> bool:
    """False for an empty name, an alias (`sonnet`) or a floating tag (`...-latest`, `...:latest`)."""
    if not model or not str(model).strip():
        return False
    m = str(model).strip().lower()
    return m not in ALIASES and not re.search(r"[-:@]latest$", m)


def llm_requested() -> bool:
    """Does the environment ask for a language model in the ladder? Same rule as pipeline.generate.make_generator:
    ADVICE_GENERATOR=llm, or ADVICE_GENERATOR unset with LLM_PROVIDER=anthropic."""
    mode = os.environ.get("ADVICE_GENERATOR", "")
    name = os.environ.get("LLM_PROVIDER", "template").strip().lower()
    return mode == "llm" or (mode != "template" and name == "anthropic")


def check(settings: Dict[str, Any], need_model: bool) -> List[str]:
    """Problems that make a run with a model irreproducible; empty = allowed. need_model: the run calls a model."""
    if not need_model:
        return []
    out = []
    llm = settings["llm"]
    provider, model = llm.get("provider"), llm.get("model")
    if not provider:
        out.append("config/evaluation.yaml: llm.provider is not set")
    if not is_exact_model_id(model):
        out.append("config/evaluation.yaml: llm.model %r is not an exact model id" % model)
    env_provider = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if env_provider and env_provider not in ("template", "none") and provider and env_provider != provider:
        out.append("LLM_PROVIDER=%s differs from config/evaluation.yaml llm.provider=%s" % (env_provider, provider))
    env_model = os.environ.get("LLM_MODEL", "").strip()
    if env_model and model and env_model != model:
        out.append("LLM_MODEL=%s differs from config/evaluation.yaml llm.model=%s" % (env_model, model))
    if llm.get("server_fallback", False):
        out.append("config/evaluation.yaml: llm.server_fallback must be false for an evaluation run")
    if os.environ.get("GROUNDING_JUDGE", "lexical") == "llm" and not is_exact_model_id(settings["judge"].get("model")):
        out.append("config/evaluation.yaml: judge.model %r is not an exact model id" % settings["judge"].get("model"))
    env_judge = os.environ.get("JUDGE_MODEL", "").strip()
    if env_judge and env_judge != settings["judge"].get("model"):
        out.append("JUDGE_MODEL=%s differs from config/evaluation.yaml judge.model=%s" % (env_judge, settings["judge"].get("model")))
    return out


def summary(settings: Dict[str, Any], generator_name: str) -> Dict[str, Any]:
    """What every item of a run records about how its text was produced."""
    llm = settings["llm"]
    uses_model = generator_name != "template"
    return {"generator": generator_name, "provider": llm.get("provider") if uses_model else None,
            "model": llm.get("model") if uses_model else None, "effort": llm.get("effort") if uses_model else None,
            "max_tokens": llm.get("max_tokens_generator") if uses_model else None,
            "server_fallback": bool(llm.get("server_fallback", False)) if uses_model else None,
            "grounding_judge": os.environ.get("GROUNDING_JUDGE", "lexical"),
            "judge_model": settings["judge"].get("model") if os.environ.get("GROUNDING_JUDGE") == "llm" else None}
