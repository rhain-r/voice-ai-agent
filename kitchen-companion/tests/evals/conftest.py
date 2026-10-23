"""Tool-call evals: Claude Haiku 5.5 with the real system prompt and tool schemas.

They call the Anthropic API, so they're marked `eval`, excluded from the default run, and skipped
when ANTHROPIC_API_KEY is unset. Run them with `uv run pytest -m eval`.
"""

import os

import pytest

from kitchen_companion.config import Settings
from kitchen_companion.pipeline.state_note import state_note
from kitchen_companion.prompts import SYSTEM_PROMPT
from kitchen_companion.recipes.library import Library
from kitchen_companion.tools import ToolHandlers, to_anthropic_tools, tool_schemas
from tests.fakes import loaded_session, make_sink, make_timers


@pytest.fixture
def anthropic_tools() -> list[dict]:
    async def on_recipe_loaded(recipe):
        pass

    handlers = ToolHandlers(
        loaded_session(), make_timers(), Library.load_bundled(), make_sink(), on_recipe_loaded
    )
    return to_anthropic_tools(tool_schemas(handlers))


@pytest.fixture
def ask(anthropic_tools):
    """Send a conversation (user turns get the kitchen state note) and return the response."""
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    note = f"\n\n[kitchen state: {state_note(loaded_session())}]"

    async def _ask(*turns: str):
        messages = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": text + (note if i % 2 == 0 else "")}
            for i, text in enumerate(turns)
        ]
        # Match what the bot sends: Pipecat passes effort "low" and leaves thinking at the model's default.
        return await client.messages.create(
            model=Settings(_env_file=None).llm_model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=anthropic_tools,
            output_config={"effort": "low"},
            messages=messages,
        )

    return _ask
