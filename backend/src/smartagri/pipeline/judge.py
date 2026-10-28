"""LLM entailment judge for the support part of gamma.

`ClaudeJudge(sentence, source)` asks Claude whether `source` supports `sentence` and returns a
score in [0, 1], or None when no usable verdict came back (API error, refusal, max_tokens,
unparseable output); `core.grounding.support_check` then uses the lexical score for that pair.
Enabled with GROUNDING_JUDGE=llm (default: lexical); the model comes from JUDGE_MODEL.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Dict, Optional, Tuple

JUDGE_PROMPT = """You check whether a source text supports a sentence from an agronomic answer.

The sentence is supported when everything it states follows from the source: the same facts,
numbers, conditions and recommendations. It is not supported when it adds a fact, a number, a cause,
a product, a dose or a recommendation the source does not contain, or when it contradicts the source.
Paraphrase and translation are fine. Judge only against the source, not against your own knowledge.

Return "supported" (true or false) and "score", a number from 0 to 1 giving how fully the source
supports the sentence (1 = fully, 0 = not at all)."""

# Numeric bounds (0..1) are stated in the prompt and enforced by clamping: structured outputs do not
# accept minimum/maximum.
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {"supported": {"type": "boolean"}, "score": {"type": "number"}},
    "required": ["supported", "score"],
    "additionalProperties": False,
}
JUDGE_PROMPT_HASH = hashlib.sha256((JUDGE_PROMPT + json.dumps(JUDGE_SCHEMA, sort_keys=True)).encode("utf-8")).hexdigest()


class ClaudeJudge:
    """Callable judge(sentence, source) -> Optional[float]. Requires the `anthropic` package."""
    prompt_hash = JUDGE_PROMPT_HASH

    def __init__(self, client=None, model: Optional[str] = None, strict: bool = False, server_fallback: bool = True):
        import anthropic                      # imported lazily so the package stays optional
        self._anthropic = anthropic
        self.client = client if client is not None else anthropic.Anthropic()
        self.model = model or os.environ.get("JUDGE_MODEL", "claude-opus-5-5")
        # strict (evaluation): a call without a verdict raises instead of being scored lexically, and no
        # server-side fallback model is allowed.
        self.strict, self.server_fallback = strict, server_fallback
        self.calls = []                       # [{model, request_id}] per request, for the provenance
        self.usage = {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0}
        self.fallbacks = 0                    # pairs scored lexically because the judge gave no verdict
        self._cache: Dict[Tuple[str, str], Optional[float]] = {}

    def __call__(self, sentence: str, source: str) -> Optional[float]:
        key = (sentence, source)
        if key not in self._cache:
            self._cache[key] = self._ask(sentence, source)
            if self._cache[key] is None:
                self.fallbacks += 1
        return self._cache[key]

    def _ask(self, sentence: str, source: str) -> Optional[float]:
        score = self._verdict(sentence, source)
        if score is None and getattr(self, "strict", False):
            from ..llm.base import ModelCallError
            raise ModelCallError("judge: no verdict from %s" % self.model)
        return score

    def _verdict(self, sentence: str, source: str) -> Optional[float]:
        kwargs = dict(model=self.model, max_tokens=1024, system=JUDGE_PROMPT,
                      output_config={"effort": "low", "format": {"type": "json_schema", "schema": JUDGE_SCHEMA}},
                      messages=[{"role": "user", "content": json.dumps({"source": source, "sentence": sentence},
                                                                       ensure_ascii=False)}])
        if getattr(self, "server_fallback", True):
            kwargs.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        try:
            response = self.client.beta.messages.create(**kwargs)
        except self._anthropic.APIError:
            return None
        usage = getattr(response, "usage", None)
        if usage is not None:
            self.usage["llm_calls"] += 1
            self.usage["input_tokens"] += usage.input_tokens
            self.usage["output_tokens"] += usage.output_tokens
        actual = getattr(response, "model", None)
        if hasattr(self, "calls"):
            self.calls.append({"model": actual, "request_id": getattr(response, "_request_id", None)})
        if getattr(self, "strict", False) and isinstance(actual, str) and actual != self.model:
            return None                               # another model answered: no verdict (strict raises)
        if response.stop_reason != "end_turn":      # refusal, max_tokens: no verdict
            return None
        try:
            out = json.loads(next(b.text for b in response.content if b.type == "text"))
            score = float(out["score"])
        except (StopIteration, ValueError, KeyError, TypeError):
            return None
        return min(1.0, max(0.0, score))


def make_judge(strict: bool = False, server_fallback: bool = True, model: Optional[str] = None):
    """GROUNDING_JUDGE=llm returns a ClaudeJudge; anything else returns None = lexical. A missing SDK or credentials
    give the lexical check interactively, and ModelCallError in strict (evaluation) mode."""
    if os.environ.get("GROUNDING_JUDGE", "lexical") != "llm":
        return None
    try:
        return ClaudeJudge(model=model, strict=strict, server_fallback=server_fallback)
    except Exception as exc:                  # missing package or credentials
        if strict:
            from ..llm.base import ModelCallError
            raise ModelCallError("judge unavailable: %s" % exc.__class__.__name__)
        return None
