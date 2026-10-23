"""The bot's wiring pieces that can be tested without keys, audio or a network."""

import asyncio
from types import SimpleNamespace

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    InterruptionFrame,
    LLMContextFrame,
    LLMFullResponseStartFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.observers.base_observer import FramePushed
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection

from kitchen_companion.bot import (
    Announcer,
    ClientActions,
    LLMWatchdog,
    SpeakingObserver,
    client_ready,
    keyterms,
    make_llm,
)
from kitchen_companion.config import Settings
from kitchen_companion.recipes.library import Library
from kitchen_companion.timers import AnnouncementGate
from tests.fakes import fixture_recipe, loaded_session, make_sink, make_timers


def pushed(frame, source=None, destination=None) -> FramePushed:
    return FramePushed(
        source=source, destination=destination, frame=frame, direction=FrameDirection.DOWNSTREAM, timestamp=0
    )


def test_keyterms_from_recipe_and_wake_phrase():
    terms = keyterms(fixture_recipe(), "chef")
    assert terms == ["flour", "butter", "garlic", "chef"]
    assert keyterms(None, "chef") == ["chef"]


def test_keyterms_capped_at_fifty():
    recipe = fixture_recipe()
    many = [recipe.ingredients[0].model_copy(update={"name": f"spice {i}"}) for i in range(80)]
    assert len(keyterms(recipe.model_copy(update={"ingredients": many}), "chef")) == 50
    assert keyterms(recipe.model_copy(update={"ingredients": many}), "chef")[-1] == "chef"


class ActionRig:
    def __init__(self):
        self.recipe = loaded_session()
        self.timers = make_timers()
        self.sink = make_sink()
        self.spoken = []
        self.armed = 0
        self.loaded = []

        async def speak(text):
            self.spoken.append(text)

        async def on_recipe_loaded(recipe):
            self.loaded.append(recipe.id)

        attention = SimpleNamespace(arm_button=lambda: setattr(self, "armed", self.armed + 1))
        self.actions = ClientActions(
            self.recipe, self.timers, Library.load_bundled(), self.sink, attention, speak, on_recipe_loaded
        )


async def test_client_load_recipe_speaks_intro_and_updates_state():
    rig = ActionRig()
    await rig.actions.handle("load_recipe", {"id": "tomato-soup"})
    assert rig.spoken[-1].startswith("Okay — Tomato Soup.")
    assert rig.loaded == ["tomato-soup"] and rig.sink.states[-1]["id"] == "tomato-soup"
    await rig.actions.handle("load_recipe", {"id": "nope"})
    assert rig.loaded == ["tomato-soup"]


async def test_client_goto_engage_ack():
    rig = ActionRig()
    await rig.actions.handle("goto_step", {"n": 3})
    assert rig.spoken[-1] == "Step three: Serve." and rig.sink.states[-1]["index"] == 2
    await rig.actions.handle("engage", None)
    assert rig.armed == 1
    timer = rig.timers.start(1, "pasta")
    timer.state = "due"
    await rig.actions.handle("ack_timer", {})
    assert rig.timers.list() == [] and rig.sink.timer_snapshots[-1] == []
    await rig.actions.handle("goto_step", {"n": "x"})  # bad input is ignored, not raised
    await rig.actions.handle("unknown", {})


async def test_speaking_observer_feeds_announcement_gate():
    gate = AnnouncementGate()
    obs = SpeakingObserver(gate)
    assert obs.observe_every_push is False
    await obs.on_push_frame(pushed(VADUserStartedSpeakingFrame()))
    assert not gate._clear.is_set()
    await obs.on_push_frame(pushed(UserStartedSpeakingFrame()))
    await obs.on_push_frame(pushed(VADUserStoppedSpeakingFrame()))
    assert not gate._clear.is_set()  # the user turn is still open
    await obs.on_push_frame(pushed(UserStoppedSpeakingFrame()))
    assert gate._clear.is_set()
    await obs.on_push_frame(pushed(BotStartedSpeakingFrame()))
    assert not gate._clear.is_set()
    await obs.on_push_frame(pushed(BotStoppedSpeakingFrame()))
    assert gate._clear.is_set()


async def test_llm_watchdog_fires_when_no_first_token():
    llm = object()
    stalls = []

    async def on_stall():
        stalls.append(1)

    dog = LLMWatchdog(llm, timeout_s=0.05, on_stall=on_stall)
    # Observers only see a frame's first push: the user aggregator handing it to the next processor.
    await dog.on_push_frame(pushed(LLMContextFrame(context=LLMContext()), destination=object()))
    await asyncio.sleep(0.1)
    assert stalls == [1]


async def test_llm_watchdog_disarmed_by_interruption():
    llm = object()
    stalls = []

    async def on_stall():
        stalls.append(1)

    dog = LLMWatchdog(llm, timeout_s=0.05, on_stall=on_stall)
    await dog.on_push_frame(pushed(LLMContextFrame(context=LLMContext()), destination=object()))
    await dog.on_push_frame(pushed(InterruptionFrame()))  # the user cut in; no answer is coming
    await asyncio.sleep(0.1)
    assert stalls == []


def test_llm_runs_haiku_low_effort_without_thinking():
    llm = make_llm(Settings(_env_file=None, anthropic_api_key="a", deepgram_api_key="d"))
    settings = llm._settings  # noqa: SLF001 - the request settings are what the constraint is about
    assert settings.model == "claude-haiku-5-5"
    assert settings.effort == "low"
    assert settings.thinking.type == "disabled"


async def test_client_ready_attaches_and_replays_queued_announcements():
    from kitchen_companion.registry import Kitchen

    kitchen = Kitchen("kitchen-abc123")
    pasta = kitchen.timers.start(1, "pasta")
    await kitchen.on_due([pasta], False)
    sink, heard = make_sink(), []

    async def announce(timers, is_reminder):
        heard.append([t.label for t in timers])

    await client_ready(kitchen, announce, sink)
    assert heard == [["pasta"]]
    assert sink.states and sink.timer_snapshots  # the UI gets state before the replayed speech


async def test_llm_watchdog_disarmed_by_response():
    llm = object()
    stalls = []

    async def on_stall():
        stalls.append(1)

    dog = LLMWatchdog(llm, timeout_s=0.05, on_stall=on_stall)
    await dog.on_push_frame(pushed(LLMContextFrame(context=LLMContext()), destination=object()))
    await dog.on_push_frame(pushed(LLMFullResponseStartFrame(), source=llm))
    await asyncio.sleep(0.1)
    assert stalls == []
    await dog.close()


async def test_announcer_waits_for_quiet_then_speaks_and_opens_window():
    gate = AnnouncementGate()
    recipe, timers, sink = loaded_session(), make_timers(), make_sink()
    spoken, windows = [], []

    async def speak(text):
        spoken.append(text)

    announcer = Announcer(gate, speak, lambda: windows.append(1), recipe, timers, sink)
    task = asyncio.create_task(announcer.run())
    gate.set_user_speaking(True)
    pasta = timers.start(1, "pasta")
    pasta.state = "due"  # as TimerService.tick leaves it
    await announcer.announce([pasta], False)
    await asyncio.sleep(0.02)
    assert spoken == []
    gate.set_user_speaking(False)
    await asyncio.sleep(0.02)
    assert spoken == ["Your pasta timer is done. Next up: Simmer the sauce for 8 minutes."]
    assert windows == [1] and sink.timer_snapshots
    await announcer.announce([pasta], True)
    await asyncio.sleep(0.02)
    assert spoken[-1] == "Reminder: your pasta timer went off."
    timers.acknowledge()
    await announcer.announce([pasta], True)  # acknowledged while queued: stays quiet
    await asyncio.sleep(0.02)
    assert len(spoken) == 2
    task.cancel()
