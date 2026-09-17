from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Ioka Flight Booking API"
    app_env: str = "local"
    log_level: str = "INFO"
    database_url: str = "sqlite+aiosqlite:///./ioka.db"
    redis_url: str = "redis://localhost:6379/0"
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    search_dispatch_mode: Literal["inline", "rabbitmq"] = "inline"
    search_timeout_seconds: float = 20
    provider_timeout_seconds: float = 15
    search_ttl_seconds: int = 900
    jwt_secret: str = Field(default="local-development-secret-change-me-please")
    jwt_issuer: str = "ioka-flight-booking"
    jwt_audience: str = "ioka-agents"
    jwt_ttl_minutes: int = 60
    default_agent_email: str = "agent@ioka.local"
    default_agent_password: str = "ChangeMe123!"
    default_agent_balance: float = 10_000_000.0
    auto_create_schema: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
