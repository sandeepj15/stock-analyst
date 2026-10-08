"""SignalForge market regime engine (SPEC.md section 15, Phase 3).

- `classifier.py`: pure, deterministic rule-tree classification -
  `classify_regime(features) -> (MarketRegimeLabel, diagnostics)`.
- `models.py`: the `market_regimes` ORM table (one row per trading day
  per `rule_version`).
- `service.py`: orchestration - ensures the Nifty 50 benchmark instrument
  exists, refreshes its OHLCV, computes breadth across the seeded
  universe, classifies, and idempotently upserts the result.

See `docs/architecture/market_regime.md` for the full rule table.
"""
from __future__ import annotations

from packages.regime.classifier import RULE_VERSION, RegimeFeatures, classify_regime
from packages.regime.models import MarketRegime, MarketRegimeLabel

__all__ = ["RULE_VERSION", "RegimeFeatures", "classify_regime", "MarketRegime", "MarketRegimeLabel"]
