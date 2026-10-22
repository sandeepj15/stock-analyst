"""Arq worker configuration.

Run with: `arq apps.worker.settings.WorkerSettings`
"""
from __future__ import annotations

from datetime import UTC

from arq import cron
from arq.connections import RedisSettings

from apps.worker.jobs import (
    check_missed_market_close_sync,
    compute_all_momentum_scans_job,
    compute_all_scores_job,
    compute_all_vcp_scans_job,
    daily_market_close_sync,
    generate_ml_forecasts_job,
    sync_analyst_estimates_job,
    sync_daily_bars,
    sync_fundamentals_job,
    sync_market_regime,
    sync_quarterly_fundamentals_job,
    sync_recent_earnings_job,
    generate_daily_ai_alpha_picks_job,
)
from packages.common.config import get_settings
from packages.common.logging import configure_logging

_settings = get_settings()


async def startup(ctx: dict) -> None:
    configure_logging(_settings.LOG_LEVEL)


async def shutdown(ctx: dict) -> None:
    pass


class WorkerSettings:
    job_timeout = 3600  # 1 hour timeout for batch processing of 1,510 stocks
    functions = [
        sync_daily_bars,
        sync_fundamentals_job,
        sync_quarterly_fundamentals_job,
        sync_analyst_estimates_job,
        sync_market_regime,
        compute_all_scores_job,
        compute_all_momentum_scans_job,
        compute_all_vcp_scans_job,
        generate_ml_forecasts_job,
        # Also independently/manually callable (e.g. `docker compose exec
        # worker python -c "..."`, same pattern as every job above) in
        # addition to running on the cron schedule below.
        daily_market_close_sync,
        check_missed_market_close_sync,
        sync_recent_earnings_job,
        generate_daily_ai_alpha_picks_job,
    ]
    cron_jobs = [
        cron(
            daily_market_close_sync,
            timeout=3600,
            # --- IST <-> UTC reasoning (read this before touching the schedule) ---
            # NSE (National Stock Exchange, India) closes at 15:30 IST.
            # IST is a fixed UTC+5:30 offset year-round (India observes no
            # DST), so 15:30 IST == 10:00 UTC. EOD bars from the free
            # yfinance data source are not always available the instant
            # the market closes, so this schedule adds a ~3-hour safety
            # buffer on top of that: 18:30 IST == 13:00 UTC
            # (18:30 - 05:30 = 13:00). `DAILY_SYNC_HOUR_UTC` /
            # `DAILY_SYNC_MINUTE_UTC` (packages/common/config.py) default
            # to 13:00 UTC == 18:30 IST for exactly this reason - tune
            # those settings, never hardcode a different value here.
            #
            # --- weekday numbering (verified, not assumed) ---
            # `weekday=(0, 1, 2, 3, 4)` means Monday-Friday only, never a
            # weekend. Confirmed directly from arq's installed source
            # (.venv/lib/python3.12/site-packages/arq/cron.py,
            # `_get_next_dt`'s `next_v = dt_.weekday()`): arq's `cron()`
            # weekday parameter is evaluated via Python's stdlib
            # `datetime.weekday()`, whose convention is Monday == 0 ...
            # Sunday == 6 (NOT Sunday == 0) - so `(0, 1, 2, 3, 4)` is
            # exactly Mon/Tue/Wed/Thu/Fri. (arq also accepts weekday-name
            # strings via `arq.typing.WEEKDAYS = ('mon', 'tues', 'wed',
            # 'thurs', 'fri', 'sat', 'sun')`, but only a *single* name
            # string is special-cased in `cron()` - a multi-day schedule
            # must use a set/list/tuple of ints, as done here - arq's own
            # type stub (`arq.typing.WeekdayOptionType`) is specifically
            # `set[int]`, so a `set` is used here rather than a tuple.)
            #
            # Known limitation (SPEC.md section 81, not fixed here): NSE
            # holidays aren't modeled, so this still fires on NSE holidays
            # that land on a weekday; yfinance just returns no new bar for
            # that date, which the existing missing-trading-day data
            # quality check already treats as a harmless, documented
            # weekday-approximation gap (see `daily_market_close_sync`'s
            # docstring in apps/worker/jobs.py).
            weekday={0, 1, 2, 3, 4},
            hour=_settings.DAILY_SYNC_HOUR_UTC,
            minute=_settings.DAILY_SYNC_MINUTE_UTC,
        ),
        cron(
            sync_analyst_estimates_job,
            # Weekly refresh on Saturday morning (02:00 UTC / 07:30 IST).
            # Analyst targets move slowly, so a weekly batch safely keeps 
            # them fresh without overloading free, unofficial data providers.
            weekday=5,
            hour=2,
            minute=0,
        ),
        cron(
            check_missed_market_close_sync,
            # Heartbeat catch-up: runs on worker startup (e.g. laptop wake)
            # and every 15 minutes past the hour (at :15, :30, :45) to catch
            # any missed market-close syncs without colliding with daily_market_close_sync at :00.
            minute={15, 30, 45},
            run_at_startup=True,
            timeout=3600,
        ),
        cron(
            sync_recent_earnings_job,
            # Autonomous earnings sync: checks BSE Financial Results feed every 2 hours
            # on weekdays between 09:30 IST and 21:30 IST (04:00 to 16:00 UTC).
            # When an active stock announces results, it verifies whether Screener.in has
            # published the new quarter before updating DB and recomputing scores.
            weekday={0, 1, 2, 3, 4},
            hour={4, 6, 8, 10, 12, 14, 16},
            minute=20,
            timeout=1800,
        ),
    ]
    redis_settings = RedisSettings.from_dsn(_settings.REDIS_URL)
    # Evaluate the cron schedule in UTC explicitly, rather than relying on
    # arq's default of "whatever the host/container's local system
    # timezone happens to be" - the hour/minute above are UTC values and
    # must be interpreted as UTC regardless of how the worker container's
    # OS timezone is configured (it happens to already be UTC, but this
    # removes that implicit dependency).
    timezone = UTC
    on_startup = startup
    on_shutdown = shutdown
