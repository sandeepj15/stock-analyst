"""Volume indicators (SPEC.md section 14): volume SMA, relative volume, OBV."""
from __future__ import annotations

import pandas as pd


def volume_sma(volume: pd.Series, window: int) -> pd.Series:
    """Simple moving average of volume over a trailing `window`."""
    return volume.rolling(window=window, min_periods=window).mean()


def relative_volume(volume: pd.Series, window: int) -> pd.Series:
    """Today's volume divided by its own trailing `window`-period average.

    The average at index i excludes nothing extra and includes today's
    bar (consistent with how most charting platforms define "relative
    volume" intraday-equivalent for daily bars). > 1.0 means above-average
    volume.
    """
    avg = volume_sma(volume, window)
    return volume / avg


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume: cumulative volume, signed by the direction of
    each day's close-to-close change (+volume on up days, -volume on down
    days, unchanged on flat days). Starts at 0 on the first observation.
    """
    # diff() leaves the first element NaN; the lambda maps NaN to 0.0 (via
    # the final else branch) which is exactly the "no prior bar" base case.
    direction = close.diff().apply(lambda x: 1.0 if x > 0 else (-1.0 if x < 0 else 0.0))
    signed_volume = direction * volume
    return signed_volume.cumsum()
