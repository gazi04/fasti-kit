from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class OutboxSettings(BaseSettings):
    poll_interval: float = 5.0
    batch_size: int = 100
    max_attempts: int = 10
    retention_days: int = 7
    max_lag_seconds: float = 60.0

    model_config = SettingsConfigDict(
        env_prefix="OUTBOX_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_outbox_settings() -> OutboxSettings:
    return OutboxSettings()
