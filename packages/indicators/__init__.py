"""SignalForge indicator orchestration layer (SPEC.md section 14, Phase 2).

Turns a raw OHLCV `DataFrame` (one instrument) into either the latest
`IndicatorSnapshot` or the full time-aligned indicator series, built
entirely on top of the pure functions in `packages/analytics`.
"""
from __future__ import annotations

from packages.indicators.models import IndicatorSnapshot
from packages.indicators.snapshot import compute_indicator_series, compute_indicator_snapshot

__all__ = ["IndicatorSnapshot", "compute_indicator_series", "compute_indicator_snapshot"]
