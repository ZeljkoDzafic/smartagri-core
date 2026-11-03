"""Quotas of the calls that spend something outside the app: the weather and satellite providers (a profile refresh), the
language model (an AI chat) and storage (a new parcel). Fixed windows over the shared `rate_counters` table, like the
limits of the authentication endpoints, keyed by the account or browser owner (accounts on) or the client address (off).

Environment (an integer; 0 switches that quota off):
  SMARTAGRI_QUOTA_REFRESH_PER_HOUR      profile refreshes per owner and hour        (default 30)
  SMARTAGRI_QUOTA_REFRESH_MIN_SECONDS   minimum spacing of refreshes of one parcel  (default 10)
  SMARTAGRI_QUOTA_AI_CHAT_PER_DAY       AI chat messages per owner and day          (default 200)
  SMARTAGRI_QUOTA_PARCELS_PER_DAY       parcels created per owner and day           (default 100)
The defaults are generous on purpose: they stop a script from spending the operator's provider quota and model budget, not a
person from working (audit S5). Over a quota the request gets 429 with Retry-After.
"""
from __future__ import annotations

import hashlib
import os
import time
from typing import Any, Callable, Optional

from fastapi import HTTPException

DEFAULTS = {"refresh_hour": 30, "refresh_gap": 10, "ai_chat_day": 200, "parcels_day": 100}
ENV = {"refresh_hour": "SMARTAGRI_QUOTA_REFRESH_PER_HOUR", "refresh_gap": "SMARTAGRI_QUOTA_REFRESH_MIN_SECONDS",
       "ai_chat_day": "SMARTAGRI_QUOTA_AI_CHAT_PER_DAY", "parcels_day": "SMARTAGRI_QUOTA_PARCELS_PER_DAY"}
WINDOW = {"refresh_hour": 3600, "ai_chat_day": 86400, "parcels_day": 86400}
MESSAGE = "Too many requests of this kind. Try again later."


def setting(name: str) -> int:
    try:
        return max(0, int(os.environ.get(ENV[name]) or DEFAULTS[name]))
    except ValueError:
        return DEFAULTS[name]


def _utc(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def charge(store: Any, name: str, who: str, scope: str = "", clock: Callable[[], float] = time.time) -> None:
    """Count one call of quota `name` by `who` (an owner or an address); HTTP 429 when it is over the quota.
    `scope` narrows the key (the parcel for the refresh spacing)."""
    if name == "refresh_gap":
        limit, window = 1, setting("refresh_gap")
    else:
        limit, window = setting(name), WINDOW[name]
    if limit <= 0 or window <= 0 or not who:
        return
    now = clock()
    slot = int(now // window)
    key = "quota:%s:%s" % (name, hashlib.sha256((who + "|" + scope).encode("utf-8")).hexdigest()[:32])
    id_ = hashlib.sha256(("%s:%d" % (key, slot)).encode("utf-8")).hexdigest()
    n = store.increment("rate_counters", id_, {"key": key, "expires_at": _utc((slot + 1) * window)})
    if n > limit:
        raise HTTPException(429, MESSAGE, headers={"Retry-After": str(int((slot + 1) * window - now) + 1)})


def client_key(request: Any, owner: Optional[str]) -> str:
    """The owner of an account or browser, else the address of the client (as the trusted-proxy middleware set it)."""
    return owner or (request.client.host if request.client else "")
