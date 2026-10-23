import pytest

from interview_coach.mcp_server.bank import rubric as bank_rubric
from interview_coach.scorecard.graph import (
    ClaudeGrader,
    GradingRefused,
    NothingToGrade,
    aggregate,
    is_non_answer,
    run_scorecard,
)
from tests.fakes import RUBRIC, SESSION, FakeAnthropicClient, FakeGrader, ga, qa


def test_aggregate_all_fives_is_100():
    assert aggregate([ga(0, 5, 5, 5, 5, 5)])["overall"] == 100


def test_aggregate_all_ones_is_0():
    assert aggregate([ga(0, 1, 1, 1, 1, 1)])["overall"] == 0


def test_aggregate_weighted():
    r = aggregate([ga(0, structure=5, specificity=3, impact=1, relevance=3, communication=3)])
    assert r["overall"] == 50 and r["weakest_dimension"] == "impact"


def test_aggregate_best_and_weakest_answer():
    r = aggregate([ga(0, 3, 3, 3, 3, 3), ga(1, 5, 5, 5, 5, 5), ga(2, 1, 2, 1, 2, 2)])
    assert (r["best_index"], r["weakest_index"]) == (1, 2)
    assert r["dimension_averages"]["structure"] == 3.0


async def test_graph_grades_each_answer_once():
    g = FakeGrader()
    sc = await run_scorecard(g, SESSION, [qa(0, "a"), qa(1, "b"), qa(2, "c")], RUBRIC)
    assert sorted(g.graded_indexes) == [0, 1, 2] and len(sc.graded) == 3 and g.coach_calls == 1
    assert [x.index for x in sc.graded] == [0, 1, 2]


async def test_skipped_answers_not_graded():
    sc = await run_scorecard(FakeGrader(), SESSION, [qa(0, "real answer"), qa(1, "  ")], RUBRIC)
    assert sc.skipped == [1] and [x.index for x in sc.graded] == [0]


async def test_all_skipped_raises():
    with pytest.raises(NothingToGrade):
        await run_scorecard(FakeGrader(), SESSION, [qa(0, "")], RUBRIC)


async def test_spoken_skip_not_graded():
    items = [
        qa(0, "I led the migration and cut costs by a third"),
        qa(1, "Pass."),
        qa(2, "Um, I'd rather skip this one."),
    ]
    sc = await run_scorecard(FakeGrader(), SESSION, items, RUBRIC)
    assert sc.skipped == [1, 2] and [g.index for g in sc.graded] == [0]


@pytest.mark.parametrize(
    "text,skip",
    [
        ("Pass", True),
        ("I don't know.", True),
        ("Can we move on to the next question?", True),
        ("uh, hmm", True),
        ("I passed the certification in a month and then led the rollout", False),
        ("I don't know the exact number, but revenue grew about twenty percent after I shipped it", False),
    ],
)
def test_is_non_answer(text, skip):
    assert is_non_answer(text) is skip


async def test_flagged_skip_not_graded():
    items = [
        qa(0, "a real answer"),
        qa(1, "something they said before skipping").model_copy(update={"skipped": True}),
    ]
    sc = await run_scorecard(FakeGrader(), SESSION, items, RUBRIC)
    assert sc.skipped == [1]


async def test_rubric_chosen_per_question_style():
    g = FakeGrader()
    items = [
        qa(0, "behavioral answer").model_copy(update={"style": "behavioral"}),
        qa(1, "technical answer").model_copy(update={"style": "technical"}),
    ]
    await run_scorecard(g, SESSION, items, bank_rubric)
    assert g.rubrics[0]["structure"] == bank_rubric("behavioral")["structure"]
    assert g.rubrics[1]["structure"] == bank_rubric("technical")["structure"]


async def test_coach_receives_weakest_index():
    g = FakeGrader(per_index={1: {"impact": 1, "structure": 1}})
    await run_scorecard(g, SESSION, [qa(0, "a"), qa(1, "b"), qa(2, "c")], RUBRIC)
    assert g.coach_weakest == 1


async def test_claude_grader_sends_dialogue_when_present():
    c = FakeAnthropicClient()
    item = qa(0, "candidate only").model_copy(
        update={"dialogue": "Interviewer: What happened?\nCandidate: candidate only"}
    )
    await ClaudeGrader(c).grade(item, RUBRIC, SESSION)
    content = c.last_kwargs["messages"][0]["content"]
    assert "Interviewer: What happened?" in content


async def test_claude_coach_names_weakest_answer():
    c = FakeAnthropicClient()
    await ClaudeGrader(c).coach([qa(0, "x"), qa(1, "y")], [ga(0), ga(1)], SESSION, weakest_index=1)
    assert "rewrite Q2" in c.last_kwargs["messages"][0]["content"]


async def test_claude_grader_refusal_raises():
    with pytest.raises(GradingRefused):
        await ClaudeGrader(FakeAnthropicClient(refuse=True)).grade(qa(0, "x"), RUBRIC, SESSION)


async def test_claude_grader_request_shape():
    c = FakeAnthropicClient()
    await ClaudeGrader(c).grade(qa(0, "x"), RUBRIC, SESSION)
    kw = c.last_kwargs
    assert kw["model"] == "claude-opus-5-5" and kw["fallbacks"] == "default"
    assert kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert kw["output_config"] == {"effort": "high"}
    assert "temperature" not in kw and "thinking" not in kw and "tool_choice" not in kw


async def test_claude_grader_coach_returns_plan():
    plan = await ClaudeGrader(FakeAnthropicClient()).coach([qa(0, "x")], [ga(0)], SESSION, weakest_index=0)
    assert len(plan.top_fixes) == 3
