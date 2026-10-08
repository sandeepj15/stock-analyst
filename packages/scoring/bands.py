"""Score bands (SPEC.md section 19).

Descriptive labels only - NEVER auto-translated into Buy/Sell/Hold
anywhere in this codebase (SPEC.md sections 19, 61, 81 rule 21).
"""
from __future__ import annotations

# Each entry is the *exclusive upper bound* of a band - SPEC.md section 19's
# "0-29 / 30-44 / 45-54 / 55-69 / 70-84" are inclusive integer ranges, which
# is equivalent to "< 30 / < 45 / < 55 / < 70 / < 85" over the continuous
# (unrounded, per section 18 "never round internally") score domain. The
# final band, "85-100", is whatever is left once every threshold is passed.
SCORE_BAND_THRESHOLDS: tuple[tuple[float, str], ...] = (
    (30.0, "Very Weak"),
    (45.0, "Weak"),
    (55.0, "Neutral"),
    (70.0, "Moderate"),
    (85.0, "Strong"),
)
VERY_STRONG_LABEL = "Very Strong"


def score_band(score: float) -> str:
    """Map a 0-100 score to its descriptive band label.

    e.g. 29.999 is "Very Weak", 30.0 is "Weak", 84.999 is "Strong", 85.0
    is "Very Strong". Values outside [0, 100] clamp to the nearest band
    rather than raising, since a renormalized weighted average cannot
    exceed [0, 100] by construction but defensive clamping costs nothing.
    """
    clamped = max(0.0, min(100.0, score))
    for threshold, label in SCORE_BAND_THRESHOLDS:
        if clamped < threshold:
            return label
    return VERY_STRONG_LABEL
