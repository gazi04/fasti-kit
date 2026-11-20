from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class ReplicaSettings(BaseSettings):
    database_replica_url: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_replica_settings() -> ReplicaSettings:
    return ReplicaSettings()
