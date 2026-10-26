from __future__ import annotations

import os
from typing import Any, Dict, Optional

from .base import LLMError, LLMResponse, Provider


class AnthropicProvider(Provider):
    """Claude through the Anthropic SDK (credentials from ANTHROPIC_API_KEY or an `ant auth login` profile)."""
    name = "anthropic"

    def __init__(self, model: Optional[str] = None, client=None, server_fallback: bool = True,
                 effort: Optional[str] = None):
        import anthropic
        self._anthropic = anthropic
        self.client = client or anthropic.Anthropic()
        self.model = model or os.environ.get("LLM_MODEL") or "claude-opus-5-5"
        # Interactive use keeps the server-side fallback; an evaluation run turns it off (config/evaluation.yaml).
        self.server_fallback = server_fallback
        self.effort = effort

    def complete(self, system, messages, json_schema=None, max_tokens=4000) -> LLMResponse:
        output_config: Dict[str, Any] = {"effort": self.effort or os.environ.get("LLM_EFFORT", "low")}
        if json_schema:
            output_config["format"] = {"type": "json_schema", "schema": json_schema}
        kwargs: Dict[str, Any] = dict(model=self.model, max_tokens=max_tokens, system=system, messages=messages,
                                      output_config=output_config)
        if self.server_fallback:
            # A server-side fallback re-runs the request on another model if a safety classifier declines it.
            kwargs.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        try:
            r = self.client.beta.messages.create(**kwargs)
        except self._anthropic.APIError as exc:
            raise LLMError("Anthropic: %s" % exc.__class__.__name__)
        if r.stop_reason != "end_turn":
            raise LLMError("Anthropic stop_reason=%s" % r.stop_reason)
        text = "".join(b.text for b in r.content if b.type == "text")
        return LLMResponse(text, self.name, r.model, r.usage.input_tokens, r.usage.output_tokens, None, r.stop_reason,
                           request_id=getattr(r, "_request_id", None))

    # ------------------------------------------------------------ spec 023: image input
    supports_images = True

    def complete_with_images(self, system, messages, images, json_schema=None, max_tokens=1500) -> LLMResponse:
        """Base64 image content blocks placed before the text of the last user message (Messages API vision input).
        The caller sends JPEGs at most SMARTAGRI_PHOTO_MAX_PX on the longer side (the API downscales larger ones)."""
        blocks = [{"type": "image", "source": {"type": "base64", "media_type": im.media_type, "data": im.base64()}}
                  for im in images]
        msgs = [dict(m) for m in messages]
        last = msgs[-1]
        msgs[-1] = {"role": last["role"], "content": blocks + [{"type": "text", "text": last["content"]}]}
        return self.complete(system, msgs, json_schema=json_schema, max_tokens=max_tokens)
