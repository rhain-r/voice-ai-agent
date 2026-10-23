"""Events for the tablet UI (RTVI server messages) and end-of-speech-to-first-audio latency."""

from collections.abc import Awaitable, Callable
from typing import Literal, Protocol

from pipecat.frames.frames import BotStartedSpeakingFrame, Frame, VADUserStoppedSpeakingFrame
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.processors.frameworks.rtvi import RTVIServerMessageFrame

Path = Literal["fast", "llm"]


class EventSink(Protocol):
    async def heard(self, text: str) -> None: ...
    async def overheard(self, text: str) -> None: ...
    async def latency(self, path: Path, ms: int) -> None: ...
    async def recipe_state(self, snapshot: dict) -> None: ...
    async def timers(self, snapshot: list[dict]) -> None: ...
    async def error(self, message: str) -> None: ...


class RTVIEventSink:
    """Sends each event to the client as `RTVIServerMessageFrame(data={"type": <event>, ...})`."""

    def __init__(self, push: Callable[[Frame], Awaitable[None]]):
        self._push = push

    async def _send(self, kind: str, **fields) -> None:
        await self._push(RTVIServerMessageFrame(data={"type": kind, **fields}))

    async def heard(self, text: str) -> None:
        await self._send("heard", text=text)

    async def overheard(self, text: str) -> None:
        await self._send("overheard", text=text)

    async def latency(self, path: Path, ms: int) -> None:
        await self._send("latency", path=path, ms=ms)

    async def recipe_state(self, snapshot: dict) -> None:
        await self._send("recipe_state", recipe=snapshot)

    async def timers(self, snapshot: list[dict]) -> None:
        await self._send("timers", timers=snapshot)

    async def error(self, message: str) -> None:
        await self._send("error", message=message)


class TurnPath:
    """Which path answered the current turn; the fast-path router flips it, the latency observer resets it."""

    def __init__(self) -> None:
        self.value: Path = "llm"


class LatencyClock:
    """Milliseconds from the end of the user's speech to the bot's first audio, once per user turn."""

    def __init__(self, max_ms: int = 15_000) -> None:
        self._stopped_at: float | None = None
        self._max_ms = max_ms

    def user_stopped(self, t: float) -> None:
        self._stopped_at = t

    def bot_started(self, t: float) -> int | None:
        if self._stopped_at is None:
            return None
        ms = round((t - self._stopped_at) * 1000)
        self._stopped_at = None
        # Bot speech long after the last utterance (e.g. a timer going off) isn't a reply to it.
        return ms if 0 <= ms <= self._max_ms else None


class LatencyObserver(BaseObserver):
    def __init__(self, clock: LatencyClock, path: TurnPath, sink: EventSink):
        super().__init__(observe_every_push=False)
        self._clock = clock
        self._path = path
        self._sink = sink

    async def on_push_frame(self, data: FramePushed) -> None:
        t = data.timestamp / 1e9
        if isinstance(data.frame, VADUserStoppedSpeakingFrame):
            self._clock.user_stopped(t)
        elif isinstance(data.frame, BotStartedSpeakingFrame):
            ms = self._clock.bot_started(t)
            if ms is not None:
                await self._sink.latency(self._path.value, ms)
                self._path.value = "llm"
