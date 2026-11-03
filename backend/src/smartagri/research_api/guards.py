"""Request and response guards of the public web app, as plain ASGI middleware (outermost, before any routing).

- RequestGuardMiddleware: a limit on the size of a request body (SMARTAGRI_MAX_BODY_BYTES, default 262144 = 256 KiB;
  413 over it), a limit on the nesting depth of a JSON body, and the JSON constants NaN and Infinity (which Python
  accepts and every later step chokes on) are refused with 400 instead of reaching the handlers.
- SecurityHeadersMiddleware: X-Content-Type-Options, Referrer-Policy, a Content-Security-Policy that lets the page load
  only its own files plus the map tile host, and `frame-ancestors 'none'` (with X-Frame-Options for older browsers).
Evaluation does not go through the web app, so neither guard touches it.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

DEFAULT_MAX_BODY = 256 * 1024
MAX_JSON_DEPTH = 32
BODY_METHODS = ("POST", "PUT", "PATCH", "DELETE")

_STRING = re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"')
_BRACKET = re.compile(r"[\[\]{}]")
_BARE_CONSTANT = re.compile(r"(?<![\w.])-?(?:NaN|Infinity)(?!\w)")


def max_body_bytes() -> int:
    try:
        value = int(os.environ.get("SMARTAGRI_MAX_BODY_BYTES") or DEFAULT_MAX_BODY)
    except ValueError:
        return DEFAULT_MAX_BODY
    return value if value > 0 else DEFAULT_MAX_BODY


def json_problem(data: bytes, max_depth: int = MAX_JSON_DEPTH) -> Optional[str]:
    """Why a JSON body is refused before parsing (too deep, or NaN/Infinity), else None. Strings are skipped, so a
    bracket or the word NaN inside a text is no problem."""
    text = _STRING.sub('""', data.decode("utf-8", "replace"))
    if _BARE_CONSTANT.search(text):
        return "The request body is not valid JSON."
    depth = 0
    for m in _BRACKET.finditer(text):
        if m.group() in "[{":
            depth += 1
            if depth > max_depth:
                return "The request body is nested too deeply."
        else:
            depth -= 1
    return None


async def _reply(send: Any, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode("utf-8")
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode("ascii")),
                            (b"cache-control", b"no-store")]})
    await send({"type": "http.response.body", "body": body})


class RequestGuardMiddleware:
    def __init__(self, app: Any, max_bytes: Optional[int] = None, max_depth: int = MAX_JSON_DEPTH):
        self.app = app
        self.max_bytes = max_bytes if max_bytes is not None else max_body_bytes()
        self.max_depth = max_depth

    async def __call__(self, scope: Dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope.get("method") not in BODY_METHODS:
            await self.app(scope, receive, send)
            return
        headers = {k: v for k, v in scope.get("headers") or []}
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > self.max_bytes:
                    await _reply(send, 413, "The request body is too large.")
                    return
            except ValueError:
                await _reply(send, 400, "The request is not valid.")
                return
        chunks: List[bytes] = []
        total = 0
        more = True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > self.max_bytes:                      # a chunked body without a declared length
                await _reply(send, 413, "The request body is too large.")
                return
            chunks.append(chunk)
            more = bool(message.get("more_body"))
        data = b"".join(chunks)
        if data and b"json" in headers.get(b"content-type", b"").lower():
            problem = json_problem(data, self.max_depth)
            if problem:
                await _reply(send, 400, problem)
                return
        sent = False

        async def replay() -> Dict[str, Any]:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": data, "more_body": False}
            return await receive()                           # the client disconnect, as before

        await self.app(scope, replay, send)


# ------------------------------------------------------------------------------------------------ host and evaluation guards
LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "[::1]", "::1")
TEST_HOSTS = ("testserver",)                     # the host name of Starlette's test client


def _host_name(value: str) -> str:
    """The host of a Host header without its port: `Example.org:8080` -> `example.org`, `[::1]:8000` -> `[::1]`."""
    value = (value or "").strip().lower()
    if value.startswith("["):
        return value.split("]")[0] + "]"
    return value.split(":")[0]


def allowed_hosts() -> Optional[List[str]]:
    """Host names the app answers to (SMARTAGRI_ALLOWED_HOSTS, comma-separated, plus the host of SMARTAGRI_PUBLIC_URL and
    the loopback names), or None when `*` is listed: any host (for a private network or a proxy that sets its own).
    A request with another Host header is refused, so a page on an attacker's name that resolves to this machine
    (DNS rebinding) cannot read it (audit S7)."""
    listed = [_host_name(h) for h in (os.environ.get("SMARTAGRI_ALLOWED_HOSTS") or "").split(",") if h.strip()]
    if "*" in listed:
        return None
    public = urlsplit(os.environ.get("SMARTAGRI_PUBLIC_URL") or "").hostname
    return list(LOOPBACK_HOSTS) + list(TEST_HOSTS) + listed + ([public.lower()] if public else [])


def eval_api_enabled() -> bool:
    """Are the blind-rating routes (/api/eval/...) served? SMARTAGRI_EVAL_API=1 / 0 decides; unset, they are served on a
    private installation (no SMARTAGRI_PUBLIC_URL) and off on a public one (audit S8): the rating screen does not use
    accounts, so it must not face the internet by default. Accounts alone do not switch it off: the rating routes are
    independent of them by design."""
    flag = (os.environ.get("SMARTAGRI_EVAL_API") or "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return True
    if flag in ("0", "false", "no", "off"):
        return False
    return not (os.environ.get("SMARTAGRI_PUBLIC_URL") or "").strip()


class HostGuardMiddleware:
    """Refuses (400) a request whose Host header is not an allowed host, and (404) the /api/eval/ routes when they are off."""

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: Dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        hosts = allowed_hosts()
        if hosts is not None:
            host = _host_name(dict(scope.get("headers") or []).get(b"host", b"").decode("latin-1"))
            if host not in hosts:
                await _reply(send, 400, "Invalid host header.")
                return
        if scope.get("path", "").startswith("/api/eval/") and not eval_api_enabled():
            await _reply(send, 404, "Not found.")
            return
        await self.app(scope, receive, send)


# ------------------------------------------------------------------------------------------------ response headers
def tile_sources(url: str) -> List[str]:
    """The CSP image sources for a tile URL template ({s} subdomain, {z}/{x}/{y}); empty for none or an unusable URL."""
    url = (url or "").strip()
    if not url or url.lower() == "none":
        return []
    parts = urlsplit(url.replace("{s}", "wildcard-s"))
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return []
    host = parts.netloc.replace("wildcard-s", "*")
    return ["%s://%s" % (parts.scheme, host)]


def csp(tile_url: str) -> str:
    img = " ".join(["'self'", "data:"] + tile_sources(tile_url))
    return "; ".join(["default-src 'self'", "script-src 'self'", "style-src 'self'", "img-src " + img,
                      "connect-src 'self'", "font-src 'self'", "object-src 'none'", "base-uri 'self'",
                      "form-action 'self'", "frame-ancestors 'none'"])


# The interactive API documentation (/docs, /redoc) loads its page from a CDN with inline scripts: no CSP there.
NO_CSP_PATHS = ("/docs", "/redoc")


class SecurityHeadersMiddleware:
    def __init__(self, app: Any, tile_url: str = ""):
        self.app = app
        self.csp = csp(tile_url).encode("ascii")

    async def __call__(self, scope: Dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        with_csp = not scope.get("path", "").startswith(NO_CSP_PATHS)

        async def send_with_headers(message: Dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                names = {k.lower() for k, _v in message.get("headers", [])}
                extra: List[Tuple[bytes, bytes]] = [(b"x-content-type-options", b"nosniff"),
                                                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                                                    (b"x-frame-options", b"DENY")]
                if with_csp:
                    extra.append((b"content-security-policy", self.csp))
                message = dict(message, headers=list(message.get("headers", [])) + [h for h in extra if h[0] not in names])
            await send(message)

        await self.app(scope, receive, send_with_headers)
