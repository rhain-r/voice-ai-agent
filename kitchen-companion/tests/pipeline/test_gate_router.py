import pytest
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    InterimTranscriptionFrame,
    InterruptionFrame,
    LLMContextFrame,
    LLMMessagesAppendFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.tests.utils import SleepFrame, run_test

from kitchen_companion.bot import user_params
from kitchen_companion.events import TurnPath
from kitchen_companion.pipeline.attention import AttentionConfig, AttentionGate
from kitchen_companion.pipeline.fast_path import FastPathRouter
from kitchen_companion.pipeline.state_note import StateNoteInjector
from kitchen_companion.recipes.state import RecipeSession
from tests.fakes import loaded_session, make_sink, make_timers, tf


class Rig:
    def __init__(self):
        self.sink = make_sink()
        self.path = TurnPath()
        self.recipe = loaded_session()
        self.timers = make_timers()
        self.gate = AttentionGate(AttentionConfig(), self.sink)
        self.router = FastPathRouter(self.recipe, self.timers, self.sink, self.path)

    def pipeline(self) -> Pipeline:
        return Pipeline([self.gate, self.router])


@pytest.fixture
def rig() -> Rig:
    return Rig()


async def test_engaged_next_is_fast_path(rig):
    down, _ = await run_test(
        rig.pipeline(),
        frames_to_send=[tf("Chef, next")],
        expected_down_frames=[TTSSpeakFrame, LLMMessagesAppendFrame],
    )
    assert down[0].text.startswith("Step two") and rig.path.value == "fast" and rig.sink.heard == ["next"]
    assert down[0].append_to_context is False  # the exchange goes in via the append frame instead
    assert down[1].messages == [
        {"role": "user", "content": "next"},
        {"role": "assistant", "content": down[0].text},
    ]
    assert down[1].run_llm is False
    assert rig.sink.states[-1]["index"] == 1


async def test_overheard_dropped(rig):
    await run_test(rig.pipeline(), frames_to_send=[tf("did you call your mom back")], expected_down_frames=[])
    assert rig.sink.overheard == ["did you call your mom back"]
    assert rig.sink.heard == []


async def test_overheard_interim_dropped(rig):
    interim = InterimTranscriptionFrame(text="did you", user_id="u", timestamp="now")
    await run_test(rig.pipeline(), frames_to_send=[interim], expected_down_frames=[])


async def test_unmatched_engaged_reaches_llm(rig):
    down, _ = await run_test(
        rig.pipeline(), frames_to_send=[tf("chef how much garlic")], expected_down_frames=[TranscriptionFrame]
    )
    assert down[0].text == "how much garlic"
    assert down[0].user_id == "u" and down[0].timestamp == "now"
    assert rig.path.value == "llm"


async def test_bare_wake_says_yes(rig):
    down, _ = await run_test(
        rig.pipeline(), frames_to_send=[tf("hey chef")], expected_down_frames=[TTSSpeakFrame]
    )
    assert down[0].text == "Yes?"
    down, _ = await run_test(
        rig.pipeline(), frames_to_send=[tf("how much garlic")], expected_down_frames=[TranscriptionFrame]
    )


async def test_followup_after_bot_stops(rig):
    down, _ = await run_test(
        rig.pipeline(),
        frames_to_send=[BotStoppedSpeakingFrame(), tf("how much garlic")],
        expected_down_frames=[BotStoppedSpeakingFrame, TranscriptionFrame],
    )
    assert down[1].text == "how much garlic"


async def test_button_engages_one_utterance(rig):
    rig.gate.arm_button()
    await run_test(
        rig.pipeline(), frames_to_send=[tf("how much garlic")], expected_down_frames=[TranscriptionFrame]
    )
    rig.gate.open_window(-1)  # close the short continuation window the engaged line opened
    await run_test(rig.pipeline(), frames_to_send=[tf("how much flour")], expected_down_frames=[])


async def test_engaged_fragment_continues(rig):
    """Deepgram can split "Chef, set a timer for… um… ten minutes" into two finals."""
    down, _ = await run_test(
        rig.pipeline(),
        frames_to_send=[tf("Chef, set a timer for"), tf("ten minutes")],
        expected_down_frames=[TranscriptionFrame, TranscriptionFrame],
    )
    assert [f.text for f in down] == ["set a timer for", "ten minutes"]


async def test_stop_word_while_bot_speaking_interrupts(rig):
    down, _ = await run_test(rig.pipeline(), frames_to_send=[BotStartedSpeakingFrame(), tf("stop")])
    assert any(isinstance(f, InterruptionFrame) for f in down)
    assert not any(isinstance(f, TTSSpeakFrame) for f in down)


async def test_router_cancel_ambiguous_asks(rig):  # Review Focus 4
    rig.timers.start(5, "pasta")
    rig.timers.start(3, "sauce")
    down, _ = await run_test(
        rig.router,
        frames_to_send=[tf("cancel the timer")],
        expected_down_frames=[TTSSpeakFrame, LLMMessagesAppendFrame],
    )
    assert down[0].text == "Which timer, pasta or sauce?" and len(rig.timers.list()) == 2


async def test_router_cancel_named(rig):
    rig.timers.start(5, "pasta")
    rig.timers.start(3, "sauce")
    down, _ = await run_test(
        rig.router,
        frames_to_send=[tf("cancel the pasta timer")],
        expected_down_frames=[TTSSpeakFrame, LLMMessagesAppendFrame],
    )
    assert down[0].text == "Cancelled the pasta timer."
    assert [t.label for t in rig.timers.list()] == ["sauce"]
    assert rig.sink.timer_snapshots[-1][0]["label"] == "sauce"


async def test_router_cancel_none_running(rig):
    down, _ = await run_test(
        rig.router,
        frames_to_send=[tf("cancel the timer")],
        expected_down_frames=[TTSSpeakFrame, LLMMessagesAppendFrame],
    )
    assert down[0].text == "There's no timer running."


async def test_router_timer_start(rig):
    down, _ = await run_test(
        rig.router,
        frames_to_send=[tf("set a timer for 8 minutes for the onions")],
        expected_down_frames=[TTSSpeakFrame, LLMMessagesAppendFrame],
    )
    assert down[0].text == "Onions timer set for eight minutes."
    assert [(t.label, t.minutes) for t in rig.timers.list()] == [("onions", 8)]


async def test_router_timer_start_default_label_uses_step_verb(rig):
    rig.recipe.goto(2)
    down, _ = await run_test(
        rig.router,
        frames_to_send=[tf("set a timer for a minute and a half")],
        expected_down_frames=[TTSSpeakFrame, LLMMessagesAppendFrame],
    )
    assert down[0].text == "Simmer timer set for one minute and thirty seconds."


async def test_router_timer_query(rig):
    rig.timers.start(5, "pasta")
    down, _ = await run_test(
        rig.router,
        frames_to_send=[tf("how long left on the pasta")],
        expected_down_frames=[TTSSpeakFrame, LLMMessagesAppendFrame],
    )
    assert down[0].text in (
        "The pasta timer has five minutes left.",
        "The pasta timer has four minutes and fifty-nine seconds left.",
    )


async def test_router_timer_query_none(rig):
    down, _ = await run_test(
        rig.router,
        frames_to_send=[tf("how much time is left")],
        expected_down_frames=[TTSSpeakFrame, LLMMessagesAppendFrame],
    )
    assert down[0].text == "No timers running."


async def test_yes_accepts_timer_offer(rig):
    rig.recipe.goto(2)
    assert rig.recipe.pending_timer_offer == 8
    down, _ = await run_test(
        rig.router, frames_to_send=[tf("yes")], expected_down_frames=[TTSSpeakFrame, LLMMessagesAppendFrame]
    )
    assert [(t.label, t.minutes) for t in rig.timers.list()] == [("simmer", 8)]
    assert rig.recipe.pending_timer_offer is None
    assert down[0].text == "Simmer timer set for eight minutes."


async def test_no_declines_timer_offer(rig):
    rig.recipe.goto(2)
    down, _ = await run_test(
        rig.router,
        frames_to_send=[tf("no thanks")],
        expected_down_frames=[TTSSpeakFrame, LLMMessagesAppendFrame],
    )
    assert down[0].text == "Okay." and rig.recipe.pending_timer_offer is None and rig.timers.list() == []


async def test_yes_without_offer_goes_to_llm(rig):
    await run_test(rig.router, frames_to_send=[tf("yes")], expected_down_frames=[TranscriptionFrame])
    assert rig.path.value == "llm"


async def test_ack_only_when_a_timer_is_due(rig):
    await run_test(rig.router, frames_to_send=[tf("thanks")], expected_down_frames=[TranscriptionFrame])
    timer = rig.timers.start(1, "pasta")
    timer.state = "due"
    down, _ = await run_test(
        rig.router,
        frames_to_send=[tf("thanks")],
        expected_down_frames=[TTSSpeakFrame, LLMMessagesAppendFrame],
    )
    assert down[0].text == "Got it." and rig.timers.list() == []


async def test_stop_acknowledges_due_timer(rig):
    timer = rig.timers.start(1, "pasta")
    timer.state = "due"
    down, _ = await run_test(rig.router, frames_to_send=[tf("stop")])
    assert any(isinstance(f, InterruptionFrame) for f in down)
    assert rig.timers.list() == []


async def test_fast_path_multiword_interrupts_bot(rig):
    down, _ = await run_test(rig.router, frames_to_send=[BotStartedSpeakingFrame(), tf("go back")])
    kinds = [type(f) for f in down]
    assert InterruptionFrame in kinds and kinds.index(InterruptionFrame) < kinds.index(TTSSpeakFrame)


async def test_fast_path_single_word_does_not_interrupt_bot(rig):
    down, _ = await run_test(rig.router, frames_to_send=[BotStartedSpeakingFrame(), tf("next")])
    assert not any(isinstance(f, InterruptionFrame) for f in down)


async def test_no_recipe_navigation_still_fast(rig):
    rig.router._recipe = RecipeSession()  # noqa: SLF001 - swap in an empty kitchen
    down, _ = await run_test(
        rig.router, frames_to_send=[tf("next")], expected_down_frames=[TTSSpeakFrame, LLMMessagesAppendFrame]
    )
    assert down[0].text.startswith("No recipe loaded yet")


async def test_state_note_injected():
    recipe = loaded_session()
    context = LLMContext(
        messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "how much garlic"}]
    )
    down, _ = await run_test(
        StateNoteInjector(recipe),
        frames_to_send=[LLMContextFrame(context=context)],
        expected_down_frames=[LLMContextFrame],
    )
    content = context.messages[-1]["content"]
    assert content == "how much garlic\n\n[kitchen state: recipe 'Test', step 1 of 3, scaled for 4 servings]"
    # A second inference on the same turn (after a tool call) doesn't stack notes.
    await run_test(StateNoteInjector(recipe), frames_to_send=[LLMContextFrame(context=context)])
    assert context.messages[-1]["content"].count("[kitchen state:") == 1


async def test_state_note_no_recipe():
    context = LLMContext(messages=[{"role": "user", "content": "find me a soup"}])
    await run_test(StateNoteInjector(RecipeSession()), frames_to_send=[LLMContextFrame(context=context)])
    assert context.messages[-1]["content"].endswith("[kitchen state: no recipe loaded]")


async def test_state_note_starts_context_with_a_user_turn():
    """A touch-loaded recipe or a timer announcement can be the first thing in the context."""
    recipe = loaded_session()
    context = LLMContext(
        messages=[
            {"role": "system", "content": "sys"},
            {"role": "assistant", "content": "Okay, Test. Three steps. Step one: Whisk the flour."},
            {"role": "user", "content": "how much garlic"},
        ]
    )
    await run_test(StateNoteInjector(recipe), frames_to_send=[LLMContextFrame(context=context)])
    roles = [m["role"] for m in context.messages]
    assert roles == ["system", "user", "assistant", "user"]
    await run_test(StateNoteInjector(recipe), frames_to_send=[LLMContextFrame(context=context)])
    assert [m["role"] for m in context.messages] == roles  # added once


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


async def test_button_arm_expires():
    sink, clock = make_sink(), FakeClock()
    gate = AttentionGate(AttentionConfig(), sink, clock=clock)
    gate.arm_button()
    clock.now += 30  # tapped, then nobody spoke to Chef
    await run_test(gate, frames_to_send=[tf("did you call your mom back")], expected_down_frames=[])
    assert sink.overheard == ["did you call your mom back"]


async def test_fast_path_command_over_bot_doesnt_run_llm(rig):
    """An interim can open a user turn whose final the router then answers: that turn ends empty."""
    rig.gate.open_window()
    timer = rig.timers.start(1, "pasta")
    timer.state = "due"
    context = LLMContext(messages=[{"role": "system", "content": "sys"}])
    aggregators = LLMContextAggregatorPair(context, user_params=user_params(stop_timeout=0.2))
    interim = InterimTranscriptionFrame(text="got it", user_id="u", timestamp="now")
    down, _ = await run_test(
        Pipeline([rig.gate, rig.router, aggregators.user()]),
        frames_to_send=[
            BotStartedSpeakingFrame(),
            interim,
            SleepFrame(sleep=0.2),
            tf("got it"),
            SleepFrame(sleep=0.8),
        ],
    )
    assert any(isinstance(f, TTSSpeakFrame) and f.text == "Got it." for f in down)
    assert not any(isinstance(f, LLMContextFrame) for f in down)
