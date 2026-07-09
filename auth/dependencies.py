from authx import AuthX, AuthXConfig

from core.setting import get_settings

settings = get_settings()

config = AuthXConfig(
    JWT_SECRET_KEY=settings.jwt_secret_key,
    JWT_ALGORITHM='HS256',
    JWT_TOKEN_LOCATION=['headers', 'cookies'],
    JWT_COOKIE_SECURE=True,         # HTTPS only (set false for local environment)
    JWT_COOKIE_HTTP_ONLY=True,      # Prevent JS access
    JWT_COOKIE_CSRF_PROTECT=True,   # CSRF protection for refresh
)

auth = AuthX(config=config)
