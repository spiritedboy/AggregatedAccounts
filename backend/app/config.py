from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, case_sensitive=False, extra="ignore")

    app_env: str = "development"
    app_encryption_key: str = Field(min_length=32)
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
    sync_job_retention_days: int = 30
    balance_snapshot_retention_days: int = 90
    equity_curve_cache_seconds: int = 30
    baidu_translation_enabled: bool = False
    baidu_translation_appid: str = ""
    baidu_translation_api_key: str = ""
    baidu_translation_endpoint: str = (
        "https://fanyi-api.baidu.com/ait/api/aiTextTranslate"
    )
    baidu_translation_timeout_seconds: float = 20
    baidu_translation_batch_size: int = 20
    maintenance_hour_utc: int = 4
    maintenance_minute_utc: int = 20
    request_timeout_seconds: float = 12
    exchange_accounts_config: str = "/app/config/exchange_accounts.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
