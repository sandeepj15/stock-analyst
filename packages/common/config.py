"""Application configuration via pydantic-settings.

All environment variables listed in SPEC.md section 69 are modeled here,
plus a CORS allowlist used by apps/api. Nothing in this module should read
os.environ directly outside of pydantic-settings — add new config here
instead of scattering `os.getenv()` calls through the codebase.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Core infra ---
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://signalforge:signalforge@localhost:5432/signalforge",
        description="Async SQLAlchemy connection string (asyncpg driver).",
    )
    REDIS_URL: str = Field(default="redis://localhost:6379/0")

    # --- Market data provider (SPEC section 8) ---
    MARKET_DATA_PROVIDER: str = Field(default="yfinance_dev")
    MARKET_DATA_API_KEY: str | None = Field(default=None)

    # --- Fundamentals provider (future phase, see SPEC section 85) ---
    FUNDAMENTAL_PROVIDER: str | None = Field(default=None)
    FUNDAMENTAL_API_KEY: str | None = Field(default=None)

    # --- News provider (future phase) ---
    NEWS_PROVIDER: str | None = Field(default=None)
    NEWS_API_KEY: str | None = Field(default=None)

    # --- Analyst-estimate (1Y price target) provider ---
    # Default is the composite (TradingView primary + yfinance fallback/
    # recommendation source) - see packages/analyst_estimates/factory.py.
    ANALYST_ESTIMATE_PROVIDER: str | None = Field(default=None)

    # --- LLM / AI layer (Vertex AI Gemini) ---
    LLM_PROVIDER: str | None = Field(default="vertex_ai")
    LLM_API_KEY: str | None = Field(default=None)
    VERTEX_AI_MODEL: str = Field(default="gemini-3.5-flash")
    VERTEX_AI_LOCATION: str = Field(default="global")
    VERTEX_PROJECT_ID: str = Field(default="onboarding-bot-458509")
    GOOGLE_APPLICATION_CREDENTIALS: str | None = Field(default=None)

    # --- Security (auth is deferred, but secrets are provisioned now) ---
    JWT_SECRET: str = Field(default="dev-only-change-me")
    ENCRYPTION_KEY: str = Field(default="dev-only-change-me")

    # --- Object storage (future phase) ---
    S3_BUCKET: str | None = Field(default=None)
    AWS_REGION: str | None = Field(default=None)

    # --- API process config ---
    ENVIRONMENT: str = Field(default="development")
    LOG_LEVEL: str = Field(default="INFO")
    CORS_ALLOW_ORIGINS: str = Field(
        default="http://localhost:3000",
        description="Comma-separated list of allowed CORS origins.",
    )

    # --- Daily after-market-close sync cron (apps/worker/settings.py) ---
    # NSE closes at 15:30 IST. IST is UTC+5:30 year-round (India observes
    # no DST), so 15:30 IST == 10:00 UTC. The free yfinance EOD source
    # isn't always available the instant the market closes, so the
    # default here adds a ~3-hour safety buffer: 18:30 IST == 13:00 UTC
    # (18:30 - 5:30 = 13:00). See apps/worker/settings.py's `cron_jobs`
    # registration for the full IST<->UTC reasoning and arq's weekday
    # convention.
    DAILY_SYNC_HOUR_UTC: int = Field(
        default=13, description="UTC hour the daily after-close sync cron fires (default 13:00 UTC == 18:30 IST)."
    )
    DAILY_SYNC_MINUTE_UTC: int = Field(
        default=0, description="UTC minute the daily after-close sync cron fires (default :00)."
    )

    @property
    def cors_allow_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ALLOW_ORIGINS.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor. Use this everywhere instead of Settings()."""
    return Settings()
