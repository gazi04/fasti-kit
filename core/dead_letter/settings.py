from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class DeadLetterSettings(BaseSettings):
    retention_days: int = 30

    model_config = SettingsConfigDict(
        env_prefix="DEAD_LETTER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_dead_letter_settings() -> DeadLetterSettings:
    return DeadLetterSettings()
