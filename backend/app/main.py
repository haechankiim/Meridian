"""Meridian — FastAPI entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routes import analytics, backtest, data, models, strategies
from backend.app.config import get_settings
from backend.app.database import init_db

settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB on startup."""
    try:
        await init_db()
    except Exception as exc:
        logger.warning("Skipping database initialization during startup: %s", exc)
    yield


app = FastAPI(
    title="Meridian",
    description="Algorithmic Trading Backtester with ML Signal Generation",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "meridian"}


app.include_router(data.router, prefix="/api/v1/data", tags=["data"])
app.include_router(backtest.router, prefix="/api/v1/backtest", tags=["backtest"])
app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["analytics"])
app.include_router(strategies.router, prefix="/api/v1/strategy", tags=["strategy"])
app.include_router(models.router, prefix="/api/v1/models", tags=["models"])
