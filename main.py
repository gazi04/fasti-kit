from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.setting import get_settings

app = FastAPI(title="Title")
settings = get_settings()


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, loop='uvloop', host="0.0.0.0", port=8000)
