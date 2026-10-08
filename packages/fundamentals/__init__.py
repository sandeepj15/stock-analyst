"""SignalForge fundamentals package (SPEC.md sections 12, 13, Phase 3).

Layout mirrors `packages/market_data/`:
- `base.py`: provider-agnostic types + the `FundamentalDataProvider` protocol.
- `providers/yfinance_fundamental_provider.py`: the only local-dev
  implementation (not licensed for commercial use - see DATA_SOURCES.md).
- `factory.py`: resolves the configured provider from settings.
- `models.py`: the `fundamental_snapshots` ORM table (raw values only).
- `derive.py`: pure functions for every derived/valuation metric.
- `ingestion.py`: `sync_fundamentals`, the idempotent upsert entry point.
"""
from __future__ import annotations

from packages.fundamentals.base import FundamentalDataProvider, FundamentalSnapshotData
from packages.fundamentals.models import FundamentalSnapshot

__all__ = ["FundamentalDataProvider", "FundamentalSnapshotData", "FundamentalSnapshot"]
