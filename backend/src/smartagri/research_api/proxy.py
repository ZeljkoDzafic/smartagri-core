"""The client address behind a reverse proxy, taken safely.

SMARTAGRI_TRUSTED_PROXIES (comma-separated addresses or networks, default: none) lists the proxies in front of the app.
Only a request whose TCP peer is in that list may say, in X-Forwarded-For, who the client is, and even then the list is
read from the right: every address that belongs to a trusted proxy is skipped and the first other address is the client.
That is the address the nearest proxy actually saw, so a client that sends its own X-Forwarded-For cannot choose it
(the leftmost entry, which uvicorn's `forwarded-allow-ips=*` takes, is whatever the client wrote).
The scheme is taken from X-Forwarded-Proto in the same case only. Run the server with uvicorn's own proxy handling off
(`python -m smartagri.research_api` does).
"""
from __future__ import annotations

import ipaddress
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

ENV_TRUSTED = "SMARTAGRI_TRUSTED_PROXIES"
MAX_HOPS = 20


def trusted_proxies(raw: Optional[str] = None) -> List[Any]:
    """The configured networks; a value that is not an address or a network is an error at start-up."""
    text = os.environ.get(ENV_TRUSTED, "") if raw is None else raw
    nets = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if part == "*":
            raise ValueError("%s must list the proxies' addresses, not '*': trusting every peer lets a client choose "
                             "its own address" % ENV_TRUSTED)
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            raise ValueError("%s: %r is not an IP address or network" % (ENV_TRUSTED, part))
    return nets


def _ip(text: str) -> Optional[Any]:
    try:
        addr = ipaddress.ip_address(text.strip())
    except ValueError:
        return None
    return addr.ipv4_mapped if getattr(addr, "ipv4_mapped", None) else addr


def _in(addr: Any, nets: Sequence[Any]) -> bool:
    return any(addr.version == n.version and addr in n for n in nets)


def client_address(peer: Optional[str], forwarded: Sequence[str], nets: Sequence[Any]) -> Tuple[Optional[str], bool]:
    """(address, via_trusted_proxy). `forwarded` holds the X-Forwarded-For header values, in order."""
    addr = _ip(peer) if peer else None
    if addr is None or not nets or not _in(addr, nets):
        return peer, False
    hops: List[str] = []
    for value in forwarded:
        hops.extend(h for h in value.split(",") if h.strip())
    for raw in reversed(hops[-MAX_HOPS:]):
        hop = _ip(raw)
        if hop is None:
            return peer, True                       # something a proxy would not write: keep the proxy's own address
        if not _in(hop, nets):
            return str(hop), True
    return peer, True


class TrustedProxyMiddleware:
    """ASGI middleware: sets scope["client"] (and the scheme) from the forwarding headers of trusted proxies only."""

    def __init__(self, app: Any, proxies: Optional[Sequence[Any]] = None):
        self.app = app
        self.nets = list(trusted_proxies() if proxies is None else proxies)

    async def __call__(self, scope: Dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] in ("http", "websocket") and self.nets:
            client = scope.get("client")
            headers = scope.get("headers") or []
            forwarded = [v.decode("latin-1") for k, v in headers if k == b"x-forwarded-for"]
            addr, trusted = client_address(client[0] if client else None, forwarded, self.nets)
            if trusted:
                scope = dict(scope)
                if addr:
                    scope["client"] = (addr, 0)
                proto = next((v.decode("latin-1").split(",")[0].strip().lower() for k, v in reversed(headers)
                              if k == b"x-forwarded-proto"), "")
                if proto in ("http", "https"):
                    scope["scheme"] = proto if scope["type"] == "http" else {"http": "ws", "https": "wss"}[proto]
        await self.app(scope, receive, send)
