import logging
from contextlib import asynccontextmanager
from importlib.metadata import metadata

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi_pagination import add_pagination
from prometheus_fastapi_instrumentator import Instrumentator
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from auth.errors import install_auth_error_handlers
from core.api_versions import v1_router
from core.database import dispose_engines
from core.dead_letter.router import dlq_router
from core.health import health_router
from core.limiter import limiter
from core.logging.setup import setup_logging
from core.middlewares.correlation import CorrelationIdMiddleware
from core.middlewares.n1_detector import N1DetectorMiddleware
from core.middlewares.security_headers import SecurityHeadersMiddleware
from core.openapi import setup_openapi
from core.problem import install_problem_handlers
from core.redis import close_redis
from core.setting import get_settings
from core.startup_checks import (
    StartupCheckError,
    check_database,
    check_jwt_config,
    check_mail_config,
)

settings = get_settings()
setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Application starting up... Environment: {settings.environment}")
    logger.info("Trusting proxy headers from: %s", settings.forwarded_allow_ips)
    try:
        await check_database()
        await check_mail_config()
        await check_jwt_config()
    except StartupCheckError as e:
        logger.error(f"Startup checks failed: {e}")
        raise

    try:
        yield
    finally:
        logger.info("Application shutting down — releasing resources...")
        for label, closer in (
            ("database engines", dispose_engines),
            ("redis", close_redis),
        ):
            try:
                await closer()
            except Exception:
                logger.exception("Failed to release %s cleanly on shutdown", label)


project = metadata("fasti-kit")
app = FastAPI(
    title=project["Name"],
    summary=project["Summary"],
    version=project["Version"],
    lifespan=lifespan,
)
app.state.limiter = limiter
install_problem_handlers(app)
install_auth_error_handlers(app)


app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    SecurityHeadersMiddleware,
    include_hsts=settings.environment == "production",
)
app.add_middleware(CorrelationIdMiddleware)

if settings.environment == "local":
    app.add_middleware(N1DetectorMiddleware, threshold=10)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    ProxyHeadersMiddleware,
    trusted_hosts=settings.forwarded_allow_ips,
)

setup_openapi(app)
add_pagination(app)

app.include_router(health_router)
app.include_router(dlq_router)
app.include_router(v1_router)

Instrumentator().instrument(app).expose(app)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        loop="uvloop",
        host="127.0.0.1",
        port=8000,
        proxy_headers=False,
        log_config=None,
        timeout_graceful_shutdown=settings.shutdown_timeout,
    )
