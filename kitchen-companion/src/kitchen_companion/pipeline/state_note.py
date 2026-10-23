"""Tells Claude where the cook is: appends a [kitchen state: …] note to the user's latest message."""

from pipecat.frames.frames import Frame, LLMContextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from kitchen_companion.recipes.state import RecipeSession

NOTE_PREFIX = "[kitchen state:"
# Stands in for the cook's first turn when the conversation opened with Chef speaking (a recipe
# picked by touch, a timer going off): the Messages API wants the first turn to be the user's.
OPENING_TURN = "(The cook started on the tablet screen.)"


def state_note(recipe: RecipeSession) -> str:
    if recipe.recipe is None:
        return "no recipe loaded"
    r = recipe.recipe
    step = f"step {recipe.index + 1} of {len(r.steps)}"
    return f"recipe '{r.title}', {step}, scaled for {recipe.servings} servings"


def _user_first(messages: list) -> list:
    for i, message in enumerate(messages):
        role = message.get("role") if isinstance(message, dict) else None
        if role in ("system", "developer"):
            continue
        if role == "assistant":
            return [*messages[:i], {"role": "user", "content": OPENING_TURN}, *messages[i:]]
        break
    return messages


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
        frame.context.transform_messages(_user_first)
        for message in reversed(frame.context.messages):
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            content = message.get("content")
            if isinstance(content, str) and NOTE_PREFIX not in content:
                message["content"] = f"{content}\n\n{NOTE_PREFIX} {state_note(self._recipe)}]"
            return
