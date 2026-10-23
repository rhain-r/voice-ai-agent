from pydantic_settings import BaseSettings, SettingsConfigDict

REQUIRED = ("anthropic_api_key", "deepgram_api_key")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    deepgram_api_key: str = ""
    cartesia_api_key: str = ""
    tts_provider: str = "deepgram"
    llm_model: str = "claude-haiku-5-5"
    wake_phrase: str = "chef"
    followup_window_s: float = 8.0
    host: str = "0.0.0.0"
    port: int = 7860


def missing_keys(settings: Settings, required: tuple[str, ...] = REQUIRED) -> list[str]:
    return [name for name in required if not getattr(settings, name, "")]


def require(settings: Settings, required: tuple[str, ...] = REQUIRED) -> None:
    missing = missing_keys(settings, required)
    if settings.tts_provider == "cartesia" and not settings.cartesia_api_key:
        missing.append("cartesia_api_key")
    if missing:
        names = ", ".join(name.upper() for name in missing)
        raise SystemExit(f"Missing required environment variables: {names}")
