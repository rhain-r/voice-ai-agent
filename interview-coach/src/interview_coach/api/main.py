"""Sessions API: mints LiveKit tokens with agent dispatch, stores results, runs the scorecard (spec §5.8)."""

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import anthropic
import uvicorn
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from livekit import api
from pydantic import BaseModel, Field

from interview_coach.config import API_REQUIRED, Settings, missing_keys, require
from interview_coach.mcp_server.bank import rubric
from interview_coach.scorecard.graph import ClaudeGrader, Grader, run_scorecard
from interview_coach.scorecard.models import QAItem, SessionInfo

from .db import Store

log = logging.getLogger(__name__)
AGENT_NAME = "interview-coach"


class SessionSetup(BaseModel):
    role: str = Field(min_length=2, max_length=80)
    level: Literal["intern", "junior", "mid", "senior", "staff"]
    style: Literal["behavioral", "technical", "mixed"]
    count: int = Field(ge=1, le=10)


class CompletionPayload(BaseModel):
    status: Literal["completed", "partial"]
    transcript: list[dict]
    qa_items: list[QAItem]
    speech: dict
    latency: dict


def mint_token(settings: Settings, session_id: str, setup: SessionSetup) -> str:
    room = f"coach-{session_id}"
    metadata = json.dumps({"session_id": session_id, **setup.model_dump()})
    return (
        api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(f"candidate-{session_id}")
        .with_name("Candidate")
        .with_grants(api.VideoGrants(room_join=True, room=room))
        .with_room_config(
            api.RoomConfiguration(agents=[api.RoomAgentDispatch(agent_name=AGENT_NAME, metadata=metadata)])
        )
        .to_jwt()
    )


def create_app(
    settings: Settings,
    store: Store | None = None,
    grader_factory: Callable[[], Grader] | None = None,
) -> FastAPI:
    store = store or Store(Path("data/coach.db"))
    grader_factory = grader_factory or (
        lambda: ClaudeGrader(
            anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key or None), settings.grader_model
        )
    )

    app = FastAPI(title="Interview Coach API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    async def run_scorecard_job(session_id: str) -> None:
        row = store.get(session_id)
        if row is None or row["payload"] is None:
            return
        setup, payload = row["setup"], CompletionPayload(**row["payload"])
        try:
            scorecard = await run_scorecard(
                grader_factory(),
                SessionInfo(role=setup["role"], level=setup["level"], style=setup["style"]),
                payload.qa_items,
                rubric(setup["style"]),
            )
            store.set_report(session_id, "ready", scorecard=scorecard.model_dump())
        except Exception as exc:  # the report must always reach a terminal state
            log.exception("scorecard failed for %s", session_id)
            store.set_report(session_id, "failed", error=f"{type(exc).__name__}: {exc}")

    def require_session(session_id: str) -> dict:
        row = store.get(session_id)
        if row is None:
            raise HTTPException(404, "session not found")
        return row

    @app.post("/api/sessions")
    def create_session(setup: SessionSetup) -> dict:
        session_id = store.create(setup)
        return {
            "session_id": session_id,
            "token": mint_token(settings, session_id, setup),
            "livekit_url": settings.livekit_url,
        }

    @app.post("/api/sessions/{session_id}/complete", status_code=202)
    def complete_session(
        session_id: str,
        payload: CompletionPayload,
        background: BackgroundTasks,
        x_agent_secret: str = Header(default=""),
    ) -> dict:
        if x_agent_secret != settings.agent_shared_secret:
            raise HTTPException(401, "bad agent secret")
        require_session(session_id)
        store.complete(session_id, payload)
        store.set_report(session_id, "pending")
        background.add_task(run_scorecard_job, session_id)
        return {"status": "accepted"}

    @app.get("/api/sessions/{session_id}/report")
    def get_report(session_id: str) -> dict:
        row = require_session(session_id)
        payload = row["payload"] or {}
        return {
            "status": row["report_status"] if row["completion_status"] else "in_progress",
            "session": {
                "id": row["id"],
                "created_at": row["created_at"],
                "setup": row["setup"],
                "completion_status": row["completion_status"],
            },
            "speech": payload.get("speech"),
            "latency": payload.get("latency"),
            "transcript": payload.get("transcript", []),
            "qa_items": payload.get("qa_items", []),
            "scorecard": row["scorecard"],
            "error": row["error"],
        }

    @app.post("/api/sessions/{session_id}/report/retry", status_code=202)
    def retry_report(session_id: str, background: BackgroundTasks) -> dict:
        row = require_session(session_id)
        if row["report_status"] != "failed":
            raise HTTPException(409, "only a failed report can be retried")
        store.set_report(session_id, "pending")
        background.add_task(run_scorecard_job, session_id)
        return {"status": "accepted"}

    @app.get("/api/sessions")
    def list_sessions() -> list[dict]:
        return store.list()

    @app.get("/api/health")
    def health() -> dict:
        return {
            "ok": True,
            "keys": {
                "anthropic": not missing_keys(settings, ["anthropic_api_key"]),
                "livekit": not missing_keys(settings, ["livekit_api_key", "livekit_api_secret"]),
            },
        }

    return app


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = Settings()
    require(settings, API_REQUIRED)
    uvicorn.run(create_app(settings), host="0.0.0.0", port=8000)
