"""Attention gate: the bot only listens when it's addressed.

`decide` is the pure decision. An utterance gets through when it starts with the wake phrase
("Chef, …"), arrives within the follow-up window after the bot spoke, follows a tap on the big
button, or is a bare stop word while the bot is talking. Everything else is overheard.
"""

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Literal

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

if TYPE_CHECKING:
    from kitchen_companion.events import EventSink

STOP_WORDS = ("stop", "wait", "quiet", "be quiet", "hold on", "pause")

# After an engaged line, the rest of the same utterance (a second STT final) still gets through.
CONTINUATION_S = 3.0

Reason = Literal["wake", "followup", "button", "stop_word", "not_addressed", "empty"]


@dataclass(frozen=True)
class AttentionConfig:
    wake_phrase: str = "chef"
    followup_window_s: float = 8.0


@dataclass(frozen=True)
class Decision:
    engaged: bool
    text: str
    reason: Reason


@lru_cache(maxsize=8)
def _wake_pattern(wake_phrase: str) -> re.Pattern[str]:
    wake = r"\s+".join(re.escape(w) for w in wake_phrase.split())
    return re.compile(rf"^\s*(?:(?:hey|hi|ok|okay|yo)[\s,]+)?{wake}(?!['’]s)\b[\s,.!?]*", re.IGNORECASE)


_STOP_RE = re.compile(
    r"^\s*(?:" + "|".join(re.escape(w) for w in STOP_WORDS) + r")(?:[\s,]+please)?[\s.!]*$", re.IGNORECASE
)


def decide(
    text: str,
    *,
    now: float,
    window_open_until: float,
    button_armed: bool,
    bot_speaking: bool,
    cfg: AttentionConfig,
) -> Decision:
    if not text or not text.strip():
        return Decision(False, text, "empty")
    m = _wake_pattern(cfg.wake_phrase).match(text)
    if m:
        return Decision(True, text[m.end():].strip(), "wake")
    if button_armed:
        return Decision(True, text, "button")
    if now <= window_open_until:
        return Decision(True, text, "followup")
    if bot_speaking and _STOP_RE.match(text):
        return Decision(True, text, "stop_word")
    return Decision(False, text, "not_addressed")


class AttentionGate(FrameProcessor):
    """Sits after STT: passes transcripts downstream only while the bot is being addressed.

    Overheard lines are dropped and reported to the UI. A bare wake phrase gets a "Yes?" and opens
    the follow-up window, as does the bot finishing a sentence.
    """

    def __init__(
        self,
        cfg: AttentionConfig,
        sink: "EventSink",
        clock: Callable[[], float] = time.monotonic,
        continuation_s: float = CONTINUATION_S,
    ):
        super().__init__()
        self._cfg = cfg
        self._sink = sink
        self._clock = clock
        self._continuation_s = continuation_s
        self._window_open_until = float("-inf")
        self._button_armed = False
        self.bot_speaking = False

    def arm_button(self) -> None:
        """The big "Hey Chef" button: the next utterance is addressed to the bot."""
        self._button_armed = True

    def open_window(self, seconds: float | None = None) -> None:
        span = self._cfg.followup_window_s if seconds is None else seconds
        self._window_open_until = self._clock() + span

    def _window_open(self) -> bool:
        return self._clock() <= self._window_open_until

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, BotStartedSpeakingFrame):
            self.bot_speaking = True
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self.bot_speaking = False
            self.open_window()

        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, TranscriptionFrame):
            await self._on_transcript(frame)
        elif direction == FrameDirection.DOWNSTREAM and isinstance(frame, InterimTranscriptionFrame):
            if self._window_open() or self._button_armed:
                await self.push_frame(frame, direction)
        else:
            await self.push_frame(frame, direction)

    async def _on_transcript(self, frame: TranscriptionFrame) -> None:
        now = self._clock()
        decision = decide(
            frame.text,
            now=now,
            window_open_until=self._window_open_until,
            button_armed=self._button_armed,
            bot_speaking=self.bot_speaking,
            cfg=self._cfg,
        )
        if not decision.engaged:
            if decision.reason != "empty":
                await self._sink.overheard(frame.text)
            return

        self._button_armed = False
        if not decision.text:
            await self.push_frame(TTSSpeakFrame("Yes?", append_to_context=False))
            self.open_window()
            return

        # STT may split one utterance into several finals; keep listening for the rest of it.
        self._window_open_until = max(self._window_open_until, now + self._continuation_s)
        await self._sink.heard(decision.text)
        await self.push_frame(
            TranscriptionFrame(
                text=decision.text,
                user_id=frame.user_id,
                timestamp=frame.timestamp,
                language=frame.language,
                result=frame.result,
                finalized=frame.finalized,
            )
        )
