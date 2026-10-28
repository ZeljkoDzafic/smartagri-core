from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx

from .base import Image, LLMError, LLMResponse, Provider, schema_instruction

# provider -> (base URL, API-key variable, default model). The model can always be set with LLM_MODEL.
PRESETS = {
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY", "gpt-4o-mini"),
    "deepseek": ("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY", "deepseek-chat"),
    "kimi": ("https://api.moonshot.ai/v1", "MOONSHOT_API_KEY", "moonshot-v1-32k"),
    "mistral": ("https://api.mistral.ai/v1", "MISTRAL_API_KEY", "mistral-small-latest"),
    "ollama": ("http://localhost:11434/v1", None, "llama3.1:8b"),
    "lmstudio": ("http://localhost:1234/v1", None, "local-model"),
    "openai-compatible": (None, "LLM_API_KEY", None),
}
# Providers known to accept response_format={"type": "json_schema"}; the others get json_object + instruction.
NATIVE_SCHEMA = {"openai"}


class OpenAICompatProvider(Provider):
    """Any server that speaks the OpenAI chat-completions protocol."""

    def __init__(self, name: str, base_url: Optional[str] = None, model: Optional[str] = None,
                 api_key: Optional[str] = None, transport=None, timeout: float = 120.0):
        if name not in PRESETS:
            raise ValueError("unknown provider %s" % name)
        default_base, key_var, default_model = PRESETS[name]
        self.name = name
        self.base_url = (base_url or os.environ.get("LLM_BASE_URL") or default_base or "").rstrip("/")
        self.model = model or os.environ.get("LLM_MODEL") or default_model
        self.api_key = api_key or (os.environ.get(key_var) if key_var else None) or os.environ.get("LLM_API_KEY")
        if not self.base_url or not self.model:
            raise LLMError("%s: set LLM_BASE_URL and LLM_MODEL" % name)
        if key_var and not self.api_key and name not in ("ollama", "lmstudio"):
            raise LLMError("%s: missing API key (%s)" % (name, key_var))
        self._client = httpx.Client(timeout=timeout, transport=transport)
        # Image input only for models listed in product_config/photo.yaml `vision_models` (never guessed).
        self.supports_images = self.model in vision_models()

    def complete(self, system, messages, json_schema=None, max_tokens=4000) -> LLMResponse:
        body: Dict[str, Any] = {"model": self.model, "max_tokens": max_tokens,
                                "messages": [{"role": "system", "content": system + (
                                    schema_instruction(json_schema) if json_schema and self.name not in NATIVE_SCHEMA else "")}]
                                + list(messages)}
        if json_schema:
            body["response_format"] = ({"type": "json_schema", "json_schema": {"name": "answer", "schema": json_schema,
                                                                               "strict": True}}
                                       if self.name in NATIVE_SCHEMA else {"type": "json_object"})
        headers = {"Authorization": "Bearer " + self.api_key} if self.api_key else {}
        try:
            r = self._client.post(self.base_url + "/chat/completions", json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise LLMError("%s: %s" % (self.name, exc.__class__.__name__))
        if r.status_code >= 400:
            raise LLMError("%s: HTTP %d" % (self.name, r.status_code))
        data = r.json()
        try:
            choice = data["choices"][0]
            text = choice["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise LLMError("%s: unexpected response" % self.name)
        if choice.get("finish_reason") not in (None, "stop"):
            raise LLMError("%s: finish_reason=%s" % (self.name, choice.get("finish_reason")))
        usage = data.get("usage") or {}
        return LLMResponse(text, self.name, data.get("model", self.model), usage.get("prompt_tokens", 0),
                           usage.get("completion_tokens", 0), None, "end_turn", request_id=data.get("id"))

    # ------------------------------------------------------------ image input
    def complete_with_images(self, system, messages, images, json_schema=None, max_tokens=1500) -> LLMResponse:
        """`image_url` parts with base64 data URLs before the text of the last user message (chat-completions
        vision input). Only for a model listed in `vision_models`; otherwise LLMError (graceful degradation)."""
        if not self.supports_images:
            raise LLMError("%s: model %s is not listed as a vision model" % (self.name, self.model))
        msgs = [dict(m) for m in messages]
        last = msgs[-1]
        parts: List[Dict[str, Any]] = [{"type": "image_url", "image_url": {
            "url": "data:%s;base64,%s" % (im.media_type, im.base64())}} for im in images]
        msgs[-1] = {"role": last["role"], "content": parts + [{"type": "text", "text": last["content"]}]}
        return self.complete(system, msgs, json_schema=json_schema, max_tokens=max_tokens)


def vision_models() -> List[str]:
    try:
        from ..product_config import load
        return [str(m) for m in (load("photo").get("vision_models") or [])]
    except Exception:                                   # no product_config directory (library use): none listed
        return []


__all__ = ["Image", "OpenAICompatProvider", "PRESETS", "vision_models"]
