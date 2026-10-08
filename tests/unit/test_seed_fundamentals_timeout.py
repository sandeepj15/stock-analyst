"""Unit test for scripts/seed_fundamentals.py's per-instrument hang protection.

Regression test: a live quarterly backfill run hung for 51 minutes on one
instrument (a provider call that never returned and never timed out at the
HTTP layer), holding a DB session "idle in transaction" and blocking every
instrument queued behind it. `_sync_one` now wraps each attempt in
`asyncio.wait_for` so no single instrument can block the batch beyond a
bounded wall-clock cap, regardless of which layer misbehaves.

Uses a fake `session_scope` and a fake `sync_fundamentals` (no DB, no real
provider call, no OS thread) so this runs in milliseconds - a real blocking
`time.sleep` in a thread-pool thread would leak a non-daemon thread that
could hang pytest itself at shutdown, which is exactly the kind of problem
this fix exists to prevent, so the test uses `asyncio.sleep` instead
(properly cancellable by `asyncio.wait_for`).
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from packages.common.rate_limit import ProviderHealth, RetryPolicy
from scripts.seed_fundamentals import FundamentalsSummary, _sync_one

TEST_TIMEOUT_SECONDS = 0.1


class _FakeResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one(self) -> object:
        return self._value

    def scalar_one_or_none(self) -> object:
        return self._value


class _FakeSession:
    """Returns a fake Instrument for the first query, `None` (no prior snapshot) for the second."""

    def __init__(self) -> None:
        self._calls = 0

    async def execute(self, *args, **kwargs) -> _FakeResult:
        self._calls += 1
        if self._calls == 1:
            return _FakeResult(SimpleNamespace(id="fake-id", symbol="TESTCO", exchange="NSE"))
        return _FakeResult(None)


@asynccontextmanager
async def _fake_session_scope():
    yield _FakeSession()


@pytest.mark.asyncio
async def test_hanging_sync_times_out_instead_of_blocking_forever() -> None:
    summary = FundamentalsSummary()
    retry_policy = RetryPolicy(max_attempts=1, base_delay_seconds=0.01, max_delay_seconds=0.01)
    health = ProviderHealth(name="test")

    async def _hanging_sync(provider, session, instrument):
        await asyncio.sleep(999)  # never actually reached - the wait_for timeout fires first

    with (
        patch("scripts.seed_fundamentals.session_scope", _fake_session_scope),
        patch("scripts.seed_fundamentals.sync_fundamentals", new=_hanging_sync),
    ):
        start = asyncio.get_event_loop().time()
        await _sync_one(
            "TESTCO", "NSE", object(), retry_policy, health, summary, timeout_seconds=TEST_TIMEOUT_SECONDS
        )
        elapsed = asyncio.get_event_loop().time() - start

    # Generous upper bound (well under the old "51 minutes") - just proves
    # this returns promptly rather than hanging for the full simulated sleep.
    assert elapsed < 5.0
    assert summary.failed == 1
    assert summary.succeeded == 0
    assert len(summary.failures) == 1
    symbol, error = summary.failures[0]
    assert symbol == "TESTCO"
    assert "timed out" in error


@pytest.mark.asyncio
async def test_successful_sync_is_unaffected_by_the_timeout_wrapper() -> None:
    summary = FundamentalsSummary()
    retry_policy = RetryPolicy(max_attempts=1, base_delay_seconds=0.01, max_delay_seconds=0.01)
    health = ProviderHealth(name="test")

    async def _fast_sync(provider, session, instrument):
        return SimpleNamespace(rows_processed=0)

    with (
        patch("scripts.seed_fundamentals.session_scope", _fake_session_scope),
        patch("scripts.seed_fundamentals.sync_fundamentals", new=_fast_sync),
    ):
        await _sync_one(
            "TESTCO", "NSE", object(), retry_policy, health, summary, timeout_seconds=TEST_TIMEOUT_SECONDS
        )

    assert summary.succeeded == 1
    assert summary.failed == 0
    assert summary.no_coverage == 1
