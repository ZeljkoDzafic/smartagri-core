from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class LLMError(Exception):
    """The provider could not produce an answer (network, refusal, bad output, missing credentials)."""


class ModelCallError(LLMError):
    """A configured model call failed, or was answered by another model, in a run that must not fall back
    (an evaluation run). The caller records an error item instead of an answer."""


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    usd: Optional[float] = None
    stop_reason: str = "end_turn"
    data: Optional[Dict[str, Any]] = None       # parsed JSON when a schema was requested
    raw: Dict[str, Any] = field(default_factory=dict)
    request_id: Optional[str] = None            # the provider's id of the request, when it reports one


@dataclass
class Image:
    """An image for `complete_with_images`: the bytes and their MIME type (always image/jpeg there)."""
    data: bytes
    media_type: str = "image/jpeg"

    def base64(self) -> str:
        import base64
        return base64.standard_b64encode(self.data).decode("ascii")


class Provider:
    name = "none"
    model = "none"

    def complete(self, system: str, messages: List[Dict[str, str]], json_schema: Optional[Dict[str, Any]] = None,
                 max_tokens: int = 4000) -> LLMResponse:
        raise NotImplementedError

    # Image input. Providers that can send images override both; every other provider (template,
    # claude-cli, bridge, OpenAI-compatible models not listed as vision models) degrades gracefully.
    supports_images = False

    def complete_with_images(self, system: str, messages: List[Dict[str, str]], images: List[Image],
                             json_schema: Optional[Dict[str, Any]] = None, max_tokens: int = 1500) -> LLMResponse:
        """Like `complete`, with `images` attached to the last user message (before its text)."""
        raise LLMError("images not supported by provider %s" % self.name)


def parse_json_object(text: str) -> Dict[str, Any]:
    """Parse a JSON object from model text, tolerating code fences or prose around it."""
    text = text.strip()
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except ValueError:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        start, end = text.find("{"), text.rfind("}")
        candidate = text[start:end + 1] if start >= 0 and end > start else ""
    try:
        value = json.loads(candidate)
    except ValueError:
        raise LLMError("unparseable model output")
    if not isinstance(value, dict):
        raise LLMError("model output is not a JSON object")
    return value


def schema_instruction(json_schema: Dict[str, Any]) -> str:
    """Instruction for providers without native structured output."""
    return ("\n\nAnswer ONLY with one JSON object that validates against this JSON Schema, with no text "
            "before or after it:\n" + json.dumps(json_schema, ensure_ascii=False))
