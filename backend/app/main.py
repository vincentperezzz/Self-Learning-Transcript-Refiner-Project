"""Phoenix 3.0 – Self-Learning Transcript Refiner (FastAPI entry point)."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.cache import close_redis
from app.database import close_pool, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure DB tables exist
    init_db()
    yield
    # Shutdown: close connection pool and Redis
    close_pool()
    close_redis()


app = FastAPI(
    title="Phoenix 3.0 – Transcript Refiner",
    description=(
        "A self-learning, deterministic-first transcript refiner "
        "using Semantic Anchors, N-Gram Co-occurrence, and DistilBERT."
    ),
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")
