import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from auth.dependencies import auth
from auth.routes import auth_router
from core.limiter import limiter
from core.logging.setup import setup_logging
from core.middlewares.correlation import CorrelationIdMiddleware
from core.setting import get_settings
from core.startup_checks import (
    StartupCheckError,
    check_database,
    check_jwt_config,
    check_mail_config,
)
from user.routes import user_router

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

auth.handle_errors(app)

app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api")
app.include_router(user_router, prefix="/api")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, loop="uvloop", host="127.0.0.1", port=8000)
