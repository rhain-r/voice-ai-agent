from interview_coach.agent.analytics import Segment, SpeechAnalytics
from interview_coach.agent.session_config import (
    AwayPolicy,
    CompletionGuard,
    completion_status,
    keyterms_for,
    segment_qa,
    turn_handling,
    wait_until_quiet,
)
from interview_coach.mcp_server.bank import question_plan


def test_turn_handling_values():
    th = turn_handling()
    assert th["endpointing"] == {"min_delay": 0.8, "max_delay": 6.0}
    assert th["interruption"] == {
        "mode": "adaptive",
        "min_words": 2,
        "resume_false_interruption": True,
        "false_interruption_timeout": 1.5,
    }
    assert th["preemptive_generation"] == {"enabled": True}


def test_keyterms_capped_and_family_aware():
    terms = keyterms_for("Senior Software Engineer")
    assert len(terms) <= 20 and "Kubernetes" in terms and "Software" in terms
    assert len(terms) == len(set(terms))


def test_keyterms_for_general_role_has_role_tokens():
    assert keyterms_for("Pastry Chef") == ["Pastry", "Chef"]


def test_segment_qa_joins_text():
    plan = question_plan("Data Analyst", "junior", "behavioral", 2, "s")
    a = SpeechAnalytics()
    a.start_question(0, 0.0)
    a.add_segment(Segment("one", 1.0, 2.0))
    a.add_segment(Segment("two", 2.5, 3.0))
    a.start_question(1, 4.0)
    a.add_segment(Segment("three", 5.0, 6.0))
    items = segment_qa(plan, a, asked=2)
    assert [(i.index, i.transcript, i.question) for i in items] == [
        (0, "one two", plan[0].text),
        (1, "three", plan[1].text),
    ]
    assert items[0].metrics["word_count"] == 2


def test_segment_qa_includes_asked_but_unanswered():
    plan = question_plan("Data Analyst", "junior", "behavioral", 3, "s")
    a = SpeechAnalytics()
    a.start_question(0, 0.0)
    items = segment_qa(plan, a, asked=1)
    assert len(items) == 1 and items[0].transcript == ""


def test_completion_status():
    assert completion_status(asked=5, total=5, reason="completed") == "completed"
    assert completion_status(asked=3, total=5, reason="completed") == "partial"
    assert completion_status(asked=5, total=5, reason="disconnected") == "partial"


def test_away_checkin_once_per_question():
    p = AwayPolicy()
    assert [p.should_check_in(0), p.should_check_in(0), p.should_check_in(1)] == [True, False, True]


async def test_wait_until_quiet_waits_for_speech_to_end():
    states = iter(["thinking", "speaking", "speaking", "listening", "listening", "listening", "listening"])
    seen = []

    def state():
        seen.append(next(states, "listening"))
        return seen[-1]

    assert await wait_until_quiet(state, quiet_s=0.02, timeout=2.0, poll_s=0.01)
    assert seen[:4] == ["thinking", "speaking", "speaking", "listening"]


async def test_wait_until_quiet_times_out():
    assert not await wait_until_quiet(lambda: "speaking", quiet_s=0.01, timeout=0.05, poll_s=0.01)


async def test_completion_fires_once():
    g = CompletionGuard()
    n = []

    async def f():
        n.append(1)

    assert await g.run_once(f)
    assert not await g.run_once(f)
    assert n == [1]
