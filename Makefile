.PHONY: up down migrate seed seed-fundamentals sync-regime compute-scores test lint

up:
	docker compose up --build

down:
	docker compose down

migrate:
	docker compose exec api alembic upgrade head

seed:
	docker compose exec api python scripts/seed_dev_data.py

# Phase 3 (SPEC.md sections 12, 15): fundamentals backfill + market
# regime computation. Both are idempotent and safe to re-run.
seed-fundamentals:
	docker compose exec api python scripts/seed_fundamentals.py

# Same as `seed-fundamentals`, but with the tradingview-ta secondary
# provider enabled to fill fields yfinance left NULL (see
# packages/fundamentals/providers/composite_provider.py, DATA_SOURCES.md).
seed-fundamentals-fallback:
	docker compose exec -e FUNDAMENTAL_PROVIDER=yfinance_tradingview_fallback api python scripts/seed_fundamentals.py

sync-regime:
	docker compose exec worker python -c "import asyncio; from apps.worker.jobs import sync_market_regime; print(asyncio.run(sync_market_regime({})))"

# Standalone/manually-triggerable (never part of the daily cron - analyst
# targets don't move daily, same reasoning as fundamentals). Default
# provider is the TradingView+yfinance composite (see
# packages/analyst_estimates/factory.py).
sync-analyst-estimates:
	docker compose exec worker python -c "import asyncio; from apps.worker.jobs import sync_analyst_estimates_job; print(asyncio.run(sync_analyst_estimates_job({})))"

# Batch-precompute Research Scores for every active instrument so
# GET /api/v1/instruments?sort=score has real, persisted scores to sort
# (UI/UX task). Idempotent/safe to re-run; the valuation-universe scan
# is computed once per run, not once per instrument - see
# packages/scoring/components.py and apps/worker/jobs.py.
compute-scores:
	docker compose exec worker python -c "import asyncio; from apps.worker.jobs import compute_all_scores_job; print(asyncio.run(compute_all_scores_job({})))"

# Batch-precompute Stage 2 Momentum Scans for every active instrument
# (packages/momentum/) so GET /api/v1/instruments?momentum_pass=true and
# ?sort=momentum_pass have real, persisted scans to read. Idempotent/safe
# to re-run; RS Rank's universe scan is computed once per run, not once
# per instrument - see packages/momentum/service.py and apps/worker/jobs.py.
compute-momentum-scans:
	docker compose exec worker python -c "import asyncio; from apps.worker.jobs import compute_all_momentum_scans_job; print(asyncio.run(compute_all_momentum_scans_job({})))"

# `test` runs inside a local virtualenv (not in-container) because it is
# faster for iterative development and does not require the full compose
# stack to be up - only a reachable Postgres (see README.md "Running
# tests locally"). CI instead starts a postgres:16 service container.
test:
	pytest -q

lint:
	ruff check .
	mypy apps packages
