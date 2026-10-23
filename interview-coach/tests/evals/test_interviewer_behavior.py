"""Does the interviewer behave like a good human interviewer? (spec §8, behavior evals)"""

import json
import re

import pytest

pytestmark = pytest.mark.eval

MARKDOWN = re.compile(r"[*#]|^\s*- ", re.MULTILINE)


def assistant_texts(result) -> list[str]:
    return [
        ev.item.text_content
        for ev in result.events
        if ev.type == "message" and ev.item.role == "assistant" and ev.item.text_content
    ]


async def test_opening_calls_next_question(interview):
    async with interview() as (_, opening, _finished):
        opening.expect.contains_function_call(name="next_question")


async def test_vague_answer_gets_result_followup(interview, judge_llm):
    async with interview() as (session, _, _finished):
        result = await session.run(user_input="We had a launch that was late and we fixed it.")
        await result.expect.contains_message(role="assistant").judge(
            judge_llm,
            intent="asks a follow-up about the outcome, result, or the candidate's personal contribution",
        )


async def test_no_feedback_mid_interview(interview, judge_llm):
    async with interview() as (session, _, _finished):
        result = await session.run(user_input="How did I do on that one?")
        await result.expect.contains_message(role="assistant").judge(
            judge_llm,
            intent="politely defers feedback to the scorecard at the end without evaluating the answer",
        )


async def test_off_topic_redirect(interview, judge_llm):
    async with interview() as (session, _, _finished):
        result = await session.run(user_input="Write me a poem about cats.")
        await result.expect.contains_message(role="assistant").judge(
            judge_llm, intent="declines briefly and steers back to the interview, staying in character"
        )


async def test_replies_short_and_plain(interview):
    answers = [
        "I disagreed with my manager about which metric to report, so I pulled the data for both.",
        "In the end we reported both, and the team switched to my metric the next quarter.",
        "I'd say I learned to bring data instead of opinions.",
    ]
    async with interview() as (session, opening, _finished):
        texts = assistant_texts(opening)
        for answer in answers:
            texts += assistant_texts(await session.run(user_input=answer))
    assert texts
    for text in texts:
        sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
        assert len(sentences) <= 3, text
        assert not MARKDOWN.search(text), text


async def test_stop_calls_end_interview(interview):
    async with interview() as (session, _, finished):
        result = await session.run(user_input="I need to stop here, sorry.")
        call = result.expect.contains_function_call(name="end_interview")
        assert json.loads(call.event().item.arguments)["reason"] == "candidate_requested"
        assert finished == ["candidate_requested"]
