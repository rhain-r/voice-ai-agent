"""Speech metrics only a voice interview can produce: pace, fillers, pauses, thinking time.

Pure and I/O-free (spec §5.3). The worker feeds it final STT segments, question boundaries
and agent speech intervals; the scorecard reads the metrics.
"""

import re
from dataclasses import dataclass, field
from statistics import mean
from typing import Literal

PaceBand = Literal["slow", "conversational", "fast", "n/a"]

_FILLERS = re.compile(r"\b(?:um+|uh+|uhm|er|erm|hmm+)\b", re.IGNORECASE)
_TICS = {
    "you know": re.compile(r"\byou know\b", re.IGNORECASE),
    "kind of": re.compile(r"\bkind of\b", re.IGNORECASE),
    "sort of": re.compile(r"\bsort of\b", re.IGNORECASE),
    "like": re.compile(r"\blike\b", re.IGNORECASE),
    "basically": re.compile(r"\bbasically\b", re.IGNORECASE),
    "literally": re.compile(r"\bliterally\b", re.IGNORECASE),
}


@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class Segment:
    text: str
    start: float
    end: float
    words: tuple[Word, ...] = ()


@dataclass
class AnswerMetrics:
    index: int
    duration_s: float
    word_count: int
    wpm: float
    filler_count: int
    fillers_per_min: float
    verbal_tics: dict[str, int]
    longest_pause_s: float
    pauses_over_3s: int
    thinking_time_s: float | None
    pace_band: PaceBand


@dataclass
class SessionMetrics:
    answers: list[AnswerMetrics]
    avg_wpm: float
    fillers_per_min: float
    talk_ratio: float
    avg_thinking_time_s: float | None


@dataclass
class _Question:
    asked_at: float
    segments: list[Segment] = field(default_factory=list)


def count_fillers(text: str) -> int:
    return len(_FILLERS.findall(text))


def count_tics(text: str) -> dict[str, int]:
    counts = {name: len(pattern.findall(text)) for name, pattern in _TICS.items()}
    return {name: n for name, n in counts.items() if n}


def pace_band(wpm: float) -> PaceBand:
    if wpm <= 0:
        return "n/a"
    if wpm < 110:
        return "slow"
    if wpm <= 170:
        return "conversational"
    return "fast"


def _per_minute(count: float, seconds: float) -> float:
    return count / (seconds / 60) if seconds > 0 else 0.0


class SpeechAnalytics:
    def __init__(self) -> None:
        self._questions: dict[int, _Question] = {}
        self._current: int | None = None
        self._agent: list[tuple[float, float]] = []

    def start_question(self, index: int, at: float) -> None:
        self._questions.setdefault(index, _Question(asked_at=at))
        self._current = index

    def add_segment(self, seg: Segment) -> None:
        if self._current is None or not seg.text.strip():
            return
        self._questions[self._current].segments.append(seg)

    def add_agent_speech(self, start: float, end: float) -> None:
        if end > start:
            self._agent.append((start, end))

    def segments_for(self, index: int) -> list[Segment]:
        question = self._questions.get(index)
        return list(question.segments) if question else []

    def _agent_overlaps(self, start: float, end: float) -> bool:
        return any(a_start < end and a_end > start for a_start, a_end in self._agent)

    def answer_metrics(self, index: int) -> AnswerMetrics:
        segments = sorted(self.segments_for(index), key=lambda s: s.start)
        if not segments:
            return AnswerMetrics(index, 0.0, 0, 0.0, 0, 0.0, {}, 0.0, 0, None, "n/a")

        units: list[tuple[float, float]] = []
        for seg in segments:
            if seg.words:
                units.extend((w.start, w.end) for w in seg.words)
            else:
                units.append((seg.start, seg.end))
        units.sort()
        first_start, last_end = units[0][0], max(end for _, end in units)
        duration = last_end - first_start

        text = " ".join(seg.text for seg in segments)
        word_count = len(text.split())
        fillers = count_fillers(text)
        wpm = _per_minute(word_count, duration)

        gaps = [
            nxt[0] - prev[1]
            for prev, nxt in zip(units, units[1:], strict=False)
            if nxt[0] > prev[1] and not self._agent_overlaps(prev[1], nxt[0])
        ]

        asked_at = self._questions[index].asked_at
        prompt_ends = [end for _, end in self._agent if asked_at <= end <= first_start]
        thinking = round(first_start - max(prompt_ends), 2) if prompt_ends else None

        return AnswerMetrics(
            index=index,
            duration_s=round(duration, 2),
            word_count=word_count,
            wpm=round(wpm, 1),
            filler_count=fillers,
            fillers_per_min=round(_per_minute(fillers, duration), 2),
            verbal_tics=count_tics(text),
            longest_pause_s=round(max(gaps, default=0.0), 2),
            pauses_over_3s=sum(1 for g in gaps if g > 3.0),
            thinking_time_s=thinking,
            pace_band=pace_band(wpm),
        )

    def session_metrics(self) -> SessionMetrics:
        answers = [self.answer_metrics(i) for i in sorted(self._questions)]
        spoken = [a for a in answers if a.word_count]
        candidate_s = sum(seg.end - seg.start for q in self._questions.values() for seg in q.segments)
        agent_s = sum(end - start for start, end in self._agent)
        total_duration = sum(a.duration_s for a in spoken)
        thinking = [a.thinking_time_s for a in answers if a.thinking_time_s is not None]
        return SessionMetrics(
            answers=answers,
            avg_wpm=round(mean(a.wpm for a in spoken), 1) if spoken else 0.0,
            fillers_per_min=round(_per_minute(sum(a.filler_count for a in spoken), total_duration), 2),
            talk_ratio=round(candidate_s / (candidate_s + agent_s), 3) if candidate_s + agent_s else 0.0,
            avg_thinking_time_s=round(mean(thinking), 2) if thinking else None,
        )
