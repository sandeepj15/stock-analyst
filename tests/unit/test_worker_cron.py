"""Tests for the daily after-market-close cron registration (apps/worker/settings.py).

These tests exist specifically to catch an off-by-one in arq's weekday
numbering convention - the task this was built for calls out that
getting this wrong "means the job silently runs on the wrong days or
skips weekdays entirely". Rather than trust a mental model of arq's
`cron()` weekday parameter, `test_cron_schedule_fires_mon_fri_never_weekends`
drives arq's own `next_cron` function (the same function the real
`Worker` uses internally to schedule the next fire) across a real
Mon-Fri work week to prove the registered schedule behaves as intended.

No network/DB access - this only inspects the `CronJob` dataclass arq
builds from `apps/worker/settings.py::WorkerSettings.cron_jobs` and
exercises the cron math arq ships, both fully offline.
"""
from __future__ import annotations

import datetime as dt

from arq.cron import next_cron

from apps.worker.jobs import daily_market_close_sync
from apps.worker.settings import WorkerSettings
from packages.common.config import get_settings


def _registered_daily_sync_cron_job():
    matches = [cj for cj in WorkerSettings.cron_jobs if cj.coroutine is daily_market_close_sync]
    assert len(matches) == 1, "daily_market_close_sync must be registered exactly once in cron_jobs"
    return matches[0]


def test_daily_market_close_sync_is_registered_as_a_cron_job():
    """`daily_market_close_sync` must appear in both `functions` (so it stays
    independently/manually triggerable, like every other job) and `cron_jobs`
    (so it also runs automatically) - never only one or the other."""
    assert daily_market_close_sync in WorkerSettings.functions
    _registered_daily_sync_cron_job()  # raises/asserts if missing from cron_jobs


def test_cron_schedule_hour_minute_weekday_match_settings():
    settings = get_settings()
    job = _registered_daily_sync_cron_job()

    # weekday={0,1,2,3,4}: Python's `datetime.weekday()` convention -
    # which arq's cron() delegates straight to (see
    # .venv/lib/python3.12/site-packages/arq/cron.py::_get_next_dt,
    # `next_v = dt_.weekday()`) - is Monday == 0 ... Sunday == 6. This
    # asserts against that *verified* convention, not an assumption.
    assert job.weekday == {0, 1, 2, 3, 4}
    assert job.hour == settings.DAILY_SYNC_HOUR_UTC
    assert job.minute == settings.DAILY_SYNC_MINUTE_UTC


def test_default_schedule_is_1300_utc_which_is_1830_ist():
    """IST is a fixed UTC+5:30 offset (no DST) - 18:30 IST == 13:00 UTC."""
    settings = get_settings()
    assert settings.DAILY_SYNC_HOUR_UTC == 13
    assert settings.DAILY_SYNC_MINUTE_UTC == 0

    ist_offset = dt.timedelta(hours=5, minutes=30)
    utc_fire_time = dt.timedelta(hours=settings.DAILY_SYNC_HOUR_UTC, minutes=settings.DAILY_SYNC_MINUTE_UTC)
    ist_fire_time = utc_fire_time + ist_offset
    assert ist_fire_time == dt.timedelta(hours=18, minutes=30)


def test_cron_schedule_fires_mon_fri_never_weekends():
    """Drive arq's real `next_cron` across a full work week + weekend.

    This is the test that would fail if arq's weekday convention were
    misread (e.g. treating 0 as Sunday instead of Monday): if that
    mistake were made, this schedule would either fire on Sat/Sun or
    skip weekdays entirely, and the assertions below would catch it.
    """
    settings = get_settings()
    job = _registered_daily_sync_cron_job()

    # Anchor to a real calendar week, discovered programmatically (never
    # a hardcoded "this literal date is a Friday" assumption).
    probe = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    friday = next(probe + dt.timedelta(days=i) for i in range(14) if (probe + dt.timedelta(days=i)).weekday() == 4)
    saturday = friday + dt.timedelta(days=1)
    sunday = friday + dt.timedelta(days=2)
    monday = friday + dt.timedelta(days=3)
    assert saturday.weekday() == 5
    assert sunday.weekday() == 6
    assert monday.weekday() == 0

    def _next_fire(previous_dt: dt.datetime) -> dt.datetime:
        return next_cron(
            previous_dt,
            weekday=job.weekday,
            hour=job.hour,
            minute=job.minute,
            second=job.second,
            microsecond=job.microsecond,
        )

    fridays_fire = friday.replace(
        hour=settings.DAILY_SYNC_HOUR_UTC, minute=settings.DAILY_SYNC_MINUTE_UTC, second=0, microsecond=0
    )

    # Just before Friday's scheduled time: next fire is still Friday.
    next_run = _next_fire(fridays_fire - dt.timedelta(minutes=1))
    assert next_run.date() == friday.date()
    assert next_run.weekday() == 4

    # Just after Friday's scheduled time: next fire must skip Saturday
    # and Sunday entirely and land on Monday - never the weekend.
    next_run = _next_fire(fridays_fire + dt.timedelta(seconds=1))
    assert next_run.date() == monday.date()
    assert next_run.weekday() == 0
    assert next_run.hour == settings.DAILY_SYNC_HOUR_UTC
    assert next_run.minute == settings.DAILY_SYNC_MINUTE_UTC

    # And from Monday's fire, the next one is Tuesday (a normal
    # mid-week day), not another multi-day jump.
    mondays_fire = monday.replace(
        hour=settings.DAILY_SYNC_HOUR_UTC, minute=settings.DAILY_SYNC_MINUTE_UTC, second=0, microsecond=0
    )
    next_run = _next_fire(mondays_fire + dt.timedelta(seconds=1))
    assert next_run.weekday() == 1
    assert next_run.date() == (monday + dt.timedelta(days=1)).date()


def test_worker_settings_timezone_is_utc():
    """The cron hour/minute settings are UTC values - the Worker must
    evaluate them as UTC regardless of the host/container's local system
    timezone configuration, not implicitly rely on it already being UTC."""
    assert WorkerSettings.timezone == dt.UTC
