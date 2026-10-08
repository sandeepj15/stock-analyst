"""Market data abstraction layer (SPEC.md section 8).

No code outside this package should import `yfinance` (or any other
provider SDK) directly. All provider-specific logic must live behind the
`MarketDataProvider` protocol defined in `packages/market_data/base.py`.
"""
