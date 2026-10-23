"""Settings shared by the agent worker, API and MCP server (spec §9)."""

from collections.abc import Sequence

from pydantic_settings import BaseSettings, SettingsConfigDict

AGENT_REQUIRED = (
    "anthropic_api_key",
    "deepgram_api_key",
    "livekit_url",
    "livekit_api_key",
    "livekit_api_secret",
    "agent_shared_secret",
)
API_REQUIRED = (
    "anthropic_api_key",
    "livekit_url",
    "livekit_api_key",
    "livekit_api_secret",
    "agent_shared_secret",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    deepgram_api_key: str = ""
    cartesia_api_key: str = ""
    tts_provider: str = "deepgram"
    livekit_url: str = "ws://localhost:7880"
    livekit_api_key: str = "devkey"
    livekit_api_secret: str = "secret"
    mcp_url: str = "http://localhost:8765/mcp"
    api_url: str = "http://localhost:8000"
    agent_shared_secret: str = "change-me"
    live_model: str = "claude-sonnet-5-5"
    fallback_model: str = "claude-haiku-5-5"
    grader_model: str = "claude-opus-5-5"
    otel_exporter_otlp_endpoint: str = ""


def missing_keys(settings: Settings, required: Sequence[str]) -> list[str]:
    return [name for name in required if not str(getattr(settings, name, "") or "").strip()]


def cli_needs_keys(argv: Sequence[str]) -> bool:
    """LiveKit CLI run modes need keys; `download-files` and help output do not."""
    args = list(argv[1:])
    return bool(args) and not {"download-files", "--help", "-h"} & set(args)


def require(settings: Settings, required: Sequence[str]) -> None:
    missing = missing_keys(settings, required)
    if missing:
        names = ", ".join(name.upper() for name in missing)
        raise SystemExit(f"Missing required environment variables: {names}")
