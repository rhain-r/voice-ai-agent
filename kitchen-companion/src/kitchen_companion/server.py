"""FastAPI app: SmallWebRTC signaling, the recipe library, and the built tablet app."""

import asyncio
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pipecat.transports.smallwebrtc.request_handler import (
    IceCandidate,
    SmallWebRTCPatchRequest,
    SmallWebRTCRequest,
    SmallWebRTCRequestHandler,
)
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from kitchen_companion.config import REQUIRED, Settings, require
from kitchen_companion.recipes.importer import ImportBlocked, RecipeNotFound, import_recipe
from kitchen_companion.recipes.library import Library
from kitchen_companion.registry import KITCHEN_ID_RE, KitchenRegistry

logger = logging.getLogger(__name__)

DEFAULT_WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"


class OfferBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    sdp: str
    type: str
    pc_id: str | None = Field(default=None, validation_alias=AliasChoices("pc_id", "pcId"))
    restart_pc: bool | None = Field(default=None, validation_alias=AliasChoices("restart_pc", "restartPc"))
    request_data: dict[str, Any] | None = Field(
        default=None, validation_alias=AliasChoices("request_data", "requestData")
    )


class CandidateBody(BaseModel):
    candidate: str
    sdp_mid: str = Field(validation_alias=AliasChoices("sdp_mid", "sdpMid"))
    sdp_mline_index: int = Field(validation_alias=AliasChoices("sdp_mline_index", "sdpMLineIndex"))


class PatchBody(BaseModel):
    pc_id: str = Field(validation_alias=AliasChoices("pc_id", "pcId"))
    candidates: list[CandidateBody]


class ImportBody(BaseModel):
    url: str = Field(max_length=2048)


def create_app(
    settings: Settings,
    registry: KitchenRegistry | None = None,
    library: Library | None = None,
    bot_runner=None,
    importer=import_recipe,
    webrtc_handler=None,
) -> FastAPI:
    if bot_runner is None:
        from kitchen_companion.bot import run_bot  # heavy (models, codecs); only needed to serve calls

        bot_runner = run_bot
    registry = registry or KitchenRegistry()
    library = library or Library.load_bundled()
    webrtc = webrtc_handler or SmallWebRTCRequestHandler()
    bots: set[asyncio.Task] = set()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        for task in bots:
            task.cancel()
        await webrtc.close()
        await registry.close()

    app = FastAPI(title="Kitchen Companion", lifespan=lifespan)
    app.state.webrtc = webrtc
    app.state.registry = registry
    app.state.library = library

    @app.post("/api/offer")
    async def offer(body: OfferBody):
        kitchen_id = str((body.request_data or {}).get("kitchen_id", ""))
        if not re.match(KITCHEN_ID_RE, kitchen_id):
            raise HTTPException(status_code=422, detail="A valid kitchen_id is required.")

        async def on_connection(connection) -> None:
            kitchen = registry.get_or_create(kitchen_id)
            task = asyncio.create_task(bot_runner(connection, kitchen, library, settings))
            bots.add(task)
            task.add_done_callback(bots.discard)

        request = SmallWebRTCRequest(
            sdp=body.sdp,
            type=body.type,
            pc_id=body.pc_id,
            restart_pc=body.restart_pc,
            request_data={"kitchen_id": kitchen_id},
        )
        return await webrtc.handle_web_request(request, on_connection)

    @app.patch("/api/offer")
    async def offer_patch(body: PatchBody):
        candidates = [IceCandidate(c.candidate, c.sdp_mid, c.sdp_mline_index) for c in body.candidates]
        await webrtc.handle_patch_request(SmallWebRTCPatchRequest(pc_id=body.pc_id, candidates=candidates))
        return {"status": "success"}

    @app.get("/api/recipes")
    async def recipes():
        return [
            {"id": r.id, "title": r.title, "servings": r.servings, "total_time_min": r.total_time_min}
            for r in library.all()
        ]

    @app.get("/api/recipes/{recipe_id}")
    async def recipe(recipe_id: str):
        found = library.get(recipe_id)
        if found is None:
            raise HTTPException(status_code=404, detail="No such recipe.")
        return found.model_dump(mode="json")

    @app.post("/api/recipes/import")
    async def import_from_url(body: ImportBody):
        try:
            imported = await importer(body.url)
        except (RecipeNotFound, ImportBlocked) as e:
            return JSONResponse(status_code=422, content={"detail": str(e)})
        library.add(imported)
        return imported.model_dump(mode="json")

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    web_dist = Path(settings.web_dist) if settings.web_dist else DEFAULT_WEB_DIST
    if (web_dist / "index.html").exists():
        app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")

    return app


def run() -> None:
    settings = Settings()
    require(settings, REQUIRED)
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
