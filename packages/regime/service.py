"""Market regime orchestration (SPEC.md section 15).

`compute_and_store_regime` is the single entry point used by the Arq
worker job (`apps/worker/jobs.py::sync_market_regime`) and ad-hoc scripts.
It:

1. Ensures the Nifty 50 benchmark `Instrument` exists (`instrument_type="INDEX"`,
   symbol `NIFTY50`, exchange `NSE` - SPEC.md section 15's special
   accommodation, see `packages/market_data/providers/yfinance_provider.py`).
2. Refreshes its OHLCV through the normal `ingest_daily_bars` pipeline
   (same table, same quality checks, same idempotency - no parallel path).
3. Computes breadth (`% of the seeded 117-instrument universe above its
   own 50/200 DMA`) - always labeled `breadth_universe: "seeded_117"` by
   callers, never presented as real market breadth.
4. Classifies via `packages.regime.classifier.classify_regime` and
   idempotently upserts one `market_regimes` row per `(date, rule_version)`.

No look-ahead (SPEC.md section 2.6): every feature here is computed from
OHLCV rows already in the database as of "now" - there is no use of any
bar dated after the latest ingested trading day.
"""
from __future__ import annotations

import logging
import math
import uuid
from datetime import date, timedelta

import pandas as pd
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from packages.analytics import rolling_volatility, sma
from packages.common.config import Settings, get_settings
from packages.common.models import Instrument
from packages.market_data.base import MarketDataProvider
from packages.market_data.factory import get_provider
from packages.market_data.history import load_ohlcv_dataframe
from packages.market_data.ingestion import ingest_daily_bars
from packages.regime.classifier import RULE_VERSION, RegimeFeatures, classify_regime
from packages.regime.models import MarketRegime

logger = logging.getLogger(__name__)

BENCHMARK_SYMBOL = "NIFTY50"
BENCHMARK_EXCHANGE = "NSE"
BENCHMARK_COMPANY_NAME = "Nifty 50 Index"
DEFAULT_BACKFILL_DAYS = 730

VOLATILITY_WINDOW = 20
SMA_50_WINDOW = 50
SMA_200_WINDOW = 200

BREADTH_UNIVERSE_LABEL = "seeded_117"


def _none_if_nan(value: float) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return float(value)


class RegimeResult(BaseModel):
    date: str
    regime: str
    nifty_close: float
    nifty_vs_200dma_pct: float | None
    breadth_above_50dma_pct: float | None
    breadth_above_200dma_pct: float | None
    rolling_volatility_pct: float | None
    rule_version: str
    reason: str
    breadth_universe: str
    universe_size: int


async def ensure_benchmark_instrument(session: AsyncSession, provider: MarketDataProvider) -> Instrument:
    """Get-or-create the Nifty 50 benchmark `Instrument` row."""
    existing = (
        await session.execute(
            select(Instrument).where(Instrument.symbol == BENCHMARK_SYMBOL, Instrument.exchange == BENCHMARK_EXCHANGE)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    company_name = BENCHMARK_COMPANY_NAME
    try:
        info = provider.get_instrument(BENCHMARK_SYMBOL, BENCHMARK_EXCHANGE)
        company_name = info.company_name or BENCHMARK_COMPANY_NAME
    except Exception as exc:  # pragma: no cover - network/provider failure path
        logger.warning("regime: could not fetch benchmark instrument info, using default name", extra={"error": str(exc)})

    instrument = Instrument(
        symbol=BENCHMARK_SYMBOL,
        exchange=BENCHMARK_EXCHANGE,
        company_name=company_name,
        instrument_type="INDEX",
        currency="INR",
    )
    session.add(instrument)
    await session.commit()
    return instrument


async def compute_breadth(session: AsyncSession) -> tuple[float | None, float | None, int]:
    """% of active seeded EQUITY instruments with close above their own 50/200 DMA.

    Each breadth ratio's denominator only counts instruments that have
    *enough history* for that specific window (e.g. an instrument with 80
    days of history contributes to the 50 DMA breadth denominator but not
    the 200 DMA one) - this avoids silently treating "not enough data" as
    "below the moving average" (SPEC.md section 81 rule 8).
    """
    stmt = select(Instrument).where(Instrument.active.is_(True), Instrument.instrument_type == "EQUITY")
    instruments = (await session.execute(stmt)).scalars().all()

    above_50 = above_200 = 0
    counted_50 = counted_200 = 0

    for instrument in instruments:
        df = await load_ohlcv_dataframe(session, instrument.id)
        if df.empty:
            continue
        close = df["adjusted_close"]
        latest_close = float(close.iloc[-1])

        if len(close) >= SMA_50_WINDOW:
            sma_50 = sma(close, SMA_50_WINDOW).iloc[-1]
            if pd.notna(sma_50):
                counted_50 += 1
                if latest_close > sma_50:
                    above_50 += 1

        if len(close) >= SMA_200_WINDOW:
            sma_200 = sma(close, SMA_200_WINDOW).iloc[-1]
            if pd.notna(sma_200):
                counted_200 += 1
                if latest_close > sma_200:
                    above_200 += 1

    breadth_50 = (above_50 / counted_50 * 100.0) if counted_50 else None
    breadth_200 = (above_200 / counted_200 * 100.0) if counted_200 else None
    return breadth_50, breadth_200, len(instruments)


async def compute_and_store_regime(
    session: AsyncSession,
    settings: Settings | None = None,
    provider: MarketDataProvider | None = None,
    refresh_benchmark: bool = True,
) -> RegimeResult:
    settings = settings or get_settings()
    provider = provider or get_provider(settings)

    benchmark = await ensure_benchmark_instrument(session, provider)

    if refresh_benchmark:
        end = date.today()
        start = end - timedelta(days=DEFAULT_BACKFILL_DAYS)
        try:
            await ingest_daily_bars(provider, session, benchmark, start, end)
        except Exception as exc:
            # Never fabricate a regime from thin air if the live refresh
            # fails - fall back to whatever Nifty history is already
            # stored (and let that surface as missing/stale downstream).
            logger.error("regime: benchmark OHLCV refresh failed, using existing stored bars", extra={"error": str(exc)})

    nifty_df = await load_ohlcv_dataframe(session, benchmark.id)
    if nifty_df.empty:
        raise ValueError(
            "No Nifty 50 OHLCV data available - cannot compute market regime. "
            "Run the benchmark backfill (sync_market_regime) first."
        )

    close = nifty_df["adjusted_close"]
    sma_50_series = sma(close, SMA_50_WINDOW)
    sma_200_series = sma(close, SMA_200_WINDOW)
    vol_series = rolling_volatility(close, VOLATILITY_WINDOW)

    nifty_close = float(close.iloc[-1])
    sma_50 = _none_if_nan(sma_50_series.iloc[-1])
    sma_200 = _none_if_nan(sma_200_series.iloc[-1])
    vol_fraction = _none_if_nan(vol_series.iloc[-1])
    vol_pct = vol_fraction * 100.0 if vol_fraction is not None else None

    breadth_50, breadth_200, universe_size = await compute_breadth(session)

    features = RegimeFeatures(
        nifty_close=nifty_close,
        nifty_sma_50=sma_50,
        nifty_sma_200=sma_200,
        breadth_above_50dma_pct=breadth_50,
        breadth_above_200dma_pct=breadth_200,
        rolling_volatility_pct=vol_pct,
    )
    classification = classify_regime(features)
    as_of_date = nifty_df["trading_date"].iloc[-1]

    insert_stmt = pg_insert(MarketRegime).values(
        id=uuid.uuid4(),
        date=as_of_date,
        regime=classification.label,
        nifty_close=nifty_close,
        nifty_vs_200dma_pct=classification.nifty_vs_200dma_pct,
        breadth_above_50dma_pct=classification.breadth_above_50dma_pct,
        breadth_above_200dma_pct=classification.breadth_above_200dma_pct,
        rolling_volatility_pct=classification.rolling_volatility_pct,
        rule_version=classification.rule_version,
    )
    update_cols = (
        "regime",
        "nifty_close",
        "nifty_vs_200dma_pct",
        "breadth_above_50dma_pct",
        "breadth_above_200dma_pct",
        "rolling_volatility_pct",
    )
    update_set = {col: getattr(insert_stmt.excluded, col) for col in update_cols}
    upsert_stmt = insert_stmt.on_conflict_do_update(
        index_elements=[MarketRegime.date, MarketRegime.rule_version], set_=update_set
    )
    await session.execute(upsert_stmt)
    await session.commit()

    logger.info(
        "sync_market_regime completed",
        extra={"date": as_of_date.isoformat(), "regime": classification.label.value, "universe_size": universe_size},
    )

    return RegimeResult(
        date=as_of_date.isoformat(),
        regime=classification.label.value,
        nifty_close=nifty_close,
        nifty_vs_200dma_pct=classification.nifty_vs_200dma_pct,
        breadth_above_50dma_pct=classification.breadth_above_50dma_pct,
        breadth_above_200dma_pct=classification.breadth_above_200dma_pct,
        rolling_volatility_pct=classification.rolling_volatility_pct,
        rule_version=classification.rule_version,
        reason=classification.reason,
        breadth_universe=BREADTH_UNIVERSE_LABEL,
        universe_size=universe_size,
    )


async def get_latest_regime(session: AsyncSession, rule_version: str | None = None) -> MarketRegime | None:
    """Latest stored `market_regimes` row (optionally filtered to one `rule_version`)."""
    stmt = select(MarketRegime).where(MarketRegime.rule_version == (rule_version or RULE_VERSION))
    stmt = stmt.order_by(MarketRegime.date.desc()).limit(1)
    return (await session.execute(stmt)).scalar_one_or_none()
