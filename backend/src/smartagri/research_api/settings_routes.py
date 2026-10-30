"""HTTP side of the web settings (/api/settings/...). The logic is in smartagri.web_settings.service.

Access: reading the effective values needs no account (an anonymous visitor sees the global values, read only); saving
needs a signed-in user (with SMARTAGRI_ACCOUNTS=off the local user); the administrator endpoints (global values, limits,
the log of every layer) answer 403 to anyone else. With accounts on, the existing middleware already enforces the CSRF
double-submit token and the Origin check on every unsafe request; with accounts off this module checks the Origin
itself. Writes are rate limited per user. A parcel's settings can only be read or written through a parcel the caller owns.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse

from ..store import Store
from ..web_settings import registry as reg
from ..web_settings.service import LOCAL_USER, Actor, SettingsError, SettingsService
from . import auth

WRITE_LIMIT = (120, 15 * 60)                      # writes per user per 15 minutes


def actor_of(request: Request, accounts: Optional[auth.Accounts]) -> Actor:
    if accounts is None:                                         # local single-user mode: the local user is the admin
        return Actor(LOCAL_USER, True, "off", LOCAL_USER)
    user = getattr(request.state, "user", None)
    if user is None:
        return Actor(None, False, "optional")
    # Administrator: promoted by the operator on the server, or listed in SMARTAGRI_ADMINS and confirmed through the
    # mailbox. An address nobody confirmed (no SMTP) is never an administrator by being listed (docs/settings.md).
    return Actor(user["id"], accounts.is_admin(user), "optional", (user.get("email") or "").lower())


def _limit(store: Store, actor: Actor, request: Request) -> None:
    now = time.time()
    attempts, window = WRITE_LIMIT
    slot = int(now // window)
    who = actor.user_id or (request.client.host if request.client else "unknown")
    key = "settings:write:%s" % auth._sha(who)[:32]
    n = store.increment("rate_counters", auth._sha("%s:%d" % (key, slot)),
                        {"key": key, "expires_at": auth._utc((slot + 1) * window)})
    if n > attempts:
        raise SettingsError(429, "Too many changes. Please wait and try again later.")


def register(api: APIRouter, svc, accounts: Optional[auth.Accounts], owner: Callable[[Request], Optional[str]]) -> SettingsService:
    settings = SettingsService(svc.store)

    def fail(exc: SettingsError) -> JSONResponse:
        headers = {"Retry-After": "60"} if exc.status == 429 else None
        return JSONResponse({"detail": exc.message, "errors": exc.errors}, status_code=exc.status, headers=headers)

    def parcel_ok(request: Request, parcel_id: Optional[str]) -> Optional[str]:
        """The parcel id when the caller may use it, else SettingsError (404, exactly like a missing parcel)."""
        if not parcel_id:
            return None
        if svc.store.get_parcel(parcel_id) is None or (accounts and not accounts.owns(owner(request), parcel_id)):
            raise SettingsError(404, "Parcel not found.")
        return parcel_id

    def write_guard(request: Request, actor: Actor) -> None:
        if accounts is None and not auth.origin_allowed(request.headers.get("origin"), request.url.scheme,
                                                        request.headers.get("host")):
            raise SettingsError(403, "The request was refused (security check). Reload the page and try again.")
        if actor.can_write:
            _limit(svc.store, actor, request)

    def body_of(body: Any) -> Dict[str, Any]:
        return body if isinstance(body, dict) else {}

    @api.get("/settings")
    def settings_view(request: Request, parcel_id: Optional[str] = Query(default=None, max_length=64)):
        try:
            actor = actor_of(request, accounts)
            pid = parcel_ok(request, parcel_id) if actor.can_write else None
            return settings.view(actor, pid)
        except SettingsError as exc:
            return fail(exc)

    @api.get("/settings/protocol")
    def settings_protocol():
        """The locked protocol files, read only (they define the experiment; web settings never reach them)."""
        return {"files": reg.protocol_view()}

    @api.get("/settings/versions")
    def settings_versions(request: Request, scope: str = Query(max_length=10), parcel_id: Optional[str] = Query(default=None, max_length=64),
                          user_id: Optional[str] = Query(default=None, max_length=64)):
        try:
            actor = actor_of(request, accounts)
            pid = parcel_ok(request, parcel_id) if scope == "parcel" else None
            return {"versions": settings.versions(actor, scope, pid, user_id)}
        except SettingsError as exc:
            return fail(exc)

    @api.get("/settings/audit")
    def settings_audit(request: Request, scope: Optional[str] = Query(default=None, max_length=10),
                       parcel_id: Optional[str] = Query(default=None, max_length=64), param: str = Query(default="", max_length=120),
                       who: str = Query(default="", max_length=64), since: str = Query(default="", max_length=32),
                       until: str = Query(default="", max_length=32), action: str = Query(default="", max_length=16),
                       limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0, le=100000)):
        try:
            actor = actor_of(request, accounts)
            pid = parcel_ok(request, parcel_id) if scope == "parcel" and not actor.admin else parcel_id
            return settings.audit(actor, scope, pid, param, who, since, until, action, limit, offset)
        except SettingsError as exc:
            return fail(exc)

    @api.get("/settings/limits")
    def settings_limits(request: Request):
        actor = actor_of(request, accounts)
        if not actor.admin:
            return fail(SettingsError(403, "Not allowed."))
        values, version = settings.layer("limits", "limits")
        return {"limits": values, "version": version}

    @api.put("/settings/limits")
    def settings_limits_put(request: Request, body: Dict[str, Any] = Body(...)):
        try:
            actor = actor_of(request, accounts)
            if not actor.admin:
                raise SettingsError(403, "Not allowed.")
            write_guard(request, actor)
            return settings.set_limits(actor, body_of(body).get("limits"), body_of(body).get("reason"))
        except SettingsError as exc:
            return fail(exc)

    @api.post("/settings/restore")
    def settings_restore(request: Request, body: Dict[str, Any] = Body(...)):
        try:
            b = body_of(body)
            actor = actor_of(request, accounts)
            scope = b.get("scope")
            if scope not in ("global", "user", "parcel", "limits"):
                raise SettingsError(400, "Unknown settings level.")
            pid = parcel_ok(request, b.get("parcel_id")) if scope == "parcel" else None
            write_guard(request, actor)
            return settings.restore(actor, scope, pid, b.get("version"), b.get("keys"), b.get("reason"))
        except SettingsError as exc:
            return fail(exc)

    @api.put("/settings/parcels/{parcel_id}")
    def settings_parcel_put(request: Request, parcel_id: str, body: Dict[str, Any] = Body(...)):
        return _put(request, "parcel", parcel_id, body)

    @api.post("/settings/parcels/{parcel_id}/reset")
    def settings_parcel_reset(request: Request, parcel_id: str, body: Dict[str, Any] = Body(default={})):
        return _reset(request, "parcel", parcel_id, body)

    @api.put("/settings/{scope}")
    def settings_put(request: Request, scope: str, body: Dict[str, Any] = Body(...)):
        return _put(request, scope, None, body)

    @api.post("/settings/{scope}/reset")
    def settings_reset(request: Request, scope: str, body: Dict[str, Any] = Body(default={})):
        return _reset(request, scope, None, body)

    def _put(request: Request, scope: str, parcel_id: Optional[str], body: Any):
        try:
            if scope not in ("global", "user", "parcel"):
                raise SettingsError(404, "Unknown settings level.")
            actor = actor_of(request, accounts)
            pid = parcel_ok(request, parcel_id) if scope == "parcel" else None
            write_guard(request, actor)
            b = body_of(body)
            base = b.get("base_version")
            return settings.update(actor, scope, pid, b.get("values"), b.get("reason"),
                                   base if isinstance(base, int) and not isinstance(base, bool) else None)
        except SettingsError as exc:
            return fail(exc)

    def _reset(request: Request, scope: str, parcel_id: Optional[str], body: Any):
        try:
            if scope not in ("global", "user", "parcel"):
                raise SettingsError(404, "Unknown settings level.")
            actor = actor_of(request, accounts)
            pid = parcel_ok(request, parcel_id) if scope == "parcel" else None
            write_guard(request, actor)
            b = body_of(body)
            return settings.reset(actor, scope, pid, b.get("keys"), bool(b.get("all")), b.get("reason"))
        except SettingsError as exc:
            return fail(exc)

    return settings
