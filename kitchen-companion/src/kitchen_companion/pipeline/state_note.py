"""Tells Claude where the cook is: appends a [kitchen state: …] note to the user's latest message."""

from pipecat.frames.frames import Frame, LLMContextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from kitchen_companion.recipes.state import RecipeSession

NOTE_PREFIX = "[kitchen state:"


def state_note(recipe: RecipeSession) -> str:
    if recipe.recipe is None:
        return "no recipe loaded"
    r = recipe.recipe
    step = f"step {recipe.index + 1} of {len(r.steps)}"
    return f"recipe '{r.title}', {step}, scaled for {recipe.servings} servings"


class StateNoteInjector(FrameProcessor):
    """Sits between the user aggregator and the LLM.

    It annotates the context rather than the transcript, so the note never counts toward the
    interruption word threshold. Each user message is noted once; tool-call follow-ups reuse it.
    """

    def __init__(self, recipe: RecipeSession):
        super().__init__()
        self._recipe = recipe

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame) and direction == FrameDirection.DOWNSTREAM:
            self._annotate(frame)
        await self.push_frame(frame, direction)

    def _annotate(self, frame: LLMContextFrame) -> None:
        for message in reversed(frame.context.messages):
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            content = message.get("content")
            if isinstance(content, str) and NOTE_PREFIX not in content:
                message["content"] = f"{content}\n\n{NOTE_PREFIX} {state_note(self._recipe)}]"
            return
