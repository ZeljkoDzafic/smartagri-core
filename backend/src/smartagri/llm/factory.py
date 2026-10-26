from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, Optional, Tuple

from .base import LLMError, Provider

NONE = ("", "none", "template")


def make_provider(name: Optional[str] = None, model: Optional[str] = None, server_fallback: bool = True,
                  effort: Optional[str] = None) -> Optional[Provider]:
    """Provider from LLM_PROVIDER; None for the template (no model). Raises LLMError when misconfigured.

    model / server_fallback / effort: set by an evaluation run from config/evaluation.yaml (exact model id, no
    server-side fallback); interactive use keeps the environment's settings."""
    name = (name if name is not None else os.environ.get("LLM_PROVIDER", "template")).strip().lower()
    if name in NONE:
        return None
    if name == "anthropic":
        try:
            from .anthropic_provider import AnthropicProvider
            return AnthropicProvider(model=model, server_fallback=server_fallback, effort=effort)
        except ImportError:
            raise LLMError("anthropic: package not installed (pip install anthropic)")
    if name == "claude-cli":
        from .claude_cli import ClaudeCliProvider
        return ClaudeCliProvider(model=model)
    if name == "bridge":
        from .bridge import BridgeProvider
        return BridgeProvider()
    from .openai_compat import PRESETS, OpenAICompatProvider
    if name in PRESETS:
        return OpenAICompatProvider(name, model=model)
    raise LLMError("unknown LLM_PROVIDER %r" % name)


# Reachability of the host bridge (LLM_PROVIDER=bridge), cached so /api/llm stays cheap: one GET /health with a short
# timeout at most every BRIDGE_CHECK_TTL seconds per (url, token). Other providers are not probed (no network call).
BRIDGE_CHECK_TTL = 30.0
BRIDGE_CHECK_TIMEOUT = 2.0
BRIDGE_DOWN = "AI razgovor trenutno nije dostupan: veza sa AI posrednikom (bridge) nije uspostavljena."
_bridge_cache: Dict[Tuple[str, str], Tuple[float, bool]] = {}
_bridge_lock = threading.Lock()


def bridge_reachable(url: Optional[str] = None, token: Optional[str] = None, transport=None,
                     now: Optional[float] = None) -> bool:
    """True when the bridge answers GET /health with 200 (cached for BRIDGE_CHECK_TTL seconds)."""
    import httpx
    url = (url or os.environ.get("LLM_BRIDGE_URL", "") or "http://host.docker.internal:8765").rstrip("/")
    token = token if token is not None else os.environ.get("LLM_BRIDGE_TOKEN", "")
    key, now = (url, token), (time.monotonic() if now is None else now)
    with _bridge_lock:
        hit = _bridge_cache.get(key)
        if hit and now - hit[0] < BRIDGE_CHECK_TTL:
            return hit[1]
    try:
        with httpx.Client(timeout=BRIDGE_CHECK_TIMEOUT, transport=transport) as client:
            r = client.get(url + "/health", headers={"Authorization": "Bearer " + token} if token else {})
        ok = r.status_code == 200
    except Exception:                                   # connection refused, DNS, timeout: unreachable
        ok = False
    with _bridge_lock:
        _bridge_cache[key] = (now, ok)
    return ok


def describe() -> Dict[str, Any]:
    """What /api/llm reports: is a model available, which one, and why not. For the bridge, availability also
    requires a reachable bridge (cached check), so the client does not offer a chat that would answer 503."""
    name = os.environ.get("LLM_PROVIDER", "template")
    if name.strip().lower() == "bridge" and not bridge_reachable():
        return {"available": False, "provider": "bridge", "model": "", "message": BRIDGE_DOWN, "images": False}
    try:
        p = make_provider(name)
    except LLMError as exc:
        return {"available": False, "provider": name, "model": "", "message": "AI razgovor nije podešen: %s." % exc,
                "images": False}
    if p is None:
        return {"available": False, "provider": "none", "model": "",
                "message": "AI razgovor nije podešen. Podesite LLM_PROVIDER (claude-cli, anthropic, openai, deepseek, "
                           "kimi, mistral, ollama, lmstudio ili openai-compatible).", "images": False}
    # Spec 023: whether the provider accepts image input (photo descriptions); additive key.
    return {"available": True, "provider": p.name, "model": p.model, "message": "",
            "images": bool(getattr(p, "supports_images", False))}
