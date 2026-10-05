from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# AI provider: OpenRouter
# ---------------------------------------------------------------------------
# The extraction pipeline talks to OpenRouter''s OpenAI-compatible
# ``/chat/completions`` endpoint via ``nvidia/nemotron-3.5-lightning:free``,
# a free, open-weights model. On timeout, 429, or malformed JSON the pipeline
# falls back to the offline deterministic parser so an AI outage can never
# produce an empty document set (an empty set would validate to a false PASSED).
DEFAULT_OPENROUTER_MODEL = "nvidia/nemotron-3.5-lightning:free"
OPENROUTER_FALLBACK_MODELS: list[str] = [
    "nvidia/nemotron-3.5-lightning:free",
    "qwen/qwen3.8-27b:free",
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Import Document Risk Checker"
    app_version: str = "0.4.1"

    database_url: str = "postgresql+psycopg2://risk_user:risk_pass@localhost:5432/risk_checker"

    # --- OpenRouter (primary AI extractor) ---------------------------------
    openrouter_api_key: str | None = None
    openrouter_model: str = DEFAULT_OPENROUTER_MODEL
    openrouter_base_url: str = "https://openrouter.ai/api/v1/chat/completions"
    openrouter_http_referer: str = "http://localhost:8000"
    openrouter_app_title: str = "Import Document Risk Checker"
    openrouter_timeout_seconds: float = 15.0
    openrouter_max_attempts: int = 3
    # Completion cap: some free reasoning models loop on a large schema and
    # never emit JSON, so the request is bounded and fails over instead.
    openrouter_max_tokens: int = 4000

    ai_temperature: float = 0.0
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

    @property
    def openrouter_models(self) -> list[str]:
        """Configured model first, then the fallbacks, deduplicated."""
        names = [self.openrouter_model, *OPENROUTER_FALLBACK_MODELS]
        seen: list[str] = []
        for name in names:
            if name and name not in seen:
                seen.append(name)
        return seen


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
