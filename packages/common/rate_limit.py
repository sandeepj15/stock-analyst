"""Shared rate-limiting/retry/concurrency helpers (SPEC.md section 59).

SPEC.md section 59 requires every external provider integration to have a
rate limiter, a retry policy, a timeout, and basic provider-health
awareness, and explicitly forbids letting user requests fan out into
uncontrolled external calls. This module is the one place that logic
lives so every provider/ingestion path (yfinance market data, yfinance
fundamentals, tradingview-ta fundamentals, the NSE universe CSV fetch)
reuses the same small, tested primitives instead of each hand-rolling
its own sleep/retry loop.

Nothing here is provider-specific - it has no knowledge of yfinance,
tradingview_ta, or HTTP at all. It only knows "run this blocking
callable, with a jittered delay, bounded concurrency, and
retry-with-backoff on transient failure."
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class RetryPolicy:
    """Simple exponential-backoff-with-jitter retry policy.

    Deliberately small and explicit (not a generic "retry anything"
    framework) - callers decide what counts as a transient failure by
    catching only the exception types they expect from a given provider.
    """

    max_attempts: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 10.0
    jitter_seconds: float = 0.5

    def delay_for_attempt(self, attempt: int) -> float:
        """`attempt` is 1-indexed (the delay *before* retrying attempt N+1)."""
        backoff = min(self.base_delay_seconds * (2 ** (attempt - 1)), self.max_delay_seconds)
        return backoff + random.uniform(0, self.jitter_seconds)


@dataclass
class ProviderHealth:
    """Minimal circuit-breaker/provider-health tracker.

    Not a full circuit-breaker state machine - just enough to satisfy
    SPEC.md section 59's "provider health" + "circuit breaker" bullets at
    this project's scale: after `failure_threshold` *consecutive*
    failures, `is_open` reports the circuit as open (callers should stop
    hammering the provider and surface the outage) until a success
    resets the counter.
    """

    name: str
    failure_threshold: int = 10
    consecutive_failures: int = 0
    total_attempts: int = 0
    total_failures: int = 0

    def record_success(self) -> None:
        self.total_attempts += 1
        self.consecutive_failures = 0

    def record_failure(self) -> None:
        self.total_attempts += 1
        self.total_failures += 1
        self.consecutive_failures += 1

    @property
    def is_open(self) -> bool:
        return self.consecutive_failures >= self.failure_threshold


def sleep_with_jitter(min_seconds: float, max_seconds: float) -> None:
    """Blocking randomized delay - used between *synchronous* provider calls.

    SPEC.md section 59: bursty, uncontrolled sequential traffic against
    an unofficial/free provider (yfinance) is exactly what must be
    avoided at hundreds-of-symbols scale.
    """
    time.sleep(random.uniform(min_seconds, max_seconds))


def call_with_retry[T](
    fn: Callable[[], T],
    *,
    policy: RetryPolicy,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    health: ProviderHealth | None = None,
    on_retry: Callable[[int, BaseException], None] | None = None,
) -> T:
    """Run a blocking `fn`, retrying on exceptions in `retry_on` per `policy`.

    Raises the last exception if every attempt fails. Updates `health`
    (if given) on every attempt's outcome.
    """
    last_exc: BaseException | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            result = fn()
        except retry_on as exc:  # noqa: BLE001 - caller controls the exception set
            last_exc = exc
            if health is not None:
                health.record_failure()
            if attempt >= policy.max_attempts:
                break
            delay = policy.delay_for_attempt(attempt)
            if on_retry is not None:
                on_retry(attempt, exc)
            time.sleep(delay)
            continue
        else:
            if health is not None:
                health.record_success()
            return result

    assert last_exc is not None  # pragma: no cover - loop always sets this before breaking
    raise last_exc


@dataclass
class BoundedConcurrencyRunner:
    """Run many blocking jobs concurrently via a thread pool, bounded by a semaphore.

    SPEC.md section 59 forbids *uncontrolled* fan-out, not concurrency
    itself - this caps the number of in-flight provider calls at
    `max_concurrency` (a handful, not hundreds) and adds a small
    randomized delay before each call so even the bounded concurrent
    traffic doesn't look like a burst to the upstream provider.
    """

    max_concurrency: int = 6
    min_delay_seconds: float = 0.1
    max_delay_seconds: float = 0.3
    _semaphore: asyncio.Semaphore = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._semaphore = asyncio.Semaphore(self.max_concurrency)

    async def run[T](self, blocking_fn: Callable[[], T]) -> T:
        """Run `blocking_fn` (a plain sync callable) in a worker thread.

        Acquires the semaphore first (bounding concurrency), sleeps a
        small random delay, then runs the callable off the event loop via
        `asyncio.to_thread` so one slow/blocking yfinance call never
        blocks the other concurrent tasks' bookkeeping.
        """
        async with self._semaphore:
            await asyncio.sleep(random.uniform(self.min_delay_seconds, self.max_delay_seconds))
            return await asyncio.to_thread(blocking_fn)


async def run_bounded[T](
    items: list[T],
    worker: Callable[[T], Awaitable[None]],
    *,
    max_concurrency: int = 6,
) -> None:
    """Run `worker(item)` for every item in `items`, at most `max_concurrency` at once.

    `worker` is expected to catch its own per-item exceptions (the
    "one bad symbol must never abort the run" rule) - this helper only
    bounds concurrency, it does not swallow errors.
    """
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _run_one(item: T) -> None:
        async with semaphore:
            await worker(item)

    await asyncio.gather(*(_run_one(item) for item in items))
