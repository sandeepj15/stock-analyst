"""Async SQLAlchemy 2.x engine/session management.

A single module-level engine is created lazily from Settings.DATABASE_URL.
`get_db_session` is a FastAPI dependency that yields an AsyncSession and
guarantees it is closed after the request. Background jobs (Arq) and
scripts should use `session_scope()` instead.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from packages.common.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.DATABASE_URL,
        pool_size=5,
        max_overflow=5,
        pool_recycle=300,
        pool_pre_ping=True,
        future=True,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=get_engine(), expire_on_commit=False, class_=AsyncSession)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: `session: AsyncSession = Depends(get_db_session)`."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        yield session


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for use outside of FastAPI (worker jobs, scripts).

    Commits on success, rolls back on exception.
    """
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
