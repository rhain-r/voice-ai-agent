from interview_coach.agent.analytics import (
    Segment,
    SpeechAnalytics,
    Word,
    count_fillers,
    count_tics,
    pace_band,
)


def test_basic_answer_metrics():
    a = SpeechAnalytics()
    a.start_question(0, at=0.0)
    a.add_agent_speech(0.0, 4.0)
    a.add_segment(Segment("um so I led the migration", 7.0, 10.0))
    m = a.answer_metrics(0)
    assert (m.word_count, m.filler_count, round(m.wpm), m.thinking_time_s) == (6, 1, 120, 3.0)


def test_pause_ignored_when_agent_spoke_in_gap():
    a = SpeechAnalytics()
    a.start_question(0, at=0.0)
    a.add_segment(Segment("first part", 1.0, 2.0))
    a.add_agent_speech(2.5, 6.0)
    a.add_segment(Segment("second part", 7.0, 8.0))
    assert a.answer_metrics(0).longest_pause_s == 0.0


def test_long_pause_counted():
    a = SpeechAnalytics()
    a.start_question(0, at=0.0)
    a.add_segment(Segment("first", 1.0, 2.0))
    a.add_segment(Segment("second", 5.5, 6.0))
    m = a.answer_metrics(0)
    assert (m.longest_pause_s, m.pauses_over_3s) == (3.5, 1)


def test_word_level_pauses_used_when_present():
    a = SpeechAnalytics()
    a.start_question(0, at=0.0)
    words = (Word("I", 1.0, 1.2), Word("think", 4.6, 5.0))
    a.add_segment(Segment("I think", 1.0, 5.0, words=words))
    assert a.answer_metrics(0).longest_pause_s == 3.4


def test_tics_and_pace_band():
    assert count_tics("it was like, you know, basically fine") == {"like": 1, "you know": 1, "basically": 1}
    assert [pace_band(x) for x in (0, 100, 140, 200)] == ["n/a", "slow", "conversational", "fast"]


def test_count_fillers_whole_words_only():
    assert count_fillers("Um, uh, hmm... the error was umm in the order") == 4


def test_answer_with_no_segments():
    a = SpeechAnalytics()
    a.start_question(0, at=0.0)
    m = a.answer_metrics(0)
    assert (m.word_count, m.wpm, m.pace_band, m.thinking_time_s) == (0, 0.0, "n/a", None)


def test_segments_attributed_to_current_question_and_talk_ratio():
    a = SpeechAnalytics()
    a.add_segment(Segment("ignored", 0, 1))
    a.start_question(0, 1.0)
    a.add_agent_speech(1.0, 3.0)
    a.add_segment(Segment("one two", 4.0, 6.0))
    a.start_question(1, 7.0)
    a.add_segment(Segment("three", 8.0, 9.0))
    assert [s.text for s in a.segments_for(0)] == ["one two"]
    assert round(a.session_metrics().talk_ratio, 2) == 0.6


def test_end_questions_stops_attribution():
    a = SpeechAnalytics()
    a.start_question(0, 1.0)
    a.add_segment(Segment("my answer", 2.0, 3.0))
    a.end_questions(at=10.0)
    a.add_segment(Segment("do you have a remote policy", 11.0, 13.0))
    assert [s.text for s in a.segments_for(0)] == ["my answer"]
    assert (a.asked_at(0), a.asked_at(1), a.closed_at) == (1.0, None, 10.0)
    assert len(a.session_metrics().answers) == 1


def test_session_metrics_empty_is_zero():
    s = SpeechAnalytics().session_metrics()
    assert (s.answers, s.avg_wpm, s.talk_ratio, s.avg_thinking_time_s) == ([], 0.0, 0.0, None)
