from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Import Document Risk Checker"
    app_version: str = "0.2.0"

    database_url: str = "postgresql+psycopg2://risk_user:risk_pass@localhost:5432/risk_checker"

    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.0-flash"
    gemini_rpm_limit: int = 15
    ai_temperature: float = 0.0

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
