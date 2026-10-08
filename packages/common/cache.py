"""Redis cache-aside helper (SPEC.md section 59: "use cached data", not
uncontrolled per-request recomputation).

Reuses the existing `REDIS_URL` setting (`packages/common/config.py`) -
this is the same Redis instance already used by `arq` for the job
queue, just a different logical use of it (its first application-level
cache usage). A thin `get_json`/`set_json` pair is intentionally all
this module offers: callers own their own key naming and TTL choice
(documented at each call site) rather than this module baking in any
policy.

Fails open: any Redis error (connection refused, timeout, bad data) is
caught, logged, and treated as a cache miss / no-op rather than raised.
A cache being unavailable must never turn into a user-facing 500 - every
caller already has a DB-read/live-compute fallback path, so a Redis
outage degrades latency, not correctness (SPEC.md section 81 rule 23
applied to infrastructure, not just data).
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

from redis.asyncio import Redis

from packages.common.config import get_settings

logger = logging.getLogger(__name__)

# Short socket/connect timeouts so a dead/unreachable Redis degrades a
# request by milliseconds, never by hanging it (SPEC.md section 59's
# "rate limiter / retry policy / timeout / circuit breaker" discipline,
# applied to our own cache dependency too, not just external providers).
_SOCKET_TIMEOUT_SECONDS = 1.0


@lru_cache
def get_redis_client() -> Redis:
    settings = get_settings()
    return Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=_SOCKET_TIMEOUT_SECONDS,
        socket_timeout=_SOCKET_TIMEOUT_SECONDS,
    )


async def get_json(key: str, *, client: Redis | None = None) -> Any | None:
    """Return the cached value at `key`, or `None` on a miss or any cache error."""
    redis_client = client if client is not None else get_redis_client()
    try:
        raw = await redis_client.get(key)
    except Exception as exc:  # noqa: BLE001 - deliberately broad, see module docstring
        logger.warning("cache get failed, treating as a miss", extra={"key": key, "error": str(exc)})
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        logger.warning("cached value was not valid JSON, treating as a miss", extra={"key": key})
        return None


async def set_json(key: str, value: Any, ttl_seconds: int, *, client: Redis | None = None) -> None:
    """Cache `value` (any JSON-serializable object) at `key` for `ttl_seconds`.

    Never raises - a failed cache write just means the next read is
    another miss, which is always safe (every caller falls back to a
    live computation).
    """
    redis_client = client if client is not None else get_redis_client()
    try:
        await redis_client.set(key, json.dumps(value), ex=ttl_seconds)
    except Exception as exc:  # noqa: BLE001 - see module docstring
        logger.warning("cache set failed, continuing without caching", extra={"key": key, "error": str(exc)})


async def delete(key: str, *, client: Redis | None = None) -> None:
    """Best-effort cache invalidation. Never raises."""
    redis_client = client if client is not None else get_redis_client()
    try:
        await redis_client.delete(key)
    except Exception as exc:  # noqa: BLE001 - see module docstring
        logger.warning("cache delete failed", extra={"key": key, "error": str(exc)})


async def delete_pattern(pattern: str, *, client: Redis | None = None) -> int:
    """Best-effort invalidation of every key matching `pattern` (e.g. "instruments_listing:v1:*").

    Used by `apps/worker/jobs.py::daily_market_close_sync` to proactively
    refresh the `GET /api/v1/instruments` listing cache immediately after
    a fresh batch score/momentum run, instead of waiting for its existing
    short TTL to lapse (SPEC.md section 59). Uses the non-blocking `SCAN`
    cursor (`scan_iter`) rather than Redis' blocking `KEYS` command, so
    this never stalls other Redis clients even against a large keyspace.

    Never raises - same fail-open contract as every other function in
    this module (a failed invalidation just means the next read is
    served from the old cached value until its TTL naturally expires,
    which every caller already tolerates as a non-fatal case).

    Returns the number of keys actually deleted (best-effort count, 0 on
    any error).
    """
    redis_client = client if client is not None else get_redis_client()
    deleted = 0
    try:
        async for key in redis_client.scan_iter(match=pattern, count=200):
            await redis_client.delete(key)
            deleted += 1
    except Exception as exc:  # noqa: BLE001 - see module docstring
        logger.warning("cache delete_pattern failed", extra={"pattern": pattern, "error": str(exc)})
    return deleted
