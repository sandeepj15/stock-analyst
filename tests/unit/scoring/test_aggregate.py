"""Tests for packages/scoring/aggregate.py (SPEC.md sections 18, 20, 22, 86).

These are the required test cases from SPEC.md section 86 ("Prompt 5 -
Research Score"), expressed directly against the aggregation engine with
synthetic `ComponentResult`s - no DB/OHLCV fixtures needed, since
aggregation is deliberately decoupled from how each component's score
was derived (see aggregate.py's module docstring).
"""
from __future__ import annotations

import pytest

from packages.scoring.aggregate import ComponentResult, aggregate_components
from packages.scoring.constants import COMPONENT_WEIGHTS

ALL_NAMES = list(COMPONENT_WEIGHTS.keys())


def _components(scores: dict[str, float | None], freshness: dict[str, float] | None = None) -> list[ComponentResult]:
    freshness = freshness or {}
    out = []
    for name in ALL_NAMES:
        score = scores.get(name, "MISSING")
        available = score != "MISSING" and score is not None
        out.append(
            ComponentResult(
                name=name,
                weight=COMPONENT_WEIGHTS[name],
                score=score if available else None,
                available=available,
                reason=None if available else "test_missing",
                freshness=freshness.get(name, 100.0),
                evidence_ids=(f"ev-{name}",) if available else (),
            )
        )
    return out


def test_all_seven_available_components_at_100_news_missing():
    scores = {name: 100.0 for name in ALL_NAMES if name != "event_news_context"}
    result = aggregate_components(_components(scores))

    assert result.score == 100.0
    # News (5% weight) is the only missing component -> available_weight = 0.95.
    # weight_coverage = 95%, freshness_avg = 100 (all available components fresh).
    # confidence = 0.7*95 + 0.3*100 = 96.5, strictly less than 100.
    assert result.confidence == pytest.approx(96.5)
    assert result.confidence < 100.0

    news = next(c for c in result.components if c.name == "event_news_context")
    assert news.available is False
    assert news.weight_used == 0.0
    assert news.contribution == 0.0


def test_all_components_at_0():
    scores = {name: 0.0 for name in ALL_NAMES}
    result = aggregate_components(_components(scores))
    assert result.score == 0.0
    assert result.confidence == pytest.approx(100.0)  # fully available, fully fresh


def test_some_components_missing_beyond_news_confidence_drops_further_and_renormalizes():
    # News AND fundamentals both missing (0.05 + 0.20 = 0.25 of total weight gone).
    scores = {name: 80.0 for name in ALL_NAMES if name not in ("event_news_context", "fundamentals")}
    result_missing_two = aggregate_components(_components(scores))

    scores_missing_one = {name: 80.0 for name in ALL_NAMES if name != "event_news_context"}
    result_missing_one = aggregate_components(_components(scores_missing_one))

    assert result_missing_two.score == pytest.approx(80.0)  # all remaining equal -> weighted avg is still 80
    assert result_missing_two.confidence < result_missing_one.confidence

    fundamentals = next(c for c in result_missing_two.components if c.name == "fundamentals")
    assert fundamentals.available is False
    assert fundamentals.weight_used == 0.0


def test_stale_fundamentals_reduces_confidence_without_changing_score():
    scores = dict.fromkeys(ALL_NAMES, 80.0)
    scores.pop("event_news_context")

    fresh = aggregate_components(_components(scores, freshness={"fundamentals": 100.0}))
    stale = aggregate_components(_components(scores, freshness={"fundamentals": 10.0}))

    assert fresh.score == stale.score  # the component's own score is unaffected by staleness
    assert stale.confidence < fresh.confidence


def test_renormalization_hand_computed_weighted_average():
    # Only technical_structure (0.20) and momentum (0.15) available, rest missing.
    scores = {"technical_structure": 90.0, "momentum": 60.0}
    result = aggregate_components(_components(scores))

    available_weight = COMPONENT_WEIGHTS["technical_structure"] + COMPONENT_WEIGHTS["momentum"]
    expected_score = (90.0 * COMPONENT_WEIGHTS["technical_structure"] + 60.0 * COMPONENT_WEIGHTS["momentum"]) / available_weight
    assert result.score == pytest.approx(expected_score)

    technical = next(c for c in result.components if c.name == "technical_structure")
    assert technical.weight_used == pytest.approx(COMPONENT_WEIGHTS["technical_structure"] / available_weight)
    # Sum of all contributions reconstructs the headline score.
    assert sum(c.contribution for c in result.components) == pytest.approx(result.score)


def test_every_component_missing_score_is_none_confidence_is_zero():
    result = aggregate_components(_components({}))
    assert result.score is None
    assert result.confidence == 0.0


def test_one_input_change_momentum_up_increases_headline_score():
    from packages.scoring.signals import score_momentum_points

    low_score, _ = score_momentum_points(rsi_14=40.0, macd_histogram=0.0, roc_12=0.0, stochastic_k=50.0)
    high_score, _ = score_momentum_points(rsi_14=80.0, macd_histogram=0.0, roc_12=0.0, stochastic_k=50.0)
    assert high_score > low_score

    base_scores = {name: 60.0 for name in ALL_NAMES if name != "event_news_context"}

    before = dict(base_scores)
    before["momentum"] = low_score
    after = dict(base_scores)
    after["momentum"] = high_score

    result_before = aggregate_components(_components(before))
    result_after = aggregate_components(_components(after))

    assert result_after.score > result_before.score

