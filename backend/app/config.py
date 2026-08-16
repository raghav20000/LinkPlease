"""
Centralized configuration. Everything that varies between local/dev/prod
comes from environment variables so nothing sensitive is hardcoded or
committed. See .env.example for the full list.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mongodb_uri: str = "MONGODB_URI"
    mongodb_db_name: str = "LinkPlease"

    pseudogram_base_url: str = "https://pseudogram-api.onrender.com"
    pseudogram_api_key: str = "PSEUDOGRAM_API_KEY"

    allowed_origins: str = "http://localhost:5173"

    dm_max_attempts: int = 6
    dm_worker_poll_seconds: float = 1.0
    pseudogram_rate_limit_per_minute: int = 10

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
