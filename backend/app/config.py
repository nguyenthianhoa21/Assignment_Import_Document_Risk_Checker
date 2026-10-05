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

    # Wall-clock budget for the whole AI extraction stage of ONE document.
    # The free model list can contain several models; without a budget a slow or
    # rate-limited upstream would make each attempt burn its own timeout
    # (models x timeout) and the upload would appear to hang. Once the budget is
    # exhausted the extractor goes straight to the offline parser.
    openrouter_total_budget_seconds: float = 25.0

    # --- BGE-M3 local entity matching (offline, optional) ------------------
    # BAAI/bge-m3 is a ~2.2 GB dense encoder. When it cannot be loaded (no
    # weights on disk, not enough RAM, torch missing) BGEMatcher transparently
    # falls back to deterministic token comparison, so the API keeps serving.
    # Set BGE_MODEL_ENABLED=false to skip the load attempt entirely on hosts
    # with limited memory.
    bge_model_enabled: bool = True
    bge_model_name: str = "BAAI/bge-m3"
    # Cosine similarity required on top of zero lexical drift for a pair to be
    # considered strictly consistent.
    bge_similarity_threshold: float = 0.995

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
