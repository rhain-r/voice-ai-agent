"""Claude for live voice turns: thinking off and low effort, so the first word arrives fast.

The LiveKit Anthropic plugin has no thinking/effort settings, so they ride along in
`extra_kwargs`, which the plugin passes straight to `messages.create`.
"""

from typing import Any

from livekit.agents import DEFAULT_API_CONNECT_OPTIONS, NOT_GIVEN, APIConnectOptions, NotGivenOr
from livekit.agents.utils import is_given
from livekit.plugins import anthropic as lk_anthropic


def voice_request_options(model: str, effort: str = "low") -> dict:
    options: dict[str, Any] = {"output_config": {"effort": effort}}
    if model.startswith("claude-sonnet-5-5"):
        options["thinking"] = {"type": "between_tools"}  # the lowest setting Sonnet 5.5 accepts
    elif model.startswith("claude-haiku-5-5"):
        options["thinking"] = {"type": "disabled"}
    return options


class ClaudeVoiceLLM(lk_anthropic.LLM):
    def __init__(self, *, model: str, effort: str = "low", **kwargs: Any) -> None:
        super().__init__(model=model, **kwargs)
        self._voice_options = voice_request_options(model, effort)

    def chat(
        self,
        *,
        chat_ctx,
        tools=None,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
        parallel_tool_calls: NotGivenOr[bool] = NOT_GIVEN,
        tool_choice=NOT_GIVEN,
        extra_kwargs: NotGivenOr[dict[str, Any]] = NOT_GIVEN,
    ):
        merged = {**self._voice_options, **(extra_kwargs if is_given(extra_kwargs) else {})}
        return super().chat(
            chat_ctx=chat_ctx,
            tools=tools,
            conn_options=conn_options,
            parallel_tool_calls=parallel_tool_calls,
            tool_choice=tool_choice,
            extra_kwargs=merged,
        )
