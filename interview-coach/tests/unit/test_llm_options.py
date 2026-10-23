from livekit.agents import ChatContext
from livekit.plugins import anthropic as lk_anthropic

from interview_coach.agent.llm import ClaudeVoiceLLM, voice_request_options


def test_voice_options_sonnet():
    assert voice_request_options("claude-sonnet-5-5") == {
        "thinking": {"type": "between_tools"},
        "output_config": {"effort": "low"},
    }


def test_voice_options_haiku():
    assert voice_request_options("claude-haiku-5-5")["thinking"] == {"type": "disabled"}


def test_voice_options_opus_has_no_thinking_override():
    assert voice_request_options("claude-opus-5-5") == {"output_config": {"effort": "low"}}


def test_voice_options_never_sampling():
    for m in ("claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5"):
        assert not {"temperature", "top_p", "top_k", "tool_choice"} & set(voice_request_options(m))


def test_chat_merges_voice_options(monkeypatch):
    captured = {}

    def fake_chat(self, **kwargs):
        captured.update(kwargs)
        return "stream"

    monkeypatch.setattr(lk_anthropic.LLM, "chat", fake_chat)
    llm = ClaudeVoiceLLM(model="claude-sonnet-5-5", api_key="test-key")
    assert llm.chat(chat_ctx=ChatContext.empty(), extra_kwargs={"metadata": {"user_id": "u"}}) == "stream"
    assert captured["extra_kwargs"] == {
        "thinking": {"type": "between_tools"},
        "output_config": {"effort": "low"},
        "metadata": {"user_id": "u"},
    }
