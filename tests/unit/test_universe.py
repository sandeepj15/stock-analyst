"""Tests for packages/market_data/universe.py (SPEC.md sections 8, 9).

All HTTP calls are mocked via `unittest.mock.patch` on
`packages.market_data.universe.requests.get` - this suite must never hit
the real network (see tests/conftest.py's docstring).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from packages.common.rate_limit import RetryPolicy
from packages.market_data.universe import (
    NIFTY_500_URL,
    NIFTY_MICROCAP_250_URL,
    NIFTY_TOTAL_MARKET_URL,
    fetch_nse_universe,
)

_TOTAL_MARKET_CSV = (
    "Company Name,Industry,Symbol,Series,ISIN Code\r\n"
    "Reliance Industries Ltd.,Oil Gas & Consumable Fuels,RELIANCE,EQ,INE002A01018\r\n"
    "Tata Consultancy Services Ltd.,Information Technology,TCS,EQ,INE467B01029\r\n"
)

_NIFTY500_CSV = (
    "Company Name,Industry,Symbol,Series,ISIN Code\r\n"
    "Reliance Industries Ltd.,Oil Gas & Consumable Fuels,RELIANCE,EQ,INE002A01018\r\n"
)

_MICROCAP_CSV = (
    "Company Name,Industry,Symbol,Series,ISIN Code\r\n"
    "Some Microcap Ltd.,Capital Goods,MICROCAP,EQ,INE999Z01000\r\n"
    # overlapping symbol with the nifty500 list, to prove dedup
    "Reliance Industries Ltd.,Oil Gas & Consumable Fuels,RELIANCE,EQ,INE002A01018\r\n"
)


def _fake_response(text: str, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(f"status {status_code}")
    else:
        resp.raise_for_status.side_effect = None
    return resp


def _no_retry_policy() -> RetryPolicy:
    return RetryPolicy(max_attempts=1, base_delay_seconds=0.0, max_delay_seconds=0.0, jitter_seconds=0.0)


def test_fetch_nse_universe_parses_primary_source() -> None:
    with patch("packages.market_data.universe.requests.get") as mock_get:
        mock_get.return_value = _fake_response(_TOTAL_MARKET_CSV)

        result = fetch_nse_universe(retry_policy=_no_retry_policy())

    mock_get.assert_called_once()
    assert mock_get.call_args.args[0] == NIFTY_TOTAL_MARKET_URL
    assert [i.symbol for i in result] == ["RELIANCE", "TCS"]
    assert result[0].company_name == "Reliance Industries Ltd."
    assert result[0].industry == "Oil Gas & Consumable Fuels"
    assert result[0].isin == "INE002A01018"


def test_fetch_nse_universe_falls_back_to_nifty500_plus_microcap_on_primary_failure() -> None:
    def _side_effect(url: str, **kwargs: object) -> MagicMock:
        if url == NIFTY_TOTAL_MARKET_URL:
            return _fake_response("", status_code=404)
        if url == NIFTY_500_URL:
            return _fake_response(_NIFTY500_CSV)
        if url == NIFTY_MICROCAP_250_URL:
            return _fake_response(_MICROCAP_CSV)
        raise AssertionError(f"unexpected URL {url}")

    with patch("packages.market_data.universe.requests.get", side_effect=_side_effect) as mock_get:
        result = fetch_nse_universe(retry_policy=_no_retry_policy())

    assert mock_get.call_count >= 2
    symbols = sorted(i.symbol for i in result)
    # RELIANCE appears in both source files but must be deduplicated.
    assert symbols == ["MICROCAP", "RELIANCE"]


def test_fetch_nse_universe_raises_when_every_source_fails() -> None:
    with patch("packages.market_data.universe.requests.get") as mock_get:
        mock_get.return_value = _fake_response("", status_code=500)

        with pytest.raises(requests.RequestException):
            fetch_nse_universe(retry_policy=_no_retry_policy())


def test_fetch_nse_universe_skips_malformed_rows_without_fabricating() -> None:
    csv_with_blank_row = (
        "Company Name,Industry,Symbol,Series,ISIN Code\r\n"
        "Reliance Industries Ltd.,Oil Gas & Consumable Fuels,RELIANCE,EQ,INE002A01018\r\n"
        ",,,,\r\n"  # malformed/blank row - must be skipped, never fabricated
    )
    with patch("packages.market_data.universe.requests.get") as mock_get:
        mock_get.return_value = _fake_response(csv_with_blank_row)

        result = fetch_nse_universe(retry_policy=_no_retry_policy())

    assert [i.symbol for i in result] == ["RELIANCE"]
