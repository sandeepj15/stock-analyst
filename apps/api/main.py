"""FastAPI application factory for SignalForge's API (apps/api).

Run locally with: `uvicorn apps.api.main:app --reload`
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from apps.api.routes import ai, analyst, fundamentals, health, instruments, market, momentum, scoring, stocks
from packages.common.config import get_settings
from packages.common.logging import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)

    app = FastAPI(
        title="SignalForge API",
        version="0.1.0",
        description="Research, analytics, and portfolio intelligence API. See SPEC.md.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    app.include_router(health.router)
    app.include_router(instruments.router)
    app.include_router(stocks.router)
    app.include_router(fundamentals.router)
    app.include_router(analyst.router)
    app.include_router(market.router)
    app.include_router(scoring.router)
    app.include_router(momentum.router)
    app.include_router(ai.router)

    return app


app = create_app()
