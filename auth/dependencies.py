from authx import AuthX, AuthXConfig

from core.setting import get_settings

settings = get_settings()

config = AuthXConfig(
    JWT_SECRET_KEY=settings.jwt_secret_key,
    JWT_ALGORITHM='HS256',
    JWT_TOKEN_LOCATION=['headers', 'cookies'],
)

auth = AuthX(config=config)
