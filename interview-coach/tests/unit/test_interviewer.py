from livekit.agents import stt
from livekit.agents.types import TimedString

from interview_coach.agent.analytics import SpeechAnalytics
from interview_coach.agent.interviewer import Interviewer
from interview_coach.agent.prompts import InterviewSetup, interviewer_instructions
from interview_coach.mcp_server.bank import question_plan

SETUP = InterviewSetup(session_id="s_test", role="Data Analyst", level="junior", style="mixed", count=3)
PLAN3 = question_plan("Data Analyst", "junior", "mixed", 3, seed="s_test")


class Recorder:
    def __init__(self):
        self.calls = []

    async def __call__(self, value):
        self.calls.append(value)


def make_interviewer(analytics=None, plan=PLAN3, clock=lambda: 0.0, progress=None, finish=None):
    return Interviewer(
        setup=SETUP,
        plan=plan,
        analytics=analytics or SpeechAnalytics(),
        on_progress=progress or Recorder(),
        on_finish=finish or Recorder(),
        clock=clock,
    )


def test_instructions_content():
    s = interviewer_instructions(SETUP, 5)
    for needle in ("Data Analyst", "junior", "5", "Never give feedback", "at most two follow-ups",
                   "end_interview", "next_question", "not a follow-up"):
        assert needle in s


async def test_advance_marks_analytics_and_progress():
    a, prog = SpeechAnalytics(), Recorder()
    agent = make_interviewer(a, progress=prog, clock=lambda: 12.0)
    out = await agent.advance_question()
    assert out.startswith("Question 1 of 3")
    assert PLAN3[0].text in out
    assert prog.calls == [{"index": 0, "total": 3, "competency": PLAN3[0].competency}]
    assert agent.current_index == 0
    assert a.session_metrics().answers[0].index == 0


async def test_advance_past_end():
    agent = make_interviewer(plan=PLAN3[:1])
    await agent.advance_question()
    assert (await agent.advance_question()).startswith("NO_MORE_QUESTIONS")
    assert agent.current_index == 0


async def test_finish_idempotent():
    reasons = Recorder()
    agent = make_interviewer(finish=reasons)
    await agent.finish("completed")
    await agent.finish("timeout")
    assert reasons.calls == ["completed"]


async def test_final_transcript_feeds_analytics_in_wall_time():
    a = SpeechAnalytics()
    now = {"t": 98.0}
    agent = make_interviewer(a, clock=lambda: now["t"])
    await agent.advance_question()
    now["t"] = 100.0
    words = [TimedString("hello", start_time=1.0, end_time=1.4), TimedString("there", start_time=1.6, end_time=2.0)]
    agent.observe_final(stt.SpeechData(language="en", text="hello there", start_time=1.0, end_time=2.0, words=words))
    seg = a.segments_for(0)[0]
    assert (seg.text, seg.start, seg.end) == ("hello there", 99.0, 100.0)
    assert [(w.start, w.end) for w in seg.words] == [(99.0, 99.4), (99.6, 100.0)]


async def test_stream_offset_uses_smallest_observed_latency():
    a = SpeechAnalytics()
    now = {"t": 50.0}
    agent = make_interviewer(a, clock=lambda: now["t"])
    await agent.advance_question()
    now["t"] = 60.5  # first final arrives 0.5s after the audio ended
    agent.observe_final(stt.SpeechData(language="en", text="one", start_time=9.0, end_time=10.0))
    now["t"] = 70.2  # second arrives only 0.2s late, so the offset tightens from 50.5 to 50.2
    agent.observe_final(stt.SpeechData(language="en", text="two", start_time=19.0, end_time=20.0))
    second = a.segments_for(0)[1]
    assert (second.start, second.end) == (69.2, 70.2)
