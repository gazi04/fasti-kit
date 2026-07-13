from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    db_user: Optional[str] = None
    db_password: Optional[str] = None
    db_name: Optional[str] = None
    database_url: Optional[str] = None

    allowed_origins: Optional[list[str]] = None

    backend_url: Optional[str] = "localhost:8000"

    jwt_secret_key: Optional[str] = None
    jwt_cookie_secure: Optional[str] = None

    mail_username: Optional[str] = None
    mail_password: Optional[str] = None
    mail_from: Optional[str] = None
    mail_from_name: Optional[str] = None
    mail_port: Optional[int] = None
    mail_server: Optional[str] = None
    mail_starttls: Optional[bool] = None
    mail_ssl_tls: Optional[bool] = None

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
