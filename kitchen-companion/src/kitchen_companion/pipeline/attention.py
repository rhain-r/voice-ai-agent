"""Attention gate: the bot only listens when it's addressed.

`decide` is the pure decision. An utterance gets through when it starts with the wake phrase
("Chef, …"), arrives within the follow-up window after the bot spoke, follows a tap on the big
button, or is a bare stop word while the bot is talking. Everything else is overheard.
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

STOP_WORDS = ("stop", "wait", "quiet", "be quiet", "hold on", "pause")

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
