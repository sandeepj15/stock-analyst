# SignalForge

SignalForge is an evidence-first market research and decision-support platform
for retail investors (Indian equities first). The full product/engineering
specification lives in [`SPEC.md`](./SignalForge_Trading_Research_Engine_SPEC.md)
— read it before changing anything.

**This repository currently implements SPEC.md's Phases 0-4 scope:**

- Repository scaffold, FastAPI app, async Postgres/SQLAlchemy, Alembic, Arq
  worker, Docker Compose, CI, structured logging, health checks.
- Instrument master + OHLCV daily data model.
- A provider-agnostic `MarketDataProvider` interface (SPEC.md section 8) with
  a `yfinance`-backed development provider.
- A data quality layer (schema/range/duplicate/missing-day/outlier checks).
- An idempotent ingestion service + Arq job + seed script.
- Technical indicators, regime detection, momentum scans, and scoring.
- Next.js frontend with stock charts, screener, and evidence dashboard.

**Not implemented yet** (later phases, see SPEC.md section 101): strategy builder, authentication, AI layer,
alerts, portfolio. See "Known limitations" below.

## Architecture

```
apps/
  api/        FastAPI app (apps/api/main.py)
  worker/     Arq background worker (apps/worker/settings.py, jobs.py)
  web/        Next.js placeholder frontend
packages/
  common/     Settings, logging, async DB session (shared by everything)
  market_data/  Provider protocol + yfinance dev provider + quality + ingestion
  analytics/, indicators/, scoring/, backtesting/, fundamentals/, news/,
  portfolio/, alerts/, ai/   Empty placeholders for later build phases
migrations/   Alembic migrations (async, targets packages.common.models.Base)
tests/        unit, integration, backtest, data_quality, api
docs/         architecture, data_dictionary, scoring, runbooks (to fill in later phases)
scripts/      scripts/seed_dev_data.py
infra/docker/ reserved for future infra-as-code; Docker Compose + root Dockerfile cover local dev today
```

### Model layout decision

- `packages/common/models.py` defines the shared SQLAlchemy `Base` plus the
  `Instrument` model (instrument master, SPEC.md section 9).
- `packages/market_data/models.py` defines `OHLCVDaily`, `DataIngestionRun`,
  and `DataQualityEvent` (SPEC.md sections 10, 11, 45), importing `Base` from
  `packages.common.models`.

This keeps one declarative `Base` (so Alembic autogenerate sees every table)
while letting each domain package own its own tables going forward.

### Provider abstraction

`packages/market_data/base.py` defines the `MarketDataProvider` Protocol and
the provider-agnostic `InstrumentData` / `DailyBar` / `IntradayBar` / `Quote`
types. **No code outside `packages/market_data` imports `yfinance` directly.**
`packages/market_data/providers/yfinance_provider.py` is the only concrete
implementation right now, and it is explicitly a local-development-only
provider — see [`DATA_SOURCES.md`](./DATA_SOURCES.md).

## Local development from a clean checkout

Prerequisites: Docker + Docker Compose. (A local Python 3.12 virtualenv is
only needed if you want to run tests/lint outside Docker — see below.)

```bash
cp .env.example .env
# generate real secrets (dev-only placeholders won't fail anything, but don't ship them):
#   openssl rand -hex 32   # paste into JWT_SECRET
#   openssl rand -hex 32   # paste into ENCRYPTION_KEY

make up        # docker compose up --build  (postgres, redis, api, worker, web)
make migrate   # alembic upgrade head, run inside the api container
make seed      # scripts/seed_dev_data.py, run inside the api container
                # seeds 20 NSE large-caps + ~2 years of daily bars via yfinance
make test      # pytest (see "Running tests locally" below)
make lint      # ruff check + mypy
```

Once `make up` is running:
- API: http://localhost:8000 (`/health`, `/health/db`, `/health/redis`,
  `/api/v1/instruments/search?q=RELI`, `/api/v1/instruments/RELIANCE`)
- Web frontend: http://localhost:3000 (Next.js UI implementing the stock research dashboard, market regimes, screener, and charting)

`make backtest` is a placeholder (`echo "Backtesting not implemented yet"`) —
backtesting is SPEC.md Phase 6, out of scope here.

### Docker layout

A single root `Dockerfile` is shared by the `api` and `worker` services
(docker-compose.yml overrides the `command` per service) since they share the
exact same Python dependency set and codebase. `apps/web` has its own
`Dockerfile` (Node/Next.js).

### Running tests locally

The ORM models use PostgreSQL-specific types (`UUID`, `JSONB`, native
`ENUM`), and the ingestion service relies on
`postgresql.insert(...).on_conflict_do_update(...)`, which has no SQLite
equivalent. Because of that, **every test that touches the database runs
against a real (disposable) Postgres** — there is no SQLite-based test path
in this repo.

Fastest local loop (no need to bring up the full compose stack):

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Point at any scratch Postgres - for example, run just the postgres service:
docker compose up -d postgres
export TEST_DATABASE_URL="postgresql+asyncpg://signalforge:signalforge@localhost:5432/signalforge_test"
export DATABASE_URL="postgresql+asyncpg://signalforge:signalforge@localhost:5432/signalforge"

pytest -q
```

`tests/conftest.py` creates/drops all tables directly via
`Base.metadata.create_all` against `TEST_DATABASE_URL` (bypassing Alembic for
speed) once per test, inside a fresh engine (engines are intentionally
function-scoped — see the comment in `conftest.py` about asyncpg + event
loops). No test hits the real network or a real market-data provider; all
provider interactions in tests use `tests/fixtures/fake_provider.py`.

CI (`.github/workflows/ci.yml`) runs the same tests against a `postgres:16`
GitHub Actions service container, then does a (push-free) `docker compose
build`.

## Known limitations / explicit deferrals

- **Auth/tenant isolation**: not implemented. All endpoints in this phase
  expose only public reference data (instruments, OHLCV) — no user-owned
  data exists yet. SPEC.md section 101 places auth + tenant isolation in the
  production-hardening phase (section 96).
- **Market data provider**: `yfinance` is free/no-key but explicitly *not*
  licensed for commercial redistribution. See `DATA_SOURCES.md`.
- **Intraday bars / live quotes**: `YFinanceDevProvider.get_intraday_bars`
  raises `NotImplementedError` by design (yfinance's intraday data is
  retention-limited and flaky) rather than fabricating data.
  `get_quotes` is a best-effort approximation using `fast_info`, fine for
  dev, not a real-time feed.
- **NSE holiday calendar**: `detect_missing_trading_days` approximates
  expected trading days as all weekdays. It does not yet exclude exchange
  holidays — this will over-report missing days around holidays. Tracked as
  a future improvement, not implemented here.
- **Next.js frontend**: Implements the Phase 4 scope (stock research, momentum scans, charting). Advanced features like authentication and strategy builders are still pending.
- **Prometheus/Grafana**: deferred to Phase 11 (SPEC.md section 105.3) — not
  present in `docker-compose.yml` even though `infra/docker/` exists.
- **Analytics / scoring / backtesting / strategy builder / alerts /
  portfolio / AI layer**: not implemented — out of scope per the task brief
  for this phase (SPEC.md sections 82-83 only).
- **`instrument_ids` type in the worker job**: SPEC.md's pseudocode for
  `sync_daily_bars` uses `list[int]`; this implementation uses `list[str]`
  (UUID strings) because the instrument primary key is a UUID. See the
  docstring in `apps/worker/jobs.py`.

## Documentation

- [`DATA_SOURCES.md`](./DATA_SOURCES.md) — exactly which data sources are
  used, which are free/dev-only, and what's required before commercial
  launch.
- `SignalForge_Trading_Research_Engine_SPEC.md` — the authoritative spec.
  Everything in this repo should trace back to a section of it.
