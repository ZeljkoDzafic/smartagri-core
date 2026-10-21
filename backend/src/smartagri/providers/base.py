"""Adapters for external services. Every response goes through the external cache so runs can be replayed."""
from __future__ import annotations

import contextlib
import contextvars
import hashlib
import json
import os
import time
from datetime import datetime
from typing import Any, Callable, Dict, FrozenSet, Iterator, Optional, Tuple

import httpx

from ..store import Store

# Two retries after the first attempt (FR-015, docs/architecture.md); waits grow as BACKOFF_S * 2**attempt.
RETRIES = 2
BACKOFF_S = 1.0
# Tests replace these: TRANSPORT with an httpx.MockTransport, SLEEP with a no-op.
TRANSPORT: Optional[httpx.BaseTransport] = None
SLEEP: Callable[[float], None] = time.sleep


class ProviderUnavailable(Exception):
    """The provider could not answer; the caller treats the corresponding inputs as missing."""


class Limits:
    """Bounds for provider calls made inside one background job (worker, 2026-10-21 incident): a per-request timeout
    and retry cap, an absolute deadline (on `clock`, time.monotonic() by default) after which no new request starts, request coalescing
    (identical requests within the scope reach the provider once; a failure is remembered as well, so the same
    overloaded endpoint is not waited on again) and providers whose cached response is reused although the caller
    asked for a refresh (satellite at most once per parcel per day, OQ-018-3 (a)).

    Outside a `limits()` block nothing changes: the API, the evaluation kit and offline replays behave as before."""

    def __init__(self, timeout: Optional[float] = None, retries: Optional[int] = None,
                 deadline: Optional[float] = None, coalesce: bool = False,
                 no_refresh: FrozenSet[str] = frozenset(), clock: Callable[[], float] = time.monotonic):
        self.timeout, self.retries, self.deadline, self.clock = timeout, retries, deadline, clock
        self.coalesce, self.no_refresh = coalesce, frozenset(no_refresh)
        self.memo: Dict[str, Any] = {}
        self.stats = {"http_requests": 0, "coalesced": 0}

    def remaining(self) -> Optional[float]:
        return None if self.deadline is None else self.deadline - self.clock()


_LIMITS: "contextvars.ContextVar[Optional[Limits]]" = contextvars.ContextVar("provider_limits", default=None)


@contextlib.contextmanager
def limits(**kwargs: Any) -> Iterator[Limits]:
    """Apply Limits(**kwargs) to every provider call made by this thread (context) inside the block."""
    lim = Limits(**kwargs)
    token = _LIMITS.set(lim)
    try:
        yield lim
    finally:
        _LIMITS.reset(token)


def current_limits() -> Optional[Limits]:
    return _LIMITS.get()


def offline() -> bool:
    return os.environ.get("SMARTAGRI_OFFLINE", "0") == "1"


def request_hash(provider: str, request: Dict[str, Any]) -> str:
    return hashlib.sha256((provider + json.dumps(request, sort_keys=True)).encode("utf-8")).hexdigest()


def _aware(moment: datetime) -> datetime:
    """Naive datetimes are local time (as_of in scenario files is written without an offset)."""
    return moment if moment.tzinfo is not None else moment.astimezone()


def _retryable(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


def http_json(method: str, url: str, label: str, timeout: float, **kwargs: Any) -> Any:
    """One HTTP call returning JSON, retried RETRIES times on transport errors and 5xx answers.

    4xx answers are not retried (the request itself is wrong). After the last failure the provider is
    reported unavailable with `label` (a Serbian sentence prefix) and the exception class name."""
    lim = _LIMITS.get()
    retries = RETRIES if lim is None or lim.retries is None else min(RETRIES, max(0, lim.retries))
    if lim is not None and lim.timeout is not None:
        timeout = min(timeout, lim.timeout)
    last: Optional[Exception] = None
    for attempt in range(retries + 1):
        budget = timeout
        if lim is not None and lim.deadline is not None:
            left = lim.remaining()
            if left <= 0:
                raise ProviderUnavailable("%s: %s" % (label, "DeadlineExceeded"))
            budget = min(timeout, left)
        try:
            if lim is not None:
                lim.stats["http_requests"] += 1
            with httpx.Client(transport=TRANSPORT, timeout=budget) as client:
                r = client.request(method, url, **kwargs)
                r.raise_for_status()
                return r.json()
        except (httpx.HTTPError, ValueError) as exc:
            last = exc
            if not _retryable(exc) or attempt == retries:
                break
            wait = BACKOFF_S * (2 ** attempt)
            if lim is not None and lim.deadline is not None and lim.remaining() <= wait:
                break                                     # no time left for another attempt
            SLEEP(wait)
    raise ProviderUnavailable("%s: %s" % (label, last.__class__.__name__ if last else "nepoznata greška"))


def cached(store: Store, provider: str, request: Dict[str, Any], fetch: Callable[[], Any],
           refresh: bool = False, not_after: Optional[datetime] = None) -> Tuple[Any, str, str]:
    """Return (response, fetched_at, request_hash). In offline mode only the cache is consulted.

    not_after (FR-013): for responses whose content depends on when they were fetched (a live
    forecast), the latest acceptable fetch moment. A cached response fetched later is not used, and
    no new fetch is made once that moment has passed, so a historical context never sees a
    forecast issued after its as_of.
    """
    h = request_hash(provider, request)
    lim = _LIMITS.get()
    if lim is not None and provider in lim.no_refresh:
        refresh = False
    if lim is not None and lim.coalesce and refresh and h in lim.memo:
        lim.stats["coalesced"] += 1
        done = lim.memo[h]
        if isinstance(done, ProviderUnavailable):
            raise ProviderUnavailable(str(done))
        return done
    hit = None if (refresh and not offline()) else store.cache_get(h)
    limit = _aware(not_after) if not_after is not None else None
    if hit and limit is not None and _aware(datetime.fromisoformat(hit["fetched_at"])) > limit:
        hit = None
        if offline():
            raise ProviderUnavailable("Podatak u kešu pribavljen je posle trenutka odluke (%s)." % provider)
    if hit:
        return hit["response"], hit["fetched_at"], h
    if offline():
        raise ProviderUnavailable("Režim bez mreže: traženi odgovor nije u kešu (%s)." % provider)
    if limit is not None and datetime.now().astimezone() > limit:
        raise ProviderUnavailable("Prognoza izdata pre trenutka odluke nije dostupna (%s)." % provider)
    if lim is not None and lim.coalesce and refresh:
        try:
            response = fetch()
        except ProviderUnavailable as exc:
            lim.memo[h] = exc
            raise
        lim.memo[h] = (response, store.cache_put(h, provider, request, response), h)
        return lim.memo[h]
    response = fetch()
    return response, store.cache_put(h, provider, request, response), h
