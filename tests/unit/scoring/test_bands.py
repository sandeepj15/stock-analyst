"""Score band boundary tests (SPEC.md section 19, 86)."""
from __future__ import annotations

import pytest

from packages.scoring.bands import score_band


@pytest.mark.parametrize(
    "score,expected",
    [
        (0.0, "Very Weak"),
        (29.0, "Very Weak"),
        (29.999, "Very Weak"),
        (30.0, "Weak"),
        (44.0, "Weak"),
        (44.999, "Weak"),
        (45.0, "Neutral"),
        (54.0, "Neutral"),
        (54.999, "Neutral"),
        (55.0, "Moderate"),
        (69.0, "Moderate"),
        (69.999, "Moderate"),
        (70.0, "Strong"),
        (84.0, "Strong"),
        (84.999, "Strong"),
        (85.0, "Very Strong"),
        (100.0, "Very Strong"),
    ],
)
def test_band_boundaries(score: float, expected: str) -> None:
    assert score_band(score) == expected
