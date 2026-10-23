"""The Interviewer agent: question progression via tools, speech analytics from STT (spec §5.2)."""

import inspect
import time
from collections.abc import AsyncIterable, Awaitable, Callable
from typing import Literal

from livekit import rtc
from livekit.agents import Agent, ModelSettings, RunContext, function_tool, stt
from livekit.agents.utils import is_given

from interview_coach.agent import speakable
from interview_coach.agent.analytics import Segment, SpeechAnalytics, Word
from interview_coach.agent.prompts import InterviewSetup, interviewer_instructions
from interview_coach.mcp_server.bank import QuestionItem

NO_MORE_QUESTIONS = (
    "NO_MORE_QUESTIONS: ask whether they have questions for you, answer briefly, "
    "then say goodbye and call end_interview with reason completed."
)


class Interviewer(Agent):
    def __init__(
        self,
        *,
        setup: InterviewSetup,
        plan: list[QuestionItem],
        analytics: SpeechAnalytics,
        on_progress: Callable[[dict], Awaitable[None]],
        on_finish: Callable[[str], Awaitable[None]],
        clock: Callable[[], float] = time.time,
    ) -> None:
        super().__init__(instructions=interviewer_instructions(setup, len(plan)))
        self._setup = setup
        self._plan = plan
        self._analytics = analytics
        self._on_progress = on_progress
        self._on_finish = on_finish
        self._clock = clock
        self._index = -1
        self._finished = False
        self._stream_offset: float | None = None  # wall-clock seconds at STT time zero

    @property
    def current_index(self) -> int:
        return self._index

    @property
    def total(self) -> int:
        return len(self._plan)

    async def advance_question(self) -> str:
        if self._index + 1 >= len(self._plan):
            return NO_MORE_QUESTIONS
        self._index += 1
        question = self._plan[self._index]
        self._analytics.start_question(self._index, self._clock())
        await self._on_progress(
            {"index": self._index, "total": len(self._plan), "competency": question.competency}
        )
        covers = ", ".join(question.good_answer_covers)
        return (
            f"Question {self._index + 1} of {len(self._plan)} ({question.competency}): {question.text}\n"
            f"A strong answer covers: {covers}. Ask it naturally, in your own words."
        )

    async def finish(self, reason: str) -> None:
        if self._finished:
            return
        self._finished = True
        await self._on_finish(reason)

    def observe_final(self, alt: stt.SpeechData) -> None:
        """Record a final transcript in wall-clock time.

        STT timestamps are relative to an internal audio start. A segment's audio ended no later
        than when its final arrives, so the smallest (arrival - end_time) seen so far is the best
        estimate of the offset; it only gets tighter as more finals arrive.
        """
        if not alt.text.strip():
            return
        offset = self._clock() - alt.end_time
        self._stream_offset = offset if self._stream_offset is None else min(self._stream_offset, offset)
        base = self._stream_offset
        words = tuple(
            Word(str(w), w.start_time + base, w.end_time + base)
            for w in (alt.words or [])
            if is_given(w.start_time) and is_given(w.end_time)
        )
        self._analytics.add_segment(Segment(alt.text, alt.start_time + base, alt.end_time + base, words))

    async def on_enter(self) -> None:
        self.session.generate_reply(
            instructions=(
                f"Greet the candidate warmly, say there are {len(self._plan)} questions and they can "
                "take their time, then call next_question."
            )
        )

    @function_tool
    async def next_question(self, context: RunContext) -> str:
        """Get the next interview question. Call it right after the greeting, and again once the
        current question and its follow-ups are done."""
        return await self.advance_question()

    @function_tool
    async def end_interview(
        self, context: RunContext, reason: Literal["completed", "candidate_requested", "timeout"]
    ) -> str:
        """End the interview: after the closing exchange, or when the candidate asks to stop."""
        await self.finish(reason)
        return "The interview is over. Say a brief, warm goodbye and nothing else."

    async def stt_node(
        self, audio: AsyncIterable[rtc.AudioFrame], model_settings: ModelSettings
    ) -> AsyncIterable[stt.SpeechEvent | str]:
        events = Agent.default.stt_node(self, audio, model_settings)
        if inspect.isawaitable(events):
            events = await events
        if events is None:
            return
        async for event in events:
            if (
                isinstance(event, stt.SpeechEvent)
                and event.type == stt.SpeechEventType.FINAL_TRANSCRIPT
                and event.alternatives
            ):
                self.observe_final(event.alternatives[0])
            yield event

    def tts_node(self, text: AsyncIterable[str], model_settings: ModelSettings):
        return Agent.default.tts_node(self, speakable.normalize_stream(text), model_settings)
