"""Shared pytest fixtures.

Model layer rationale (documented here and in README.md): the ORM models
use PostgreSQL-specific types (UUID, JSONB, native ENUM) and the ingestion
service relies on `postgresql.insert(...).on_conflict_do_update(...)`,
which has no SQLite equivalent. Rather than fork the schema for a
SQLite-only test path, every test in this suite that touches the
database runs against a real (disposable) Postgres instance.

Locally: point `TEST_DATABASE_URL` at any scratch Postgres database (see
README.md "Running tests locally"). In CI: `.github/workflows/ci.yml`
starts a `postgres:16` service container and sets `TEST_DATABASE_URL`
accordingly. No test may hit the network or a real market-data provider.
"""
from __future__ import annotations

import os

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import packages.analyst_estimates.models  # noqa: F401  (registers tables on Base.metadata)
import packages.fundamentals.models  # noqa: F401  (registers tables on Base.metadata)
import packages.market_data.models  # noqa: F401  (registers tables on Base.metadata)
import packages.momentum.models  # noqa: F401  (registers tables on Base.metadata)
import packages.regime.models  # noqa: F401  (registers tables on Base.metadata)
import packages.scoring.models  # noqa: F401  (registers tables on Base.metadata)
from packages.common.models import Base

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://signalforge:signalforge@localhost:5432/signalforge_test",
)


@pytest_asyncio.fixture
async def engine():
    """Function-scoped on purpose: pytest-asyncio gives each test function
    its own event loop, and asyncpg connections cannot be reused across
    event loops. A session-scoped engine would intermittently fail with
    'another operation is in progress' / cross-loop errors.
    """
    eng = create_async_engine(TEST_DATABASE_URL, future=True)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db_session(engine):
    """A fresh AsyncSession per test, backed by a freshly created schema."""
    sessionmaker = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with sessionmaker() as session:
        yield session
