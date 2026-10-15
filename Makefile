.PHONY: up dev down logs ps migrate seed test lint

up:
	docker compose up --build -d

dev:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

down:
	docker compose down

logs:
	docker compose logs -f

ps:
	docker compose ps

migrate:
	docker compose exec api alembic upgrade head

seed:
	docker compose exec api python scripts/seed_dev_data.py

seed-fundamentals:
	docker compose exec api python scripts/seed_fundamentals.py

seed-fundamentals-fallback:
	docker compose exec -e FUNDAMENTAL_PROVIDER=yfinance_tradingview_fallback api python scripts/seed_fundamentals.py

expand-universe:
	docker compose exec worker python scripts/expand_universe.py

scrape-screener:
	docker compose exec worker python scripts/scrape_raw_screener.py

parse-screener:
	docker compose exec worker python scripts/parse_structured_screener.py
	docker compose exec worker python -c "import asyncio; from apps.worker.jobs import sync_quarterly_fundamentals_job; asyncio.run(sync_quarterly_fundamentals_job({}))"

sync-screener:
	docker compose exec worker python scripts/scrape_raw_screener.py
	docker compose exec worker python scripts/parse_structured_screener.py
	docker compose exec worker python -c "import asyncio; from apps.worker.jobs import sync_quarterly_fundamentals_job, compute_all_scores_job; asyncio.run(sync_quarterly_fundamentals_job({})); asyncio.run(compute_all_scores_job({}))"

run-forecasts:
	docker compose exec worker python run_all_forecasts.py

sync-regime:
	docker compose exec worker python -c "import asyncio; from apps.worker.jobs import sync_market_regime; print(asyncio.run(sync_market_regime({})))"

sync-analyst-estimates:
	docker compose exec worker python -c "import asyncio; from apps.worker.jobs import sync_analyst_estimates_job; print(asyncio.run(sync_analyst_estimates_job({})))"

compute-scores:
	docker compose exec worker python -c "import asyncio; from apps.worker.jobs import compute_all_scores_job; print(asyncio.run(compute_all_scores_job({})))"

compute-momentum-scans:
	docker compose exec worker python -c "import asyncio; from apps.worker.jobs import compute_all_momentum_scans_job; print(asyncio.run(compute_all_momentum_scans_job({})))"

test:
	pytest -q

lint:
	ruff check .
	mypy apps packages

