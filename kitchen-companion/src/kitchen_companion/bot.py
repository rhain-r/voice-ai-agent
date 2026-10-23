"""Builds and runs the Pipecat pipeline for one tablet connection.

    transport.in → Deepgram STT → AttentionGate → FastPathRouter → user aggregator → StateNoteInjector
                 → Claude Haiku 5.5 (tools) → TTS (KitchenTextFilter) → transport.out → assistant aggregator

Recipe and timers belong to the kitchen, not the connection, so a reconnect picks up where it left off.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    ErrorFrame,
    Frame,
    InterruptionFrame,
    LLMContextFrame,
    LLMFullResponseStartFrame,
    STTUpdateSettingsFrame,
    TTSSpeakFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.services.anthropic.llm import AnthropicLLMService
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.deepgram.tts import DeepgramTTSService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.turns.user_start import MinWordsUserTurnStartStrategy
from pipecat.turns.user_stop.turn_analyzer_user_turn_stop_strategy import TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner

from kitchen_companion.config import Settings
from kitchen_companion.events import EventSink, LatencyClock, LatencyObserver, RTVIEventSink, TurnPath
from kitchen_companion.pipeline.attention import AttentionConfig, AttentionGate
from kitchen_companion.pipeline.fast_path import FastPathRouter
from kitchen_companion.pipeline.speakable import KitchenTextFilter
from kitchen_companion.pipeline.state_note import StateNoteInjector
from kitchen_companion.prompts import SYSTEM_PROMPT
from kitchen_companion.recipes.library import Library
from kitchen_companion.recipes.model import Recipe
from kitchen_companion.recipes.state import RecipeSession
from kitchen_companion.registry import Kitchen
from kitchen_companion.timers import AnnouncementGate, Timer, TimerService, announcement_text
from kitchen_companion.tools import ToolHandlers, tool_schemas

logger = logging.getLogger(__name__)

APOLOGY = "Sorry, I lost my train of thought — try that again?"
LLM_TIMEOUT_S = 8.0
MAX_KEYTERMS = 50
# How long a timer announcement waits for the room to go quiet before speaking anyway.
ANNOUNCE_WAIT_S = 20.0

Speak = Callable[[str], Awaitable[None]]


def keyterms(recipe: Recipe | None, wake_phrase: str) -> list[str]:
    """Words for Deepgram to listen harder for: the recipe's ingredients, then the wake phrase."""
    names: list[str] = []
    for ing in recipe.ingredients if recipe else []:
        name = ing.name.strip().lower()
        if name and name not in names and len(name) <= 40:
            names.append(name)
    return names[: MAX_KEYTERMS - 1] + [wake_phrase]


class ClientActions:
    """Touch actions from the tablet, applied to the same kitchen state the voice path uses."""

    def __init__(
        self,
        recipe: RecipeSession,
        timers: TimerService,
        library: Library,
        sink: EventSink,
        attention,
        speak: Speak,
        on_recipe_loaded: Callable[[Recipe], Awaitable[None]],
    ):
        self._recipe = recipe
        self._timers = timers
        self._library = library
        self._sink = sink
        self._attention = attention
        self._speak = speak
        self._on_recipe_loaded = on_recipe_loaded

    async def handle(self, kind: str, data) -> None:
        data = data if isinstance(data, dict) else {}
        try:
            if kind == "load_recipe":
                recipe = self._library.get(str(data.get("id", "")))
                if recipe is None:
                    return
                say = self._recipe.load(recipe)
                await self._on_recipe_loaded(recipe)
                await self._sink.recipe_state(self._recipe.snapshot())
                await self._speak(say)
            elif kind == "goto_step":
                say = self._recipe.goto(int(data["n"]))
                await self._sink.recipe_state(self._recipe.snapshot())
                await self._speak(say)
            elif kind == "engage":
                self._attention.arm_button()
            elif kind == "ack_timer":
                self._timers.acknowledge()
                await self._sink.timers(self._timers.snapshot())
        except (KeyError, TypeError, ValueError):
            logger.warning("ignoring bad client message %s %r", kind, data)


class SpeakingObserver(BaseObserver):
    """Tells the announcement gate when anyone (VAD) or a user turn, or the bot, is talking."""

    def __init__(self, gate: AnnouncementGate):
        super().__init__(observe_every_push=False)
        self._gate = gate
        self._vad = False
        self._turn = False

    async def on_push_frame(self, data: FramePushed) -> None:
        frame = data.frame
        if isinstance(frame, VADUserStartedSpeakingFrame):
            self._vad = True
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            self._vad = False
        elif isinstance(frame, UserStartedSpeakingFrame):
            self._turn = True
        elif isinstance(frame, UserStoppedSpeakingFrame):
            self._turn = False
        elif isinstance(frame, BotStartedSpeakingFrame):
            self._gate.set_bot_speaking(True)
            return
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._gate.set_bot_speaking(False)
            return
        else:
            return
        self._gate.set_user_speaking(self._vad or self._turn)


class LLMWatchdog(BaseObserver):
    """Calls `on_stall` when a context heads for the LLM but no response starts within the timeout.

    Observers see only a frame's first push (aggregator → next processor), so any LLMContextFrame
    arms it; the pipeline has one LLM. An interruption disarms it: no answer is coming then.
    """

    def __init__(self, llm: object, timeout_s: float, on_stall: Callable[[], Awaitable[None]]):
        super().__init__(observe_every_push=False)
        self._llm = llm
        self._timeout_s = timeout_s
        self._on_stall = on_stall
        self._timer: asyncio.Task | None = None

    async def on_push_frame(self, data: FramePushed) -> None:
        if isinstance(data.frame, LLMContextFrame):
            self._disarm()
            self._timer = asyncio.create_task(self._wait())
        elif isinstance(data.frame, LLMFullResponseStartFrame) and data.source is self._llm:
            self._disarm()
        elif isinstance(data.frame, InterruptionFrame):
            self._disarm()

    async def _wait(self) -> None:
        await asyncio.sleep(self._timeout_s)
        self._timer = None
        await self._on_stall()

    def _disarm(self) -> None:
        if self._timer:
            self._timer.cancel()
            self._timer = None

    async def close(self) -> None:
        self._disarm()


class Announcer:
    """Speaks timer announcements one at a time, once the user and the bot are both quiet."""

    def __init__(
        self,
        gate: AnnouncementGate,
        speak: Speak,
        open_window: Callable[[], None],
        recipe: RecipeSession,
        timers: TimerService,
        sink: EventSink,
        wait_s: float = ANNOUNCE_WAIT_S,
    ):
        self._gate = gate
        self._speak = speak
        self._open_window = open_window
        self._recipe = recipe
        self._timers = timers
        self._sink = sink
        self._wait_s = wait_s
        self._queue: asyncio.Queue[tuple[list[Timer], bool]] = asyncio.Queue()

    async def announce(self, timers: list[Timer], is_reminder: bool) -> None:
        """The kitchen's timer callback: queue it so the timer loop never waits on the room."""
        self._queue.put_nowait((timers, is_reminder))

    async def run(self) -> None:
        while True:
            timers, is_reminder = await self._queue.get()
            if not any(t.state == "due" for t in timers):
                continue  # acknowledged or cancelled while it waited
            await self._gate.wait_clear(self._wait_s)
            labels = [t.label for t in timers]
            await self._speak(announcement_text(labels, self._recipe.next_step_text(), is_reminder))
            self._open_window()
            await self._sink.timers(self._timers.snapshot())


def user_params(vad_analyzer=None, turn_analyzer=None, stop_timeout: float = 5.0) -> LLMUserAggregatorParams:
    """How the user aggregator decides a turn started and ended."""
    return LLMUserAggregatorParams(
        vad_analyzer=vad_analyzer,
        # No VAD start strategy, so room noise never starts a turn; only lines the gate passed do,
        # and while the bot is talking it takes two words to cut it off.
        user_turn_strategies=UserTurnStrategies(
            start=[MinWordsUserTurnStartStrategy(min_words=2)],
            stop=[
                TurnAnalyzerUserTurnStopStrategy(turn_analyzer=turn_analyzer or LocalSmartTurnAnalyzerV3())
            ],
        ),
        user_turn_stop_timeout=stop_timeout,
        # The fast path answers some lines the turn started on, so a turn ending with no transcript
        # for the LLM is normal here, not something to "recover" by asking the user to repeat.
        empty_user_turn=None,
    )


def make_llm(settings: Settings) -> AnthropicLLMService:
    # Thinking off explicitly: Pipecat only sends its lowest-thinking default when effort is unset.
    return AnthropicLLMService(
        api_key=settings.anthropic_api_key,
        settings=AnthropicLLMService.Settings(
            model=settings.llm_model,
            effort="low",
            thinking=AnthropicLLMService.ThinkingConfig(type="disabled"),
        ),
    )


async def client_ready(
    kitchen: Kitchen, announce: Callable[[list[Timer], bool], Awaitable[None]], sink: EventSink
):
    """The tablet's RTVI client is up: send it the kitchen, then start (and catch up on) announcements.

    Attaching here rather than when the pipeline starts means queued announcements aren't spoken
    into a peer connection that can't carry audio yet.
    """
    await sink.recipe_state(kitchen.recipe.snapshot())
    await sink.timers(kitchen.timers.snapshot())
    await kitchen.attach(announce)


def make_tts(settings: Settings):
    if settings.tts_provider == "cartesia":
        return CartesiaTTSService(
            api_key=settings.cartesia_api_key,
            settings=CartesiaTTSService.Settings(voice=settings.cartesia_voice_id),
            text_filters=[KitchenTextFilter()],
        )
    return DeepgramTTSService(
        api_key=settings.deepgram_api_key,
        settings=DeepgramTTSService.Settings(voice="aura-2-thalia-en"),
        text_filters=[KitchenTextFilter()],
    )


async def run_bot(
    connection: SmallWebRTCConnection, kitchen: Kitchen, library: Library, settings: Settings
) -> None:
    transport = SmallWebRTCTransport(
        webrtc_connection=connection,
        params=TransportParams(audio_in_enabled=True, audio_out_enabled=True),
    )
    stt = DeepgramSTTService(
        api_key=settings.deepgram_api_key,
        settings=DeepgramSTTService.Settings(
            model="nova-3", smart_format=True, keyterm=keyterms(kitchen.recipe.recipe, settings.wake_phrase)
        ),
    )
    llm = make_llm(settings)
    tts = make_tts(settings)

    worker: PipelineWorker | None = None

    async def push(frame: Frame) -> None:
        if worker is not None:
            await worker.queue_frame(frame)

    async def speak(text: str) -> None:
        await push(TTSSpeakFrame(text))

    sink = RTVIEventSink(push)
    path, gate = TurnPath(), AnnouncementGate()
    attention = AttentionGate(AttentionConfig(settings.wake_phrase, settings.followup_window_s), sink)
    router = FastPathRouter(kitchen.recipe, kitchen.timers, sink, path)

    async def on_recipe_loaded(recipe: Recipe) -> None:
        # Deepgram applies new keyterms by reconnecting its stream with the updated settings.
        terms = keyterms(recipe, settings.wake_phrase)
        await push(STTUpdateSettingsFrame(delta=DeepgramSTTService.Settings(keyterm=terms)))

    handlers = ToolHandlers(kitchen.recipe, kitchen.timers, library, sink, on_recipe_loaded)
    context = LLMContext(
        messages=[{"role": "system", "content": SYSTEM_PROMPT}], tools=tool_schemas(handlers)
    )
    aggregators = LLMContextAggregatorPair(
        context, user_params=user_params(vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)))
    )

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            attention,
            router,
            aggregators.user(),
            StateNoteInjector(kitchen.recipe),
            llm,
            tts,
            transport.output(),
            aggregators.assistant(),
        ]
    )

    async def apologize(reason: str) -> None:
        logger.warning("LLM failure: %s", reason)
        await push(InterruptionFrame())
        await speak(APOLOGY)
        await sink.error(reason)

    async def on_stall() -> None:
        await apologize("the model took too long to answer")

    watchdog = LLMWatchdog(llm, LLM_TIMEOUT_S, on_stall)
    worker = PipelineWorker(
        pipeline,
        observers=[LatencyObserver(LatencyClock(), path, sink), SpeakingObserver(gate), watchdog],
    )
    announcer = Announcer(gate, speak, attention.open_window, kitchen.recipe, kitchen.timers, sink)
    actions = ClientActions(kitchen.recipe, kitchen.timers, library, sink, attention, speak, on_recipe_loaded)

    @worker.event_handler("on_pipeline_error")
    async def on_pipeline_error(_worker, frame: ErrorFrame):
        if getattr(frame, "processor", None) is llm:
            await apologize(str(frame.error))

    @worker.rtvi.event_handler("on_client_ready")
    async def on_client_ready(_rtvi):
        await client_ready(kitchen, announcer.announce, sink)

    @worker.rtvi.event_handler("on_client_message")
    async def on_client_message(_rtvi, message):
        await actions.handle(message.type, message.data)

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(_transport, _client):
        kitchen.detach(announcer.announce)
        await worker.cancel()

    announcer_task = asyncio.create_task(announcer.run(), name=f"announcer-{kitchen.id}")
    runner = WorkerRunner(handle_sigint=False)
    try:
        await runner.add_workers(worker)
        await runner.run()
    finally:
        kitchen.detach(announcer.announce)
        announcer_task.cancel()
        await watchdog.close()
