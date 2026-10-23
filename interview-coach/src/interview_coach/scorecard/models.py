"""Scorecard data shapes (spec §5.7). AnswerGrade and CoachingPlan double as Claude's output schemas."""

from pydantic import BaseModel, Field


class SessionInfo(BaseModel):
    role: str
    level: str
    style: str


class QAItem(BaseModel):
    """One question plus the whole exchange until the next question (follow-ups included)."""

    index: int
    question: str
    competency: str
    transcript: str = Field(description="The candidate's words only")
    metrics: dict = Field(default_factory=dict)
    style: str = "behavioral"
    dialogue: str = Field(default="", description="Interviewer and candidate lines, follow-ups included")
    skipped: bool = False


class DimensionScores(BaseModel):
    structure: int = Field(ge=1, le=5, description="STAR structure (or approach, for technical answers)")
    specificity: int = Field(ge=1, le=5)
    impact: int = Field(ge=1, le=5)
    relevance: int = Field(ge=1, le=5)
    communication: int = Field(ge=1, le=5)


class AnswerGrade(BaseModel):
    scores: DimensionScores
    strengths: list[str] = Field(max_length=2, description="At most two")
    improvements: list[str] = Field(max_length=2, description="At most two")
    evidence_quotes: list[str] = Field(description="Short verbatim excerpts of the candidate's own words")
    one_line_verdict: str


class CoachingPlan(BaseModel):
    top_fixes: list[str] = Field(min_length=3, max_length=3, description="Exactly three")
    rewritten_answer: str = Field(
        description="The weakest answer rewritten in STAR form, using only facts given"
    )
    practice_drill: str


class GradedAnswer(BaseModel):
    index: int
    grade: AnswerGrade


class Scorecard(BaseModel):
    overall: int
    dimension_averages: dict[str, float]
    weakest_dimension: str
    best_index: int
    weakest_index: int
    skipped: list[int]
    graded: list[GradedAnswer]
    coaching: CoachingPlan
