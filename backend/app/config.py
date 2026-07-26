from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, case_sensitive=False, extra="ignore")

    app_env: str = "development"
    app_access_password: str = Field(min_length=8)
    app_encryption_key: str = Field(min_length=32)
    session_secret: str = Field(min_length=32)
    cookie_secure: bool = False
    database_url: str
    database_url_sync: str
    test_database_url: str
    demo_mode: bool = True
    sync_balance_seconds: int = 60
    sync_position_seconds: int = 15
    sync_history_seconds: int = 300
    sync_closed_position_seconds: int = 600
    sync_health_seconds: int = 60
    request_timeout_seconds: float = 12


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
