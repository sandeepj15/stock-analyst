"""Unit tests for packages/regime/classifier.py (SPEC.md sections 15, 64, 86).

Feeds synthetic feature combinations through `classify_regime` and
asserts the exact expected regime for each branch of the rule tree.
"""
from __future__ import annotations

from packages.regime.classifier import RULE_VERSION, RegimeFeatures, classify_regime
from packages.regime.models import MarketRegimeLabel


def _features(
    nifty_close: float = 20000.0,
    nifty_sma_50: float | None = 19500.0,
    nifty_sma_200: float | None = 19000.0,
    breadth_above_50dma_pct: float | None = 70.0,
    breadth_above_200dma_pct: float | None = 65.0,
    rolling_volatility_pct: float | None = 15.0,
) -> RegimeFeatures:
    return RegimeFeatures(
        nifty_close=nifty_close,
        nifty_sma_50=nifty_sma_50,
        nifty_sma_200=nifty_sma_200,
        breadth_above_50dma_pct=breadth_above_50dma_pct,
        breadth_above_200dma_pct=breadth_above_200dma_pct,
        rolling_volatility_pct=rolling_volatility_pct,
    )


def test_bullish_trend_matches_spec_worked_example():
    # index > 200DMA AND 50DMA > 200DMA AND breadth > 60% => Bullish Trend.
    features = _features(nifty_close=21000.0, nifty_sma_50=20000.0, nifty_sma_200=19000.0, breadth_above_50dma_pct=75.0, rolling_volatility_pct=14.0)
    result = classify_regime(features)
    assert result.label == MarketRegimeLabel.bullish_trend
    assert result.rule_version == RULE_VERSION
    assert result.nifty_vs_200dma_pct == (21000.0 / 19000.0 - 1.0) * 100.0


def test_bearish_trend_mirrors_bullish_rule():
    features = _features(nifty_close=17000.0, nifty_sma_50=18000.0, nifty_sma_200=19000.0, breadth_above_50dma_pct=25.0, rolling_volatility_pct=14.0)
    result = classify_regime(features)
    assert result.label == MarketRegimeLabel.bearish_trend


def test_high_volatility_dominates_regardless_of_trend():
    # Even with otherwise-bullish features, volatility above threshold wins.
    features = _features(nifty_close=21000.0, nifty_sma_50=20000.0, nifty_sma_200=19000.0, breadth_above_50dma_pct=75.0, rolling_volatility_pct=30.0)
    result = classify_regime(features)
    assert result.label == MarketRegimeLabel.high_volatility


def test_low_volatility_with_mixed_breadth():
    features = _features(nifty_close=19100.0, nifty_sma_50=19050.0, nifty_sma_200=19000.0, breadth_above_50dma_pct=50.0, rolling_volatility_pct=8.0)
    result = classify_regime(features)
    assert result.label == MarketRegimeLabel.low_volatility


def test_sideways_when_index_at_200dma():
    # vs_200dma_pct within +/-3% band, breadth mixed, moderate vol, not golden cross
    # (so rules 3/4 don't match), not low-vol breadth-mixed with vol<12 either.
    features = _features(nifty_close=19300.0, nifty_sma_50=19250.0, nifty_sma_200=19200.0, breadth_above_50dma_pct=50.0, rolling_volatility_pct=18.0)
    result = classify_regime(features)
    assert result.label == MarketRegimeLabel.sideways
    assert abs(result.nifty_vs_200dma_pct) <= 3.0


def test_transition_on_conflicting_signals():
    # Index above 200dma and breadth bullish-leaning, but no golden cross
    # yet and vol too high for low-vol/sideways to apply -> conflicting.
    features = _features(nifty_close=19800.0, nifty_sma_50=19100.0, nifty_sma_200=19000.0, breadth_above_50dma_pct=55.0, rolling_volatility_pct=18.0)
    result = classify_regime(features)
    assert result.label == MarketRegimeLabel.transition
    assert result.reason == "conflicting_signals"


def test_transition_on_insufficient_data():
    features = _features(nifty_sma_200=None)
    result = classify_regime(features)
    assert result.label == MarketRegimeLabel.transition
    assert result.reason == "insufficient_data"

    features2 = _features(breadth_above_50dma_pct=None)
    result2 = classify_regime(features2)
    assert result2.label == MarketRegimeLabel.transition
    assert result2.reason == "insufficient_data"

    features3 = _features(rolling_volatility_pct=None)
    result3 = classify_regime(features3)
    assert result3.label == MarketRegimeLabel.transition
    assert result3.reason == "insufficient_data"


def test_golden_cross_property():
    features = _features(nifty_sma_50=20000.0, nifty_sma_200=19000.0)
    assert features.golden_cross is True
    features2 = _features(nifty_sma_50=18000.0, nifty_sma_200=19000.0)
    assert features2.golden_cross is False
    features3 = _features(nifty_sma_50=None)
    assert features3.golden_cross is None
