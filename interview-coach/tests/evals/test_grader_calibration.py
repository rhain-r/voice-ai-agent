"""Grader calibration: a known strong answer must clearly outscore a known weak one (spec §8)."""

import asyncio
import json
from pathlib import Path
from statistics import mean

import anthropic
import pytest

from interview_coach.mcp_server.bank import rubric
from interview_coach.scorecard.graph import ClaudeGrader, aggregate
from interview_coach.scorecard.models import GradedAnswer, QAItem, SessionInfo

pytestmark = pytest.mark.eval

PAIRS = json.loads((Path(__file__).parent / "fixtures" / "answers.json").read_text(encoding="utf-8"))
SESSION = SessionInfo(role="Data Analyst", level="mid", style="behavioral")
RUNS = 3
MIN_GAP = 15


async def overall(grader: ClaudeGrader, pair: dict, answer: str) -> int:
    item = QAItem(index=0, question=pair["question"], competency=pair["competency"], transcript=answer)
    grade = await grader.grade(item, rubric("behavioral"), SESSION)
    return aggregate([GradedAnswer(index=0, grade=grade)])["overall"]


@pytest.mark.parametrize("pair", PAIRS, ids=[p["competency"] for p in PAIRS])
async def test_strong_beats_weak(pair):
    grader = ClaudeGrader(anthropic.AsyncAnthropic())
    strong = await asyncio.gather(*(overall(grader, pair, pair["strong"]) for _ in range(RUNS)))
    weak = await asyncio.gather(*(overall(grader, pair, pair["weak"]) for _ in range(RUNS)))
    assert mean(strong) - mean(weak) >= MIN_GAP, (strong, weak)
