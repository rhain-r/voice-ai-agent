from pipecat.frames.frames import BotStartedSpeakingFrame, VADUserStoppedSpeakingFrame
from pipecat.observers.base_observer import FramePushed
from pipecat.processors.frame_processor import FrameDirection
from pipecat.processors.frameworks.rtvi import RTVIServerMessageFrame

from kitchen_companion.events import LatencyClock, LatencyObserver, RTVIEventSink, TurnPath
from tests.fakes import make_sink


def test_latency_clock_once_per_turn():
    c = LatencyClock()
    c.user_stopped(1.0)
    assert c.bot_started(1.4) == 400 and c.bot_started(2.0) is None


def test_latency_clock_ignores_bot_speech_without_user_turn():
    assert LatencyClock().bot_started(5.0) is None


def test_latency_clock_drops_stale_turns():
    c = LatencyClock()
    c.user_stopped(1.0)
    assert c.bot_started(40.0) is None  # an overheard line long ago, then a timer announcement


def pushed(frame, t_s: float) -> FramePushed:
    return FramePushed(
        source=None,
        destination=None,
        frame=frame,
        direction=FrameDirection.DOWNSTREAM,
        timestamp=int(t_s * 1e9),
    )


async def test_latency_observer_reports_and_resets_path():
    sink, path = make_sink(), TurnPath()
    obs = LatencyObserver(LatencyClock(), path, sink)
    assert obs.observe_every_push is False
    path.value = "fast"
    await obs.on_push_frame(pushed(VADUserStoppedSpeakingFrame(), 10.0))
    await obs.on_push_frame(pushed(BotStartedSpeakingFrame(), 10.28))
    await obs.on_push_frame(pushed(BotStartedSpeakingFrame(), 10.29))  # the upstream copy
    assert sink.latencies == [("fast", 280)]
    assert path.value == "llm"


async def test_rtvi_event_sink_pushes_server_messages():
    sent = []

    async def push(frame):
        sent.append(frame)

    sink = RTVIEventSink(push)
    await sink.heard("next")
    await sink.overheard("mom")
    await sink.latency("fast", 280)
    await sink.recipe_state({"index": 1})
    await sink.timers([{"id": "t1"}])
    await sink.error("oops")
    assert all(isinstance(f, RTVIServerMessageFrame) for f in sent)
    assert [f.data for f in sent] == [
        {"type": "heard", "text": "next"},
        {"type": "overheard", "text": "mom"},
        {"type": "latency", "path": "fast", "ms": 280},
        {"type": "recipe_state", "recipe": {"index": 1}},
        {"type": "timers", "timers": [{"id": "t1"}]},
        {"type": "error", "message": "oops"},
    ]
