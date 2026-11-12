import ipaddress
import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from authx.types import AlgorithmType
from pydantic import (
    EmailStr,
    Field,
    computed_field,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

DOCKER_BRIDGE_HOST_IP = "172.17.0.1"
COMPOSE_CADDY_IP = "172.28.0.10"


CGROUP_CPU_MAX = Path("/sys/fs/cgroup/cpu.max")


def cgroup_cpu_limit(cpu_max: Path = CGROUP_CPU_MAX) -> int | None:
    try:
        quota, period = cpu_max.read_text().split()
        return max(1, math.ceil(int(quota) / int(period)))
    except (OSError, ValueError):
        return None


def available_cpus() -> int:
    visible = os.process_cpu_count() or 1
    return min(visible, cgroup_cpu_limit() or visible)


def _default_password_hash_workers() -> int:
    return max(1, available_cpus() - 1)


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",")]


class Settings(BaseSettings):
    environment: Literal["local", "staging", "production"] = "local"

    db_user: str | None = None
    db_password: str | None = None
    db_name: str | None = None
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    db_pool_recycle: int = 3600
    db_echo: bool = False
    database_url: str

    allowed_origins: list[str]

    backend_url: str = "http://localhost:8000"
    server_hosts: str = f"127.0.0.1,{DOCKER_BRIDGE_HOST_IP}"

    forwarded_allow_ips: str = "127.0.0.1,::1"

    jwt_secret_key: str
    jwt_cookie_secure: bool = False
    jwt_algorithm: AlgorithmType = "HS256"
    jwt_refresh_token_ttl_days: int = 20
    refresh_reuse_grace_seconds: int = 10

    mail_username: str | None = None
    mail_password: str | None = None
    mail_from: EmailStr
    mail_from_name: str | None = None
    mail_port: int
    mail_server: str
    mail_starttls: bool
    mail_ssl_tls: bool

    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_db: int = 0

    cache_prefix: str = "fasti-cache"
    cache_default_ttl: int = 3600

    # Seconds uvicorn waits for in-flight requests to finish on SIGTERM/SIGINT
    # before force-cancelling them.
    shutdown_timeout: int = 30

    outbox_poll_interval: float = 5.0
    outbox_batch_size: int = 100
    outbox_max_attempts: int = 10
    outbox_retention_days: int = 7
    outbox_max_lag_seconds: float = 60.0

    password_hash_workers: int = Field(
        default_factory=_default_password_hash_workers, ge=1
    )
    password_hash_queue_per_worker: int = Field(default=4, ge=1)
    password_hash_retry_after: int = Field(default=1, ge=1)

    dead_letter_retention_days: int = 30
    task_max_retries: int = 3
    task_retry_delay: float = 5.0
    task_retry_backoff: bool = True

    database_replica_url: str | None = None

    @computed_field
    @property
    def is_deployed(self) -> bool:
        return self.environment != "local"

    @computed_field
    @property
    def get_replica_url(self) -> str:
        if self.database_replica_url:
            return self.database_replica_url
        return self.database_url

    @computed_field
    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    @field_validator("backend_url")
    @classmethod
    def _ensure_scheme(cls, value: str) -> str:
        if "://" not in value:
            return f"http://{value}"
        return value

    @computed_field
    @property
    def server_host_list(self) -> list[str]:
        return _split_csv(self.server_hosts)

    @field_validator("server_hosts")
    @classmethod
    def _validate_server_hosts(cls, value: str) -> str:
        for entry in _split_csv(value):
            try:
                ipaddress.ip_address(entry)
            except ValueError as exc:
                raise ValueError(
                    f"SERVER_HOSTS entry {entry!r} is not an IP address"
                ) from exc
        return value

    @model_validator(mode="after")
    def _trust_compose_caddy_locally(self) -> "Settings":
        uses_default_trust = "forwarded_allow_ips" not in self.model_fields_set
        if uses_default_trust and self.environment == "local":
            self.forwarded_allow_ips = f"{self.forwarded_allow_ips},{COMPOSE_CADDY_IP}"
        return self

    @field_validator("forwarded_allow_ips")
    @classmethod
    def _validate_forwarded_allow_ips(cls, value: str) -> str:
        for entry in _split_csv(value):
            if entry == "*":
                continue
            try:
                if "/" in entry:
                    ipaddress.ip_network(entry)
                else:
                    ipaddress.ip_address(entry)
            except ValueError as exc:
                raise ValueError(
                    f"FORWARDED_ALLOW_IPS entry {entry!r} is not an IP address, "
                    "a CIDR network or '*'"
                ) from exc
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue] -- values are loaded from .env, not passed as kwargs
