import pytest

from kitchen_companion.config import REQUIRED, Settings, missing_keys, require


def test_defaults_match_spec():
    s = Settings(_env_file=None)
    assert s.llm_model == "claude-haiku-5-5"
    assert s.wake_phrase == "chef"
    assert s.followup_window_s == 8.0
    assert s.port == 7860
    assert s.host == "0.0.0.0"
    assert s.tts_provider == "deepgram"


def test_missing_keys_reports_empty():
    s = Settings(_env_file=None, anthropic_api_key="sk-x", deepgram_api_key="")
    assert missing_keys(s, REQUIRED) == ["deepgram_api_key"]


def test_require_exits_with_upper_names():
    s = Settings(_env_file=None, anthropic_api_key="sk-x", deepgram_api_key="")
    with pytest.raises(SystemExit, match="DEEPGRAM_API_KEY"):
        require(s, REQUIRED)


def test_require_cartesia_key_when_selected():
    s = Settings(_env_file=None, anthropic_api_key="a", deepgram_api_key="d", tts_provider="cartesia")
    with pytest.raises(SystemExit, match="CARTESIA_API_KEY"):
        require(s, REQUIRED)
