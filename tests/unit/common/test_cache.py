"""packages/common/cache.py: Redis cache-aside helper.

Uses `fakeredis`'s async client (not a real Redis connection - keeps
this test fast and infra-independent, as explicitly allowed by the
task) passed explicitly via the `client=` parameter, so these tests
exercise the exact same `get_json`/`set_json` code path the app uses,
without depending on `packages.common.config.get_settings().REDIS_URL`
resolving to a reachable Redis instance in every environment this test
suite runs in (e.g. CI has no Redis service container).
"""
from __future__ import annotations

import pytest
from fakeredis import aioredis as fake_aioredis

from packages.common import cache


@pytest.fixture
async def fake_redis():
    client = fake_aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest.mark.asyncio
async def test_get_json_miss_returns_none(fake_redis):
    assert await cache.get_json("nope", client=fake_redis) is None


@pytest.mark.asyncio
async def test_set_then_get_json_round_trips(fake_redis):
    value = {"score": 83.5, "components": [1, 2, 3], "nested": {"a": True}}
    await cache.set_json("key:1", value, ttl_seconds=60, client=fake_redis)
    assert await cache.get_json("key:1", client=fake_redis) == value


@pytest.mark.asyncio
async def test_set_json_applies_a_ttl(fake_redis):
    await cache.set_json("key:ttl", {"a": 1}, ttl_seconds=60, client=fake_redis)
    ttl = await fake_redis.ttl("key:ttl")
    assert 0 < ttl <= 60


@pytest.mark.asyncio
async def test_delete_removes_key(fake_redis):
    await cache.set_json("key:del", {"a": 1}, ttl_seconds=60, client=fake_redis)
    await cache.delete("key:del", client=fake_redis)
    assert await cache.get_json("key:del", client=fake_redis) is None


@pytest.mark.asyncio
async def test_get_json_fails_open_on_broken_client():
    class BrokenClient:
        async def get(self, key):
            raise ConnectionError("redis is down")

    # Must never raise - a cache outage degrades to a miss, not an error
    # (SPEC.md section 81 rule 23 applied to infrastructure).
    assert await cache.get_json("whatever", client=BrokenClient()) is None


@pytest.mark.asyncio
async def test_set_json_fails_open_on_broken_client():
    class BrokenClient:
        async def set(self, *args, **kwargs):
            raise ConnectionError("redis is down")

    # Must not raise.
    await cache.set_json("whatever", {"a": 1}, ttl_seconds=60, client=BrokenClient())


@pytest.mark.asyncio
async def test_get_json_treats_non_json_value_as_a_miss(fake_redis):
    await fake_redis.set("bad:key", "{not valid json")
    assert await cache.get_json("bad:key", client=fake_redis) is None
