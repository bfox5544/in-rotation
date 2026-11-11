import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .album_map import router as map_router
from .catalog import get_catalog
from .chat.routes import router as chat_router
from .db import check_schema
from .engine import get_engine
from .covers import router as covers_router
from .feedback import router as feedback_router
from .insights import router as insights_router
from .listen import router as listen_router
from .profiles import router as profiles_router
from .routes import router

# backend/.env: GEMINI_API_KEY and the settings in backend/.env.example. Real environment variables win.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    check_schema()  # fail at startup, with the fix, if Postgres is down or not migrated
    get_catalog()   # fail at startup, with build instructions, if catalog.db or the model is missing
    get_engine()
    get_catalog().warm_lengths()   # For You's length filter (ADR 0026), in the background
    yield


app = FastAPI(title="In Rotation API", version="0.6.0", lifespan=lifespan)
# Only the Vite dev server needs CORS. Deployed, Caddy serves the site and the API from one origin (set it empty).
_origins = os.environ.get("INROTATION_CORS_ORIGINS", "http://localhost:5173")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(covers_router)
app.include_router(listen_router)
app.include_router(insights_router)
app.include_router(profiles_router)
app.include_router(feedback_router)
app.include_router(chat_router)
app.include_router(map_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
