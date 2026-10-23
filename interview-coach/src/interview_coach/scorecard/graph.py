"""Post-interview scorecard: a LangGraph map-reduce over answers (spec §5.7).

START → fan_out (one Send per answered question) → grade_answer → aggregate → coach → END
"""

import json
import operator
import re
from collections.abc import Callable
from statistics import mean
from typing import Annotated, Any, Protocol, TypedDict

import anthropic
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from interview_coach.scorecard.models import (
    AnswerGrade,
    CoachingPlan,
    GradedAnswer,
    QAItem,
    Scorecard,
    SessionInfo,
)

WEIGHTS = {"structure": 1.5, "impact": 1.5, "specificity": 1.0, "relevance": 1.0, "communication": 1.0}

Rubric = dict | Callable[[str], dict]

_WORDS = re.compile(r"[a-z']+")
_FILLERS = {"um", "umm", "uh", "uhm", "er", "erm", "hmm", "so", "well", "sorry", "actually"}
_DECLINE = re.compile(
    r"\b(pass|skip|move on|next question|i don'?t know|no idea|rather not|can'?t think of)\b"
)
_MAX_DECLINE_WORDS = 8


class Grader(Protocol):
    async def grade(self, item: QAItem, rubric: dict, session: SessionInfo) -> AnswerGrade: ...

    async def coach(
        self, items: list[QAItem], graded: list[GradedAnswer], session: SessionInfo, weakest_index: int
    ) -> CoachingPlan: ...


class GradingRefused(RuntimeError):
    pass


class NothingToGrade(ValueError):
    """Every question was skipped or unanswered; a terminal state, not a failure to retry."""


def is_non_answer(transcript: str) -> bool:
    """A short decline ("pass", "I'd rather skip this one") is a skip, not a 1/5 answer."""
    words = [w for w in _WORDS.findall(transcript.lower()) if w not in _FILLERS]
    if not words:
        return True
    return len(words) <= _MAX_DECLINE_WORDS and bool(_DECLINE.search(" ".join(words)))


_GRADE_SYSTEM = (
    "You are a rigorous, fair interview coach. Grade one interview answer against the rubric. "
    "Score each dimension 1-5 using the anchors. Give at most two strengths and at most two "
    "improvements, each one short sentence. Evidence quotes must be short excerpts of words the "
    "candidate actually said; never invent or paraphrase them, and never quote the interviewer. "
    "The transcript comes from speech recognition, so ignore filler words and minor recognition "
    "errors. Judge the answer as finally developed, including what the candidate added in response "
    "to follow-up questions."
)
_COACH_SYSTEM = (
    "You are an interview coach writing a short coaching plan after a mock interview. Give exactly "
    "three fixes, most important first, each one actionable sentence. Rewrite the answer you are "
    "told is weakest in STAR form (situation, task, action, result) using only facts the candidate "
    "gave; where a fact is missing, write a bracketed placeholder like [number] instead of inventing "
    "it. End with one practice drill the candidate can do in under ten minutes."
)


class ClaudeGrader:
    """Grades with Claude Opus 5.5 via structured outputs; server-side fallback on refusal."""

    def __init__(self, client: Any, model: str = "claude-opus-5-5"):
        self._client = client
        self._model = model

    async def _parse(self, output_format: type, system: str, content: str):
        response = await self._client.beta.messages.parse(
            model=self._model,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "high"},
            output_format=output_format,
            system=system,
            messages=[{"role": "user", "content": content}],
        )
        if response.stop_reason == "refusal":
            raise GradingRefused(f"grader declined: {getattr(response, 'stop_details', None)}")
        if response.parsed_output is None:
            raise RuntimeError(f"grader returned no structured output (stop_reason={response.stop_reason})")
        return response.parsed_output

    async def grade(self, item: QAItem, rubric: dict, session: SessionInfo) -> AnswerGrade:
        exchange = (
            f"Interview exchange for this question, follow-ups included:\n{item.dialogue}"
            if item.dialogue
            else f"Candidate transcript:\n{item.transcript}"
        )
        content = (
            f"Role: {session.role} ({session.level}). Question style: {item.style}.\n"
            f"Question: {item.question}\nCompetency: {item.competency}\n"
            f"Rubric anchors:\n{json.dumps(rubric, indent=2)}\n\n{exchange}"
        )
        return await self._parse(AnswerGrade, _GRADE_SYSTEM, content)

    async def coach(
        self, items: list[QAItem], graded: list[GradedAnswer], session: SessionInfo, weakest_index: int
    ) -> CoachingPlan:
        grades = {g.index: g.grade for g in graded}
        blocks = []
        for item in items:
            g = grades.get(item.index)
            verdict = g.one_line_verdict if g else "skipped"
            blocks.append(
                f"Q{item.index + 1}: {item.question}\nAnswer: {item.transcript}\nVerdict: {verdict}"
            )
        content = (
            f"Role: {session.role} ({session.level}).\n\n"
            + "\n\n".join(blocks)
            + f"\n\nThe weakest answer is Q{weakest_index + 1}: rewrite Q{weakest_index + 1}."
        )
        return await self._parse(CoachingPlan, _COACH_SYSTEM, content)

    @classmethod
    def from_env(cls, model: str = "claude-opus-5-5") -> "ClaudeGrader":
        return cls(anthropic.AsyncAnthropic(), model)


def _weighted(scores: dict[str, int]) -> float:
    return sum(scores[d] * w for d, w in WEIGHTS.items()) / sum(WEIGHTS.values())


def aggregate(graded: list[GradedAnswer]) -> dict:
    per_answer = {g.index: _weighted(g.grade.scores.model_dump()) for g in graded}
    averages = {d: round(mean(g.grade.scores.model_dump()[d] for g in graded), 2) for d in WEIGHTS}
    return {
        "overall": round((mean(per_answer.values()) - 1) / 4 * 100),
        "dimension_averages": averages,
        "weakest_dimension": min(WEIGHTS, key=lambda d: averages[d]),
        "best_index": max(per_answer, key=lambda i: per_answer[i]),
        "weakest_index": min(per_answer, key=lambda i: per_answer[i]),
    }


class _State(TypedDict, total=False):
    session: SessionInfo
    items: list[QAItem]
    rubric: Rubric
    graded: Annotated[list[GradedAnswer], operator.add]
    summary: dict
    coaching: CoachingPlan


def _rubric_for(rubric: Rubric, item: QAItem) -> dict:
    return rubric(item.style) if callable(rubric) else rubric


def build_graph(grader: Grader):
    def fan_out(state: _State) -> list[Send]:
        return [
            Send(
                "grade_answer",
                {"item": item, "rubric": _rubric_for(state["rubric"], item), "session": state["session"]},
            )
            for item in state["items"]
        ]

    async def grade_answer(payload: dict) -> dict:
        grade = await grader.grade(payload["item"], payload["rubric"], payload["session"])
        return {"graded": [GradedAnswer(index=payload["item"].index, grade=grade)]}

    def aggregate_node(state: _State) -> dict:
        return {"summary": aggregate(state["graded"])}

    async def coach_node(state: _State) -> dict:
        graded = sorted(state["graded"], key=lambda g: g.index)
        coaching = await grader.coach(
            state["items"], graded, state["session"], state["summary"]["weakest_index"]
        )
        return {"coaching": coaching}

    builder = StateGraph(_State)
    builder.add_node("grade_answer", grade_answer)
    builder.add_node("aggregate", aggregate_node)
    builder.add_node("coach", coach_node)
    builder.add_conditional_edges(START, fan_out, ["grade_answer"])
    builder.add_edge("grade_answer", "aggregate")
    builder.add_edge("aggregate", "coach")
    builder.add_edge("coach", END)
    return builder.compile()


async def run_scorecard(
    grader: Grader, session: SessionInfo, items: list[QAItem], rubric: Rubric
) -> Scorecard:
    """`rubric` is one rubric for every answer, or a function of the question's style."""
    answered = [item for item in items if not item.skipped and not is_non_answer(item.transcript)]
    answered_ids = {item.index for item in answered}
    skipped = [item.index for item in items if item.index not in answered_ids]
    if not answered:
        raise NothingToGrade("no answers to grade")
    result = await build_graph(grader).ainvoke(
        {"session": session, "items": answered, "rubric": rubric, "graded": []}
    )
    return Scorecard(
        **result["summary"],
        skipped=skipped,
        graded=sorted(result["graded"], key=lambda g: g.index),
        coaching=result["coaching"],
    )
