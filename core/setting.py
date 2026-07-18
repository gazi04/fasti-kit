from functools import lru_cache
from typing import Optional

from authx.types import AlgorithmType
from pydantic import EmailStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    db_user: Optional[str] = None
    db_password: Optional[str] = None
    db_name: Optional[str] = None
    database_url: str

    allowed_origins: list[str]

    backend_url: str = "http://localhost:8000"

    jwt_secret_key: str
    jwt_cookie_secure: bool = False
    jwt_algorithm: AlgorithmType = "HS256"

    mail_username: str
    mail_password: str
    mail_from: EmailStr
    mail_from_name: Optional[str] = None
    mail_port: int
    mail_server: str
    mail_starttls: bool
    mail_ssl_tls: bool

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    @field_validator("backend_url")
    @classmethod
    def _ensure_scheme(cls, value: str) -> str:
        if "://" not in value:
            return f"http://{value}"
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue] -- values are loaded from .env, not passed as kwargs
