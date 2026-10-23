"""Behavior evals hit the real Claude API. Skipped unless ANTHROPIC_API_KEY is set; run with `-m eval`."""

import os
from contextlib import asynccontextmanager

import pytest
from livekit.agents import AgentSession

from interview_coach.agent.analytics import SpeechAnalytics
from interview_coach.agent.interviewer import Interviewer
from interview_coach.agent.llm import ClaudeVoiceLLM
from interview_coach.agent.prompts import InterviewSetup
from interview_coach.config import Settings
from interview_coach.mcp_server.bank import question_plan

SETUP = InterviewSetup(session_id="s_eval", role="Data Analyst", level="junior", style="behavioral", count=3)


def pytest_collection_modifyitems(config, items):
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    skip = pytest.mark.skip(reason="ANTHROPIC_API_KEY not set")
    for item in items:
        if "evals" in item.path.parts:
            item.add_marker(skip)


@pytest.fixture
def judge_llm():
    # judge() forces a tool call; of the 5.5 models only Haiku accepts a forced tool_choice.
    return ClaudeVoiceLLM(model="claude-haiku-5-5")


@pytest.fixture
def interview():
    @asynccontextmanager
    async def _interview():
        finished: list[str] = []

        async def on_finish(reason: str) -> None:
            finished.append(reason)

        async def on_progress(_: dict) -> None:
            return None

        agent = Interviewer(
            setup=SETUP,
            plan=question_plan(SETUP.role, SETUP.level, SETUP.style, SETUP.count, SETUP.session_id),
            analytics=SpeechAnalytics(),
            on_progress=on_progress,
            on_finish=on_finish,
        )
        async with AgentSession(llm=ClaudeVoiceLLM(model=Settings().live_model)) as session:
            opening = await session.start(agent, capture_run=True)
            yield session, opening, finished

    return _interview
