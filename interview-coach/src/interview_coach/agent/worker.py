"""LiveKit agent worker for the Interview Coach (spec §5.1). Real-time only: the scorecard runs in the API."""

import asyncio
import json
import logging
import sys
import time

from livekit import rtc
from livekit.agents import AgentServer, AgentSession, JobContext, JobProcess, cli, llm, stt, tts
from livekit.plugins import cartesia, deepgram, silero
from livekit.plugins.turn_detector.english import EnglishModel

from interview_coach.agent.analytics import SpeechAnalytics
from interview_coach.agent.completion import post_completion
from interview_coach.agent.interviewer import Interviewer
from interview_coach.agent.llm import ClaudeVoiceLLM
from interview_coach.agent.prompts import InterviewSetup
from interview_coach.agent.question_source import fetch_plan
from interview_coach.agent.session_config import (
    USER_AWAY_TIMEOUT,
    AwayPolicy,
    CompletionGuard,
    completion_status,
    keyterms_for,
    segment_qa,
    turn_handling,
    wait_until_quiet,
)
from interview_coach.agent.telemetry import LatencyTracker, TurnLatency, setup_tracing
from interview_coach.config import AGENT_REQUIRED, Settings, cli_needs_keys, require

log = logging.getLogger("interview_coach.worker")
AGENT_NAME = "interview-coach"
STT_FAILURE_LINE = (
    "I'm having trouble hearing you, so let's stop here. Your scorecard will cover what we got through."
)


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


server = AgentServer(setup_fnc=prewarm)


def build_tts(settings: Settings) -> tts.TTS:
    primary = deepgram.TTS(model="aura-2-andromeda-en", api_key=settings.deepgram_api_key)
    if not settings.cartesia_api_key:
        return primary
    secondary = cartesia.TTS(api_key=settings.cartesia_api_key)
    ordered = [secondary, primary] if settings.tts_provider == "cartesia" else [primary, secondary]
    return tts.FallbackAdapter(ordered)


def build_llm(settings: Settings) -> llm.LLM:
    return llm.FallbackAdapter(
        [
            ClaudeVoiceLLM(model=settings.live_model, api_key=settings.anthropic_api_key),
            ClaudeVoiceLLM(model=settings.fallback_model, api_key=settings.anthropic_api_key),
        ]
    )


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: JobContext) -> None:
    settings = Settings()
    setup = InterviewSetup(**json.loads(ctx.job.metadata or "{}"))
    setup_tracing(settings.otel_exporter_otlp_endpoint or None)

    plan, source = await fetch_plan(
        settings.mcp_url,
        role=setup.role,
        level=setup.level,
        style=setup.style,
        count=setup.count,
        seed=setup.session_id,
    )
    log.info("session %s: %d questions from %s bank", setup.session_id, len(plan), source)

    analytics = SpeechAnalytics()
    transcript: list[dict] = []
    guard, away = CompletionGuard(), AwayPolicy()
    background: set[asyncio.Task] = set()

    def spawn(coro) -> None:
        task = asyncio.create_task(coro)
        background.add(task)
        task.add_done_callback(background.discard)

    async def publish(topic: str, data: dict) -> None:
        try:
            await ctx.room.local_participant.send_text(json.dumps(data), topic=topic)
        except Exception:  # the UI is best-effort; never let it break the interview
            log.debug("publish on %s failed", topic, exc_info=True)

    def on_turn(turn: TurnLatency) -> None:
        spawn(publish("coach.metrics", turn.__dict__))

    tracker = LatencyTracker(on_turn=on_turn)

    session = AgentSession(
        stt=deepgram.STT(
            model="nova-3",
            filler_words=True,
            smart_format=True,
            keyterm=keyterms_for(setup.role),
            api_key=settings.deepgram_api_key,
        ),
        llm=build_llm(settings),
        tts=build_tts(settings),
        vad=ctx.proc.userdata["vad"],
        turn_handling={**turn_handling(), "turn_detection": EnglishModel()},
        user_away_timeout=USER_AWAY_TIMEOUT,
    )

    async def complete(reason: str) -> None:
        if reason not in ("disconnected", "stt_failure"):
            await wait_until_quiet(lambda: session.agent_state)
        asked = interviewer.current_index + 1
        payload = {
            "status": completion_status(asked=asked, total=interviewer.total, reason=reason),
            "transcript": transcript,
            "qa_items": [item.model_dump() for item in segment_qa(plan, analytics, asked)],
            "speech": _as_dict(analytics.session_metrics()),
            "latency": tracker.summary(),
        }
        await post_completion(settings.api_url, settings.agent_shared_secret, setup.session_id, payload)
        ctx.shutdown(reason=f"interview finished: {reason}")

    async def on_finish(reason: str) -> None:
        # Called from inside the end_interview tool: return at once so the goodbye can be spoken.
        spawn(guard.run_once(lambda: complete(reason)))

    async def on_progress(progress: dict) -> None:
        await publish("coach.progress", progress)

    interviewer = Interviewer(
        setup=setup,
        plan=plan,
        analytics=analytics,
        on_progress=on_progress,
        on_finish=on_finish,
        clock=time.time,
    )

    speaking_since: list[float] = []

    @session.on("agent_state_changed")
    def _on_agent_state(ev) -> None:
        if ev.new_state == "speaking":
            speaking_since[:] = [ev.created_at]
        elif ev.old_state == "speaking" and speaking_since:
            analytics.add_agent_speech(speaking_since.pop(), ev.created_at)

    @session.on("conversation_item_added")
    def _on_item(ev) -> None:
        item = ev.item
        if (
            getattr(item, "type", None) == "message"
            and item.role in ("user", "assistant")
            and item.text_content
        ):
            transcript.append({"role": item.role, "text": item.text_content, "at": ev.created_at})

    @session.on("metrics_collected")
    def _on_metrics(ev) -> None:
        tracker.observe(ev.metrics)

    @session.on("user_state_changed")
    def _on_user_state(ev) -> None:
        if ev.new_state == "away" and away.should_check_in(interviewer.current_index):
            session.generate_reply(instructions="Gently check in once: they can take their time, no rush.")

    @session.on("error")
    def _on_error(ev) -> None:
        if not ev.error.recoverable and isinstance(ev.source, stt.STT):
            log.error("unrecoverable STT error: %s", ev.error)

            async def stop_for_stt() -> None:
                session.say(STT_FAILURE_LINE, allow_interruptions=False)
                await wait_until_quiet(lambda: session.agent_state, quiet_s=0.5, timeout=10.0)
                await interviewer.finish("stt_failure")

            spawn(stop_for_stt())

    @ctx.room.on("participant_disconnected")
    def _on_left(participant: rtc.RemoteParticipant) -> None:
        if participant.identity.startswith("candidate-"):
            spawn(interviewer.finish("disconnected"))

    await session.start(agent=interviewer, room=ctx.room)


def _as_dict(metrics) -> dict:
    from dataclasses import asdict

    return asdict(metrics)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if cli_needs_keys(sys.argv):
        require(Settings(), AGENT_REQUIRED)
    cli.run_app(server)


if __name__ == "__main__":
    main()
