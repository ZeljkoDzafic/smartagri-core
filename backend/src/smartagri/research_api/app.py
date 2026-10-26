"""FastAPI app of the research API (spec 057). Local research use: no accounts; bind to 127.0.0.1."""
from __future__ import annotations

import html
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import i18n
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


def create_app(service: Optional[ResearchService] = None) -> FastAPI:
    answer_locale.ensure_english_catalogue()
    svc = service or ResearchService()
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

    @api.get("/health")
    def health():
        return svc.health()

    @api.get("/meta")
    def meta():
        return svc.meta()

    @api.post("/parcels", status_code=201)
    def create_parcel(body: Dict[str, Any] = Body(...)):
        return call(svc.create_parcel, body)

    @api.get("/parcels")
    def list_parcels():
        return svc.list_parcels()

    @api.get("/parcels/{parcel_id}")
    def get_parcel(parcel_id: str):
        return call(svc.get_parcel, parcel_id)

    @api.post("/parcels/{parcel_id}/profile/refresh")
    def refresh_profile(parcel_id: str):
        return call(svc.refresh_profile, parcel_id)

    @api.get("/parcels/{parcel_id}/profile")
    def get_profile(parcel_id: str):
        return call(svc.get_profile, parcel_id)

    @api.post("/parcels/{parcel_id}/chat")
    def chat(parcel_id: str, body: Dict[str, Any] = Body(...)):
        return call(svc.chat, parcel_id, body)

    @api.post("/parcels/{parcel_id}/ai-chat")
    def ai_chat(parcel_id: str, body: Dict[str, Any] = Body(...)):
        return call(svc.ai_chat, parcel_id, body)

    @api.get("/conversations/{conversation_id}")
    def conversation(conversation_id: str):
        return call(svc.get_conversation, conversation_id)

    @api.get("/runs/{run_id}")
    def run(run_id: str):
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
