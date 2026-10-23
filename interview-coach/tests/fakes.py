"""Test doubles shared across unit tests."""

from types import SimpleNamespace

from interview_coach.scorecard.models import (
    AnswerGrade,
    CoachingPlan,
    DimensionScores,
    GradedAnswer,
    QAItem,
    SessionInfo,
)

SESSION = SessionInfo(role="Data Analyst", level="junior", style="behavioral")
RUBRIC = {"structure": {"1": "a", "3": "b", "5": "c"}}


def scores(structure=4, specificity=4, impact=4, relevance=4, communication=4) -> DimensionScores:
    return DimensionScores(
        structure=structure,
        specificity=specificity,
        impact=impact,
        relevance=relevance,
        communication=communication,
    )


def grade(**dims) -> AnswerGrade:
    return AnswerGrade(
        scores=scores(**dims),
        strengths=["clear context"],
        improvements=["add a number"],
        evidence_quotes=["I led the migration"],
        one_line_verdict="Solid, needs a measurable result.",
    )


def ga(index: int, *positional, **dims) -> GradedAnswer:
    if positional:
        dims = dict(zip(["structure", "specificity", "impact", "relevance", "communication"], positional, strict=True))
    return GradedAnswer(index=index, grade=grade(**dims))


def qa(index: int, transcript: str) -> QAItem:
    return QAItem(index=index, question=f"Question {index}", competency="conflict", transcript=transcript)


def coaching() -> CoachingPlan:
    return CoachingPlan(
        top_fixes=["Lead with the result", "Quantify impact", "Say 'I', not 'we'"],
        rewritten_answer="Situation... Task... Action... Result...",
        practice_drill="Retell one story in 90 seconds with a number in the result.",
    )


class FakeGrader:
    def __init__(self, per_index: dict[int, dict] | None = None, fail: bool = False):
        self.per_index = per_index or {}
        self.fail = fail
        self.graded_indexes: list[int] = []
        self.coach_calls = 0

    async def grade(self, item, rubric, session):
        if self.fail:
            raise RuntimeError("grader exploded")
        self.graded_indexes.append(item.index)
        return grade(**self.per_index.get(item.index, {}))

    async def coach(self, items, graded, session):
        self.coach_calls += 1
        return coaching()


class FakeAnthropicClient:
    """Mimics `client.beta.messages.parse(...)` and records the request."""

    def __init__(self, refuse: bool = False):
        self.refuse = refuse
        self.last_kwargs: dict = {}
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._parse))

    async def _parse(self, **kwargs):
        self.last_kwargs = kwargs
        if self.refuse:
            return SimpleNamespace(stop_reason="refusal", parsed_output=None, stop_details=None)
        output_format = kwargs["output_format"]
        parsed = grade() if output_format is AnswerGrade else coaching()
        return SimpleNamespace(stop_reason="end_turn", parsed_output=parsed, stop_details=None)
