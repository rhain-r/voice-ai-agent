"""Per-turn voice latency (spec §5.5): end-of-utterance delay + LLM time-to-first-token + TTS first byte."""

import math
from collections.abc import Callable
from dataclasses import dataclass

_FIELDS = {
    "eou_metrics": ("eou", "end_of_utterance_delay"),
    "llm_metrics": ("llm", "ttft"),
    "tts_metrics": ("tts", "ttfb"),
}


@dataclass
class TurnLatency:
    speech_id: str
    eou_delay_ms: int
    llm_ttft_ms: int
    tts_ttfb_ms: int
    total_ms: int


def _percentile(values: list[int], q: float) -> int:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


class LatencyTracker:
    def __init__(self, on_turn: Callable[[TurnLatency], None] | None = None) -> None:
        self._on_turn = on_turn
        self._partial: dict[str, dict[str, int]] = {}
        self._done: set[str] = set()
        self._turns: list[TurnLatency] = []

    def observe(self, metrics) -> None:
        kind = _FIELDS.get(getattr(metrics, "type", ""))
        speech_id = getattr(metrics, "speech_id", None)
        if kind is None or not speech_id or speech_id in self._done:
            return
        key, attr = kind
        parts = self._partial.setdefault(speech_id, {})
        parts.setdefault(key, round(getattr(metrics, attr) * 1000))  # first value per kind wins
        if len(parts) == 3:
            turn = TurnLatency(
                speech_id=speech_id,
                eou_delay_ms=parts["eou"],
                llm_ttft_ms=parts["llm"],
                tts_ttfb_ms=parts["tts"],
                total_ms=parts["eou"] + parts["llm"] + parts["tts"],
            )
            self._done.add(speech_id)
            del self._partial[speech_id]
            self._turns.append(turn)
            if self._on_turn:
                self._on_turn(turn)

    def turns(self) -> list[TurnLatency]:
        return list(self._turns)

    def summary(self) -> dict:
        totals = [t.total_ms for t in self._turns]
        if not totals:
            return {"p50_ms": 0, "p95_ms": 0, "turns": 0}
        return {"p50_ms": _percentile(totals, 0.5), "p95_ms": _percentile(totals, 0.95), "turns": len(totals)}


def setup_tracing(endpoint: str | None) -> None:
    """Send LiveKit's built-in OpenTelemetry spans to an OTLP endpoint (Langfuse, Jaeger, ...)."""
    if not endpoint:
        return
    from livekit.agents.telemetry import set_tracer_provider
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": "interview-coach-agent"}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    set_tracer_provider(provider)
