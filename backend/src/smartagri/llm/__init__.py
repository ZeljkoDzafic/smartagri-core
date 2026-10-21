"""One interface over language-model providers.

    LLM_PROVIDER = claude-cli | bridge | anthropic | openai | deepseek | kimi | mistral | ollama | lmstudio
                   | openai-compatible | template (none)

Every provider answers `complete(system, messages, json_schema=None)` with an LLMResponse. Providers
that speak the OpenAI chat-completions protocol (OpenAI, DeepSeek, Kimi/Moonshot, Mistral, Ollama,
LM Studio, llama.cpp server, vLLM) share one implementation with a base-URL preset. Claude is reached
through the Anthropic SDK or through the locally installed Claude Code CLI; the bridge lets the API
container use the host's CLI.
"""
from .base import Image, LLMError, LLMResponse, Provider, parse_json_object
from .factory import describe, make_provider

__all__ = ["Image", "LLMError", "LLMResponse", "Provider", "parse_json_object", "make_provider", "describe"]
