from fastapi import APIRouter, HTTPException

from auth.routes import auth_router
from core.queue import task_queue
from user.routes import user_router

API_V1_PREFIX = "/api/v1"

v1_router = APIRouter(prefix=API_V1_PREFIX)
v1_router.include_router(auth_router)
v1_router.include_router(user_router)

