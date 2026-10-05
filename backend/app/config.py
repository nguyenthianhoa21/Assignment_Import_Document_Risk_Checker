from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# Models that support the unary ``generate_content`` endpoint used by the
# extraction pipeline. Gemini "live" variants (``gemini-3-flash-live``,
# ``gemini-3.8-live``) only expose the bidirectional WebSocket
# ``bidiGenerateContent`` API and are therefore rejected by the SDK with
# ``INVALID_ARGUMENT``. They are kept last as a probe target only.
ACTIVE_GEMINI_MODELS: list[str] = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-flash-latest",
    "gemini-3-flash-live",
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Import Document Risk Checker"
    app_version: str = "0.3.0"

    database_url: str = "postgresql+psycopg2://risk_user:risk_pass@localhost:5432/risk_checker"

    # Single legacy key (still honoured when the pool is empty).
    gemini_api_key: str | None = None
    # Comma-separated key pool used for rotation; overrides the legacy key.
    gemini_api_keys: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    gemini_rpm_limit: int = 15
    ai_temperature: float = 0.0
    # When every key is out of quota, fall back to the offline parser
    # instead of failing the document.
    offline_fallback_enabled: bool = True

    upload_dir: str = "uploads"
    max_upload_mb: int = 25
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
