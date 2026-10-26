"""FastAPI app of the research API (spec 057). Local research use by default: no accounts; bind to 127.0.0.1.

SMARTAGRI_ACCOUNTS=optional turns on optional accounts and per-browser isolation for a public deployment (auth.py)."""
from __future__ import annotations

import hmac
import html
import os
import secrets
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import i18n
from . import auth
from . import locale as answer_locale
from .service import BadRequest, NotFound, ResearchService, Unavailable

STATIC = Path(__file__).resolve().parent / "static"
# Map tiles are the client's only external request. Defaults are in static/index.html; these environment variables
# replace them (SMARTAGRI_TILE_URL=none turns tiles off: the parcel can still be drawn on an empty grid).
TILE_URL_META = '<meta name="smartagri-tile-url" content="'
TILE_ATTRIBUTION_META = '<meta name="smartagri-tile-attribution" content="'


def _set_meta(page: str, prefix: str, value: str) -> str:
    start = page.find(prefix)
    if start < 0:
        return page
    start += len(prefix)
    end = page.find('"', start)
    return page[:start] + html.escape(value, quote=True) + page[end:]


def index_html() -> str:
    """The client page, with the tile settings of this server (environment) when they are set."""
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    url = os.environ.get("SMARTAGRI_TILE_URL")
    attribution = os.environ.get("SMARTAGRI_TILE_ATTRIBUTION")
    if url is not None:
        page = _set_meta(page, TILE_URL_META, url.strip())
    if attribution is not None:
        page = _set_meta(page, TILE_ATTRIBUTION_META, attribution.strip())
    return page


class RatingIn(BaseModel):
    """Same shape as the product API's rating (rubric R1-R5, 0-2 each; critical error classes; comment)."""
    item_id: str
    rater: str
    r1: int = Field(ge=0, le=2)
    r2: int = Field(ge=0, le=2)
    r3: int = Field(ge=0, le=2)
    r4: int = Field(ge=0, le=2)
    r5: int = Field(ge=0, le=2)
    critical: List[str] = []
    comment: str = ""


def _message(exc: Exception) -> str:
    """An error message in the request locale (messages are written in the default locale)."""
    text = str(exc)
    return i18n.translate_message(text) if i18n.current() == "en" else text


class Credentials(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)


class TokenIn(BaseModel):
    token: str = Field(max_length=200)


class ResetIn(BaseModel):
    token: str = Field(max_length=200)
    password: str = Field(max_length=1024)


class EmailIn(BaseModel):
    email: str = Field(max_length=320)


class PasswordIn(BaseModel):
    password: str = Field(max_length=1024)


PARCEL_NOT_FOUND = "Parcela nije pronađena."


def create_app(service: Optional[ResearchService] = None, accounts: Optional[auth.Accounts] = None) -> FastAPI:
    answer_locale.ensure_english_catalogue()
    svc = service or ResearchService()
    if accounts is None and auth.enabled():
        accounts = auth.Accounts(svc.store)
    app = FastAPI(title="SmartAgri research API", version="0.1.0",
                  description="Research prototype: parcels, input profile with quality, advisory conversation (V0-V5), "
                              "provenance, VC chat and blind rating.")
    api = APIRouter(prefix="/api")

    def call(fn, *args):
        try:
            return fn(*args)
        except NotFound as exc:
            raise HTTPException(404, _message(exc))
        except BadRequest as exc:
            raise HTTPException(400, _message(exc))
        except Unavailable as exc:
            raise HTTPException(503, _message(exc))

    @app.middleware("http")
    async def _locale(request: Request, call_next):
        # The answer language of this request (English by default, SMARTAGRI_LOCALE, ?lang=, X-SmartAgri-Lang); the
        # rating endpoints always run in the default locale. Outside a request the default locale applies.
        code = answer_locale.for_request(request.url.path, request.query_params.get("lang"),
                                         request.headers.get(answer_locale.HEADER))
        i18n.begin(code)
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Content-Language"] = code
        return response

    # ------------------------------------------------------------ optional accounts (off by default)
    def owner(request: Request) -> Optional[str]:
        return getattr(request.state, "owner", None) if accounts else None

    def guard_parcel(request: Request, parcel_id: Optional[str]) -> None:
        """With accounts on, a parcel of another user or browser is answered exactly like a missing one."""
        if accounts and not accounts.owns(owner(request), parcel_id):
            raise HTTPException(404, _message(NotFound(PARCEL_NOT_FOUND)))

    def guard_conversation(request: Request, conversation_id: Optional[str]) -> None:
        if accounts:
            conv = svc.store.get_conversation(conversation_id) if conversation_id else None
            if conv is None or not accounts.owns(owner(request), conv.get("parcel_id")):
                raise HTTPException(404, _message(NotFound("Razgovor nije pronađen.")))

    if accounts:
        def cookie(response, request: Request, name: str, value: Optional[str], days: Optional[float],
                   http_only: bool = True):
            """days=None: a session cookie (no Max-Age/Expires), ended when the browser closes."""
            secure = auth.secure_request(request.url.scheme)
            if value is None:
                response.delete_cookie(name, path="/", httponly=http_only, samesite="lax", secure=secure)
            else:
                response.set_cookie(name, value, max_age=None if days is None else int(days * 86400), path="/",
                                    httponly=http_only, samesite="lax", secure=secure)

        @app.middleware("http")
        async def _accounts(request: Request, call_next):
            path = request.url.path
            if path.startswith("/static/") or path.startswith(auth.EXEMPT_PATHS):
                return await call_next(request)
            if path.startswith("/api/") and request.method in auth.UNSAFE_METHODS:
                # CSRF: the request must come from this site (Origin) and carry the double-submit token.
                sent = request.headers.get(auth.CSRF_HEADER) or ""
                kept = request.cookies.get(auth.CSRF_COOKIE) or ""
                if (not auth.origin_allowed(request.headers.get("origin"), request.url.scheme,
                                            request.headers.get("host"))
                        or not kept or not hmac.compare_digest(sent, kept)):
                    return JSONResponse({"detail": "The request was refused (security check). Reload the page and "
                                                   "try again."}, status_code=403)
            new_cookies: Dict[str, Optional[str]] = {}
            browser = request.cookies.get(auth.BROWSER_COOKIE)
            if not browser or len(browser) > 100:
                browser = secrets.token_urlsafe(32)
                new_cookies[auth.BROWSER_COOKIE] = browser
            if not request.cookies.get(auth.CSRF_COOKIE):
                new_cookies[auth.CSRF_COOKIE] = secrets.token_urlsafe(24)
            session = request.cookies.get(auth.SESSION_COOKIE)
            user = accounts.session_user(session) if session and path.startswith("/api/") else None
            if session and path.startswith("/api/") and user is None:
                new_cookies[auth.SESSION_COOKIE] = None                # expired or signed out elsewhere
            request.state.user = user
            request.state.browser_owner = auth.browser_owner(browser)
            request.state.owner = auth.user_owner(user) if user else request.state.browser_owner
            request.state.cookies = new_cookies                       # routes add their own changes here
            if path.startswith("/api/"):
                if user is None:
                    accounts.touch(request.state.browser_owner)           # anonymous work stays alive while used
                accounts.maybe_purge()                                    # and expires after SMARTAGRI_ANON_TTL_HOURS
            response = await call_next(request)
            for name, value in request.state.cookies.items():
                if name == auth.SESSION_COOKIE:
                    cookie(response, request, name, value, auth.session_days())
                elif name == auth.CSRF_COOKIE:
                    cookie(response, request, name, value, auth.BROWSER_DAYS, http_only=False)
                else:
                    cookie(response, request, name, value, None)              # anonymous browser: session cookie
            if path.startswith("/api/"):
                response.headers["Cache-Control"] = "no-store"
            return response

        def ip(request: Request) -> str:
            return request.client.host if request.client else "unknown"

        def auth_call(fn, *args):
            try:
                return fn(*args)
            except auth.AuthError as exc:
                headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
                raise HTTPException(exc.status, exc.message, headers=headers)

        def signed_in(request: Request, user: Dict[str, Any], token: str) -> Dict[str, Any]:
            request.state.cookies[auth.SESSION_COOKIE] = token
            return {"user": user, "email": accounts.email_enabled}

        def me_body(request: Request) -> Dict[str, Any]:
            user = request.state.user
            return {"user": accounts.public(user) if user else None, "email": accounts.email_enabled}

        @api.get("/auth/me")
        def auth_me(request: Request):
            return me_body(request)

        @api.post("/auth/signup", status_code=201)
        def auth_signup(request: Request, body: Credentials):
            user, token = auth_call(accounts.signup, body.email, body.password, ip(request),
                                    request.state.browser_owner)
            if token is None:                                         # e-mail on: confirm first (same answer always)
                return {"user": None, "email": True, "verify_sent": True}
            return signed_in(request, user, token)

        @api.post("/auth/signin")
        def auth_signin(request: Request, body: Credentials):
            user, token = auth_call(accounts.signin, body.email, body.password, ip(request),
                                    request.state.browser_owner)
            return signed_in(request, user, token)

        @api.post("/auth/signout")
        def auth_signout(request: Request):
            accounts.signout(request.cookies.get(auth.SESSION_COOKIE))
            request.state.cookies[auth.SESSION_COOKIE] = None
            request.state.cookies[auth.BROWSER_COOKIE] = secrets.token_urlsafe(32)   # a fresh, empty browser
            return {"user": None, "email": accounts.email_enabled}

        @api.post("/auth/verify")
        def auth_verify(request: Request, body: TokenIn):
            return {"user": auth_call(accounts.verify, body.token, ip(request)), "verified": True}

        @api.post("/auth/password/forgot", status_code=202)
        def auth_forgot(request: Request, body: EmailIn):
            auth_call(accounts.forgot, body.email, ip(request))
            return {"sent": True}

        @api.post("/auth/password/reset")
        def auth_reset(request: Request, body: ResetIn):
            user, token = auth_call(accounts.reset, body.token, body.password, ip(request),
                                    request.state.browser_owner)
            return signed_in(request, user, token)

        @api.post("/auth/account/delete")
        def auth_delete(request: Request, body: PasswordIn):
            user = request.state.user
            if user is None:
                raise HTTPException(401, "Sign in first.")
            deleted = auth_call(accounts.delete_account, user, body.password, ip(request))
            request.state.cookies[auth.SESSION_COOKIE] = None
            request.state.cookies[auth.BROWSER_COOKIE] = secrets.token_urlsafe(32)
            return {"deleted": True, "parcels": deleted}

    @api.get("/health")
    def health():
        return svc.health()

    @api.get("/meta")
    def meta():
        return dict(svc.meta(), accounts={"enabled": accounts is not None,
                                          "email": bool(accounts and accounts.email_enabled)})

    @api.post("/parcels", status_code=201)
    def create_parcel(request: Request, body: Dict[str, Any] = Body(...)):
        parcel = call(svc.create_parcel, body)
        if accounts:
            accounts.own(parcel["id"], owner(request))
        return parcel

    @api.get("/parcels")
    def list_parcels(request: Request):
        return accounts.parcels(owner(request)) if accounts else svc.list_parcels()

    @api.get("/parcels/{parcel_id}")
    def get_parcel(request: Request, parcel_id: str):
        guard_parcel(request, parcel_id)
        return call(svc.get_parcel, parcel_id)

    @api.post("/parcels/{parcel_id}/profile/refresh")
    def refresh_profile(request: Request, parcel_id: str):
        guard_parcel(request, parcel_id)
        return call(svc.refresh_profile, parcel_id)

    @api.get("/parcels/{parcel_id}/profile")
    def get_profile(request: Request, parcel_id: str):
        guard_parcel(request, parcel_id)
        return call(svc.get_profile, parcel_id)

    @api.post("/parcels/{parcel_id}/chat")
    def chat(request: Request, parcel_id: str, body: Dict[str, Any] = Body(...)):
        guard_parcel(request, parcel_id)
        return call(svc.chat, parcel_id, body)

    @api.post("/parcels/{parcel_id}/ai-chat")
    def ai_chat(request: Request, parcel_id: str, body: Dict[str, Any] = Body(...)):
        guard_parcel(request, parcel_id)
        return call(svc.ai_chat, parcel_id, body)

    @api.get("/conversations/{conversation_id}")
    def conversation(request: Request, conversation_id: str):
        guard_conversation(request, conversation_id)
        return call(svc.get_conversation, conversation_id)

    @api.get("/runs/{run_id}")
    def run(request: Request, run_id: str):
        if accounts:
            found = svc.store.get_run(run_id)
            guard_conversation(request, found.get("conversation_id") if found else None)
        return call(svc.get_run, run_id)

    @api.get("/llm")
    def llm():
        return svc.llm_info()

    @api.get("/eval/rubric")
    def rubric():
        return svc.rubric()

    @api.get("/eval/runs")
    def eval_runs(set_name: Optional[str] = Query(default=None, alias="set")):
        return svc.eval_runs(set_name)

    @api.get("/eval/rating/next")
    def rating_next(rater: str = Query(min_length=1)):
        return svc.rating_next(rater)

    @api.post("/eval/rating", status_code=201)
    def rating_save(body: RatingIn):
        return call(svc.rating_save, body.model_dump())

    app.include_router(api)
    # Client assets (CSS, JS, icon, vendored Leaflet with its licence); no build step, no CDN.
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

    @app.get("/", include_in_schema=False, response_class=HTMLResponse)
    def index():
        return HTMLResponse(index_html())

    return app
