from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from auth.dependencies import auth
from auth.routes import auth_router
from core.limiter import limiter
from core.setting import get_settings
from user.routes import user_router

settings = get_settings()

app = FastAPI(title='Title')
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

auth.handle_errors(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

app.include_router(auth_router, prefix='/api')
app.include_router(user_router, prefix='/api')

if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, loop='uvloop', host='0.0.0.0', port=8000)
