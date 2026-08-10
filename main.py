import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi_pagination import add_pagination
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from auth.dependencies import auth
from core.api_versions import v1_router
from core.exception import DomainException, domain_exception_handler
from core.limiter import limiter
from core.logging.setup import setup_logging
from core.middlewares.correlation import CorrelationIdMiddleware
from core.middlewares.n1_detector import N1DetectorMiddleware
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
    try:
        await check_database()
        await check_mail_config()
        await check_jwt_config()
    except StartupCheckError as e:
        logger.error(f"Startup checks failed: {e}")
        raise

    yield
    logger.info("Application shutting down...")


app = FastAPI(title="Title", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
app.add_exception_handler(DomainException, domain_exception_handler)  # type: ignore[arg-type]

auth.handle_errors(app)

app.add_middleware(GZipMiddleware, minimum_size=1000)
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

add_pagination(app)

app.include_router(v1_router)

Instrumentator().instrument(app).expose(app)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, loop="uvloop", host="127.0.0.1", port=8000)
