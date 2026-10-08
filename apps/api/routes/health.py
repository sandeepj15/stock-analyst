"""Liveness/readiness endpoints.

- GET /health         liveness only - process is up, no dependency checks
- GET /health/db      runs `SELECT 1` through the async SQLAlchemy session
- GET /health/redis   PING via redis-py's async client
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Response, status
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.config import get_settings
from packages.common.db import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    """Liveness probe - does not touch any external dependency."""
    return {"status": "ok"}


@router.get("/health/db")
async def health_db(response: Response, session: AsyncSession = Depends(get_db_session)) -> dict:
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - exercised via integration tests
        logger.error("Database health check failed", extra={"error": str(exc)})
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "error", "detail": "database unavailable"}
    return {"status": "ok"}


@router.get("/health/redis")
async def health_redis(response: Response) -> dict:
    settings = get_settings()
    client = Redis.from_url(settings.REDIS_URL)
    try:
        pong = await client.ping()
    except Exception as exc:  # pragma: no cover - exercised via integration tests
        logger.error("Redis health check failed", extra={"error": str(exc)})
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "error", "detail": "redis unavailable"}
    finally:
        await client.aclose()
    return {"status": "ok" if pong else "error"}
