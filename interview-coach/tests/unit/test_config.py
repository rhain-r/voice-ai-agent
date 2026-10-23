import pytest

from interview_coach.config import Settings, cli_needs_keys, missing_keys, require


@pytest.mark.parametrize(
    "argv,needs",
    [
        (["coach-agent", "start"], True),
        (["coach-agent", "dev"], True),
        (["coach-agent", "download-files"], False),
        (["coach-agent", "--help"], False),
        (["coach-agent"], False),
    ],
)
def test_cli_needs_keys_only_for_run_modes(argv, needs):
    assert cli_needs_keys(argv) is needs


def test_missing_keys_reports_empty_and_unset():
    s = Settings(_env_file=None, anthropic_api_key="", deepgram_api_key="x")
    assert missing_keys(s, ("anthropic_api_key", "deepgram_api_key")) == ["anthropic_api_key"]


def test_require_exits_with_upper_names():
    s = Settings(_env_file=None, anthropic_api_key="")
    with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY"):
        require(s, ("anthropic_api_key",))


def test_defaults_match_spec():
    s = Settings(_env_file=None)
    assert (s.live_model, s.fallback_model, s.grader_model) == (
        "claude-sonnet-5-5",
        "claude-haiku-5-5",
        "claude-opus-5-5",
    )
    assert s.mcp_url == "http://localhost:8765/mcp" and s.tts_provider == "deepgram"
