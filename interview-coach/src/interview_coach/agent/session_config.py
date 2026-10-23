"""Pure session policy: turn-taking values, STT keyterms, QA segmentation, once-only guards."""

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import Literal

from interview_coach.agent.analytics import SpeechAnalytics
from interview_coach.mcp_server.bank import QuestionItem, role_family
from interview_coach.scorecard.models import QAItem

USER_AWAY_TIMEOUT = 25.0
MAX_KEYTERMS = 20

_FAMILY_TERMS = {
    "software": ["Kubernetes", "PostgreSQL", "microservices", "CI/CD", "API", "Docker", "Redis", "Kafka"],
    "data": ["SQL", "dbt", "Tableau", "A/B test", "Snowflake", "BigQuery", "pandas", "cohort"],
    "ai_ml": ["LLM", "RAG", "embeddings", "fine-tuning", "PyTorch", "evals", "precision", "recall"],
    "product": ["roadmap", "OKR", "MVP", "PRD", "retention", "activation", "churn", "stakeholders"],
    "design": ["Figma", "prototype", "usability", "accessibility", "WCAG", "design system", "wireframe"],
    "general": [],
}


def turn_handling() -> dict:
    """Patient turn-taking: wait through thinking pauses, ignore backchannels (spec §5.1)."""
    return {
        "endpointing": {"min_delay": 0.8, "max_delay": 6.0},
        "interruption": {
            "mode": "adaptive",
            "min_words": 2,
            "resume_false_interruption": True,
            "false_interruption_timeout": 1.5,
        },
        "preemptive_generation": {"enabled": True},
    }


def keyterms_for(role: str) -> list[str]:
    candidates = [t for t in re.findall(r"[A-Za-z][A-Za-z+#.]*", role) if len(t) >= 3]
    candidates += _FAMILY_TERMS[role_family(role)]
    seen: set[str] = set()
    terms = []
    for term in candidates:
        if term.lower() not in seen:
            seen.add(term.lower())
            terms.append(term)
    return terms[:MAX_KEYTERMS]


def segment_qa(plan: list[QuestionItem], analytics: SpeechAnalytics, asked: int) -> list[QAItem]:
    return [
        QAItem(
            index=i,
            question=plan[i].text,
            competency=plan[i].competency,
            transcript=" ".join(seg.text for seg in analytics.segments_for(i)),
            metrics=asdict(analytics.answer_metrics(i)),
        )
        for i in range(min(asked, len(plan)))
    ]


def completion_status(*, asked: int, total: int, reason: str) -> Literal["completed", "partial"]:
    return "completed" if reason == "completed" and asked >= total else "partial"


async def wait_until_quiet(
    agent_state: Callable[[], str], *, quiet_s: float = 1.5, timeout: float = 20.0, poll_s: float = 0.25
) -> bool:
    """Wait until the agent has been neither thinking nor speaking for `quiet_s` (the goodbye played).
    Returns False on timeout."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    quiet_since: float | None = None
    while loop.time() < deadline:
        if agent_state() in ("thinking", "speaking"):
            quiet_since = None
        else:
            quiet_since = quiet_since if quiet_since is not None else loop.time()
            if loop.time() - quiet_since >= quiet_s:
                return True
        await asyncio.sleep(poll_s)
    return False


class AwayPolicy:
    """Check in on a silent candidate at most once per question, not every timeout."""

    def __init__(self) -> None:
        self._checked: set[int] = set()

    def should_check_in(self, question_index: int) -> bool:
        if question_index in self._checked:
            return False
        self._checked.add(question_index)
        return True


class CompletionGuard:
    """end_interview, a disconnect and an STT failure can race; only the first one completes."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._done = False

    async def run_once(self, fn: Callable[[], Awaitable[None]]) -> bool:
        async with self._lock:
            if self._done:
                return False
            self._done = True
        await fn()
        return True
