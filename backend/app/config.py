from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# AI provider: OpenRouter
# ---------------------------------------------------------------------------
# The extraction pipeline talks to OpenRouter's OpenAI-compatible
# ``/chat/completions`` endpoint. ``qwen/qwen3.8-27b:free`` is a free,
# open-weights model, so the project needs no paid AI quota.
#
# Fallback models are tried in order when the primary one is unavailable or
# rate-limited. When every model fails, the pipeline falls back to the offline
# deterministic parser, so an AI outage can never produce an empty document
# set (an empty set would validate to a false PASSED verdict).
DEFAULT_OPENROUTER_MODEL = "qwen/qwen3.8-27b:free"
OPENROUTER_FALLBACK_MODELS: list[str] = [
    "qwen/qwen3.8-27b:free",
    "qwen/qwen3-32b:free",
    "deepseek/deepseek-chat-v3-0324:free",
    "mistralai/mistral-small-3.2-24b-instruct:free",
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Import Document Risk Checker"
    app_version: str = "0.4.0"

    database_url: str = "postgresql+psycopg2://risk_user:risk_pass@localhost:5432/risk_checker"

    # --- OpenRouter (primary AI extractor) ---------------------------------
    openrouter_api_key: str | None = None
    openrouter_model: str = DEFAULT_OPENROUTER_MODEL
    openrouter_base_url: str = "https://openrouter.ai/api/v1/chat/completions"
    # OpenRouter identifies the caller in its dashboard from these two headers.
    openrouter_http_referer: str = "http://localhost:8000"
    openrouter_app_title: str = "Import Document Risk Checker"
    # Per-request timeout in seconds; free models can be slow to cold-start.
    openrouter_timeout_seconds: float = 15.0
    # Free-tier models are rate limited per day; retries stay bounded.
    openrouter_max_attempts: int = 3

    ai_temperature: float = 0.0
    # When the AI provider fails, fall back to the offline deterministic
    # parser instead of failing the document.
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
