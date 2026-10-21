"""HTTP bridge: lets the API container use a provider that only exists on the host (the Claude CLI).

Host:       python -m smartagri.llm.bridge            (reads LLM_BRIDGE_TOKEN; provider from BRIDGE_PROVIDER, default claude-cli)
Container:  LLM_PROVIDER=bridge  LLM_BRIDGE_URL=http://host.docker.internal:8765  LLM_BRIDGE_TOKEN=<same token>
"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional

import httpx

from .base import LLMError, LLMResponse, Provider


class BridgeProvider(Provider):
    name = "bridge"
    # Spec 023: the bridge protocol (/complete) carries text messages only; photo descriptions are not available.
    supports_images = False

    def __init__(self, url: Optional[str] = None, token: Optional[str] = None, transport=None):
        self.url = (url or os.environ.get("LLM_BRIDGE_URL", "http://host.docker.internal:8765")).rstrip("/")
        self.token = token or os.environ.get("LLM_BRIDGE_TOKEN", "")
        self._client = httpx.Client(timeout=200.0, transport=transport)
        self.model = "bridge"
        try:
            info = self._client.get(self.url + "/health", headers=self._headers()).json()
            self.name, self.model = "bridge:" + info.get("provider", "?"), info.get("model", "?")
        except Exception:
            pass

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": "Bearer " + self.token} if self.token else {}

    def complete(self, system, messages, json_schema=None, max_tokens=4000) -> LLMResponse:
        try:
            r = self._client.post(self.url + "/complete", headers=self._headers(), json={
                "system": system, "messages": messages, "json_schema": json_schema, "max_tokens": max_tokens})
        except httpx.HTTPError as exc:
            raise LLMError("bridge: %s" % exc.__class__.__name__)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code != 200:
            raise LLMError("bridge: %s" % body.get("error", "HTTP %d" % r.status_code))
        return LLMResponse(**{k: body.get(k) for k in ("text", "provider", "model", "input_tokens", "output_tokens",
                                                        "usd", "stop_reason", "data")})


def serve(host: str = "0.0.0.0", port: int = 8765) -> None:
    from .factory import make_provider
    token = os.environ.get("LLM_BRIDGE_TOKEN", "")
    if not token:
        sys.exit("Set LLM_BRIDGE_TOKEN (the same value in the container) before starting the bridge.")
    provider = make_provider(os.environ.get("BRIDGE_PROVIDER", "claude-cli"))

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, payload: Dict[str, Any]) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authorised(self) -> bool:
            return self.headers.get("Authorization") == "Bearer " + token

        def do_GET(self):
            if self.path != "/health" or not self._authorised():
                return self._send(404, {"error": "not found"})
            self._send(200, {"provider": provider.name, "model": provider.model})

        def do_POST(self):
            if self.path != "/complete" or not self._authorised():
                return self._send(404, {"error": "not found"})
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            try:
                r = provider.complete(req["system"], req["messages"], req.get("json_schema"), req.get("max_tokens", 4000))
            except LLMError as exc:
                return self._send(502, {"error": str(exc)})
            self._send(200, {"text": r.text, "provider": r.provider, "model": r.model, "input_tokens": r.input_tokens,
                             "output_tokens": r.output_tokens, "usd": r.usd, "stop_reason": r.stop_reason, "data": r.data})

        def log_message(self, fmt, *args):
            sys.stderr.write("bridge: " + fmt % args + "\n")

    print("LLM bridge on %s:%d -> %s (%s)" % (host, port, provider.name, provider.model))
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    serve(os.environ.get("LLM_BRIDGE_HOST", "0.0.0.0"), int(os.environ.get("LLM_BRIDGE_PORT", "8765")))
