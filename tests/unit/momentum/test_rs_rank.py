"""RS Rank: raw-score formula + universe percentile ranking.

Hand-verified against a small synthetic universe (SPEC.md section 81
rule 4) - no DB, no market data.
"""
from __future__ import annotations

import pandas as pd
import pytest

from packages.momentum.rs_rank import (
    RS_RANK_LOOKBACK_TRADING_DAYS,
    compute_raw_score,
    percentile_rank_universe,
)


def _flat_then_quarterly_returns(q4: float, q3: float, q2: float, q1: float) -> pd.Series:
    """Build a 253-point close series with exact per-quarter returns Q4..Q1 (oldest to newest).

    Starts at 100.0; each quarter (63 bars) compounds by `1 + return`.
    `compute_raw_score` reads this back out as the same four returns.
    """
    start = 100.0
    boundaries = [start]
    for q_return in (q4, q3, q2, q1):
        boundaries.append(boundaries[-1] * (1.0 + q_return))

    # 4 segments of 63 bars each ending exactly at each boundary price,
    # linearly interpolated within a segment (the *endpoints* are what
    # compute_raw_score reads, so interior shape doesn't matter).
    segments = []
    for i in range(4):
        seg_start, seg_end = boundaries[i], boundaries[i + 1]
        n = 64  # 64 points per segment; the first point of segments 1-3 is dropped below (shared boundary)
        segment = pd.Series([seg_start + (seg_end - seg_start) * j / (n - 1) for j in range(n)])
        if i > 0:
            segment = segment.iloc[1:]  # avoid double-counting the shared boundary point
        segments.append(segment)
    full = pd.concat(segments, ignore_index=True)
    assert len(full) == RS_RANK_LOOKBACK_TRADING_DAYS + 1
    return full


def test_raw_score_formula_hand_verified():
    # Q1 (most recent) = +10%, Q2 = +5%, Q3 = -2%, Q4 (oldest) = +1%
    # raw_score = 2*0.10 + 0.05 + (-0.02) + 0.01 = 0.24
    series = _flat_then_quarterly_returns(q4=0.01, q3=-0.02, q2=0.05, q1=0.10)
    result = compute_raw_score(series)
    assert result.reason is None
    assert result.raw_score == pytest.approx(0.24, abs=1e-6)


def test_raw_score_insufficient_history_is_none_not_fabricated():
    short_series = pd.Series([100.0] * (RS_RANK_LOOKBACK_TRADING_DAYS))  # one point short of required
    result = compute_raw_score(short_series)
    assert result.raw_score is None
    assert result.reason == "insufficient_price_history"


def test_raw_score_double_weights_most_recent_quarter():
    # Flip which quarter carries the big move - the DOUBLE-weighted Q1
    # must dominate the raw_score more than any single-weighted quarter.
    strong_recent = _flat_then_quarterly_returns(q4=0.0, q3=0.0, q2=0.0, q1=0.20)
    strong_oldest = _flat_then_quarterly_returns(q4=0.20, q3=0.0, q2=0.0, q1=0.0)
    recent_score = compute_raw_score(strong_recent).raw_score
    oldest_score = compute_raw_score(strong_oldest).raw_score
    assert recent_score == pytest.approx(0.40, abs=1e-6)  # 2 * 0.20
    assert oldest_score == pytest.approx(0.20, abs=1e-6)  # 1 * 0.20
    assert recent_score > oldest_score


def test_percentile_rank_hand_verified_5_instrument_universe():
    # Strictly increasing raw_scores -> ranks are evenly spaced 0..100.
    raw_scores = {"A": -0.10, "B": -0.05, "C": 0.0, "D": 0.05, "E": 0.10}
    ranks = percentile_rank_universe(raw_scores)
    assert ranks == {"A": 0.0, "B": 25.0, "C": 50.0, "D": 75.0, "E": 100.0}


def test_percentile_rank_ties_get_averaged_rank():
    # B and C tie for the middle two of 4 slots (0-indexed ranks 1 and 2);
    # average rank = 1.5 -> percentile = 1.5/3*100 = 50.0 for both.
    raw_scores = {"A": 0.0, "B": 0.10, "C": 0.10, "D": 0.20}
    ranks = percentile_rank_universe(raw_scores)
    assert ranks["A"] == 0.0
    assert ranks["B"] == pytest.approx(50.0)
    assert ranks["C"] == pytest.approx(50.0)
    assert ranks["D"] == 100.0


def test_percentile_rank_single_instrument_universe_is_neutral():
    assert percentile_rank_universe({"ONLY": 0.5}) == {"ONLY": 50.0}


def test_percentile_rank_empty_universe():
    assert percentile_rank_universe({}) == {}


def test_percentile_rank_is_not_quadratic_in_implementation():
    """O(n log n) via one sort, not O(n^2) pairwise comparisons - proof by
    construction: a population large enough that an O(n^2) Python loop
    would be noticeably slow still ranks correctly and quickly here."""
    import time

    raw_scores = {f"SYM{i}": float(i) for i in range(5000)}
    start = time.monotonic()
    ranks = percentile_rank_universe(raw_scores)
    elapsed = time.monotonic() - start

    assert ranks["SYM0"] == 0.0
    assert ranks["SYM4999"] == 100.0
    assert ranks["SYM2500"] == pytest.approx(2500 / 4999 * 100.0)
    assert elapsed < 2.0  # generous ceiling; an accidental O(n^2) implementation at n=5000 is far slower
