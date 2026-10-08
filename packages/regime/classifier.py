"""Deterministic market regime classifier (SPEC.md section 15).

Pure function, no I/O, no ML (SPEC.md section 81 rule 24: "prefer simple
deterministic implementations before ML"). See
`docs/architecture/market_regime.md` for the rule table in prose; this
module is the executable version of that table and the two must be kept
in sync.

`RULE_VERSION` is stored with every classification (SPEC.md section 47) -
bump it (e.g. "regime_v2") and keep this one intact if the rule tree ever
changes, so historical rows never get silently reinterpreted.
"""
from __future__ import annotations

from dataclasses import dataclass

from packages.regime.models import MarketRegimeLabel

RULE_VERSION = "regime_v1"

# --- Documented thresholds (SPEC.md section 15 example extended) ---
# Annualized rolling volatility bands, in percent (matches
# `packages.analytics.volatility.rolling_volatility`'s * 100 output).
HIGH_VOL_THRESHOLD_PCT = 25.0
LOW_VOL_THRESHOLD_PCT = 12.0
# Breadth (% of the seeded universe above its own 50 DMA) bands, in percent.
BREADTH_BULLISH_PCT = 60.0
BREADTH_BEARISH_PCT = 40.0
# How close the index must be to its 200 DMA (in percent) to be considered
# "at" it rather than meaningfully above/below it, for the SIDEWAYS branch.
TREND_FLAT_BAND_PCT = 3.0


@dataclass(frozen=True)
class RegimeFeatures:
    """Inputs to `classify_regime`. Any `None` field means "insufficient data"."""

    nifty_close: float
    nifty_sma_50: float | None
    nifty_sma_200: float | None
    breadth_above_50dma_pct: float | None  # 0-100, % of seeded universe
    breadth_above_200dma_pct: float | None  # 0-100
    rolling_volatility_pct: float | None  # Nifty's own annualized rolling vol, in percent

    @property
    def nifty_vs_200dma_pct(self) -> float | None:
        if self.nifty_sma_200 is None or self.nifty_sma_200 == 0:
            return None
        return (self.nifty_close / self.nifty_sma_200 - 1.0) * 100.0

    @property
    def golden_cross(self) -> bool | None:
        if self.nifty_sma_50 is None or self.nifty_sma_200 is None:
            return None
        return self.nifty_sma_50 > self.nifty_sma_200


@dataclass(frozen=True)
class RegimeClassification:
    label: MarketRegimeLabel
    rule_version: str
    reason: str
    nifty_vs_200dma_pct: float | None
    breadth_above_50dma_pct: float | None
    breadth_above_200dma_pct: float | None
    rolling_volatility_pct: float | None


def classify_regime(features: RegimeFeatures) -> RegimeClassification:
    """Classify `features` into one of the six SPEC.md section 15 regimes.

    Evaluated as an ordered if/elif chain (first match wins) - see
    `docs/architecture/market_regime.md` for the full prose rule table.
    """
    vs_200 = features.nifty_vs_200dma_pct
    golden = features.golden_cross
    breadth_50 = features.breadth_above_50dma_pct
    breadth_200 = features.breadth_above_200dma_pct
    vol = features.rolling_volatility_pct

    def result(label: MarketRegimeLabel, reason: str) -> RegimeClassification:
        return RegimeClassification(
            label=label,
            rule_version=RULE_VERSION,
            reason=reason,
            nifty_vs_200dma_pct=vs_200,
            breadth_above_50dma_pct=breadth_50,
            breadth_above_200dma_pct=breadth_200,
            rolling_volatility_pct=vol,
        )

    # 1. Insufficient data to classify at all (e.g. < 200 trading days of
    #    history, or no breadth universe computed yet) - never guess.
    if vs_200 is None or golden is None or breadth_50 is None or vol is None:
        return result(MarketRegimeLabel.transition, "insufficient_data")

    # 2. High volatility dominates: regardless of trend direction, an
    #    elevated-volatility tape is flagged first because it is the most
    #    actionable risk signal (SPEC.md section 15 feature list includes
    #    "volatility index" / "ATR regime" alongside trend features).
    if vol > HIGH_VOL_THRESHOLD_PCT:
        return result(MarketRegimeLabel.high_volatility, f"rolling_volatility_pct={vol:.1f} > {HIGH_VOL_THRESHOLD_PCT}")

    # 3. Bullish trend (SPEC.md section 15 worked example, verbatim):
    #    index > 200DMA AND 50DMA > 200DMA AND breadth > 60%.
    if vs_200 > 0 and golden and breadth_50 > BREADTH_BULLISH_PCT:
        return result(MarketRegimeLabel.bullish_trend, "index>200dma AND golden_cross AND breadth>60%")

    # 4. Bearish trend: mirror image of rule 3.
    if vs_200 < 0 and not golden and breadth_50 < BREADTH_BEARISH_PCT:
        return result(MarketRegimeLabel.bearish_trend, "index<200dma AND death_cross AND breadth<40%")

    # 5. Low volatility: quiet tape with no decisive breadth majority
    #    either way - calm but directionless.
    if vol < LOW_VOL_THRESHOLD_PCT and BREADTH_BEARISH_PCT <= breadth_50 <= BREADTH_BULLISH_PCT:
        return result(MarketRegimeLabel.low_volatility, f"rolling_volatility_pct={vol:.1f} < {LOW_VOL_THRESHOLD_PCT} AND breadth mixed")

    # 6. Sideways: index is essentially sitting at its own 200 DMA.
    if abs(vs_200) <= TREND_FLAT_BAND_PCT:
        return result(MarketRegimeLabel.sideways, f"abs(nifty_vs_200dma_pct)={vs_200:.1f} <= {TREND_FLAT_BAND_PCT}")

    # 7. Everything else: signals conflict (e.g. index above its 200 DMA
    #    but 50/200 DMA not yet crossed, or breadth doesn't confirm trend) -
    #    a regime that is changing rather than settled.
    return result(MarketRegimeLabel.transition, "conflicting_signals")
