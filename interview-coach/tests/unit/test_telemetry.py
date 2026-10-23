from livekit.agents.metrics import EOUMetrics, LLMMetrics, TTSMetrics

from interview_coach.agent.telemetry import LatencyTracker


def eou(speech_id, delay):
    return EOUMetrics(
        timestamp=0,
        end_of_utterance_delay=delay,
        transcription_delay=0.1,
        on_user_turn_completed_delay=0,
        speech_id=speech_id,
    )


def llm(speech_id, ttft):
    return LLMMetrics(
        label="llm",
        request_id="r",
        timestamp=0,
        duration=1,
        ttft=ttft,
        cancelled=False,
        completion_tokens=1,
        prompt_tokens=1,
        prompt_cached_tokens=0,
        total_tokens=2,
        tokens_per_second=1,
        speech_id=speech_id,
    )


def tts(speech_id, ttfb):
    return TTSMetrics(
        label="tts",
        request_id="r",
        timestamp=0,
        ttfb=ttfb,
        duration=1,
        audio_duration=1,
        cancelled=False,
        characters_count=10,
        streamed=True,
        speech_id=speech_id,
    )


def test_tracker_groups_by_speech_id():
    got = []
    t = LatencyTracker(on_turn=got.append)
    t.observe(eou("s1", 0.4))
    t.observe(llm("s1", 0.5))
    assert got == []
    t.observe(tts("s1", 0.2))
    assert len(got) == 1 and got[0].total_ms == 1100
    assert (got[0].eou_delay_ms, got[0].llm_ttft_ms, got[0].tts_ttfb_ms) == (400, 500, 200)


def test_tracker_emits_once_per_turn():
    got = []
    t = LatencyTracker(on_turn=got.append)
    for m in (eou("s1", 0.4), llm("s1", 0.5), tts("s1", 0.2), tts("s1", 0.9), llm("s1", 2.0)):
        t.observe(m)
    assert len(got) == 1 and len(t.turns()) == 1


def test_tracker_ignores_metrics_without_speech_id():
    t = LatencyTracker()
    t.observe(llm(None, 0.5))
    assert t.turns() == []


def test_tracker_summary_percentiles():
    t = LatencyTracker()
    for i, total in enumerate([800, 1000, 1200, 3000]):
        sid = f"s{i}"
        t.observe(eou(sid, total / 1000))
        t.observe(llm(sid, 0))
        t.observe(tts(sid, 0))
    assert t.summary() == {"p50_ms": 1000, "p95_ms": 3000, "turns": 4}


def test_tracker_summary_empty():
    assert LatencyTracker().summary() == {"p50_ms": 0, "p95_ms": 0, "turns": 0}
