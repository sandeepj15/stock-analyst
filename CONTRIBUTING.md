# Contributing to SignalForge

Thank you for your interest in contributing to **SignalForge**! SignalForge is an evidence-first equity research, quantitative screening, and market intelligence platform designed primarily for Indian equities (NSE/BSE).

We welcome contributions from developers, quantitative researchers, financial analysts, and designers. Whether you are fixing a bug, adding an indicator, improving the UI, or optimizing ingestion pipelines, this guide will help you get started.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Prerequisites & Development Environment](#prerequisites--development-environment)
3. [Quickstart: 1-Command Startup](#quickstart-1-command-startup)
4. [Local Development Workflow](#local-development-workflow)
   - [Running the Backend (FastAPI)](#running-the-backend-fastapi)
   - [Running the Frontend (Next.js)](#running-the-frontend-nextjs)
   - [Running the Background Worker (Arq)](#running-the-background-worker-arq)
5. [Database Migrations (Alembic)](#database-migrations-alembic)
6. [Data Pipelines & Scraping Tools](#data-pipelines--scraping-tools)
7. [Code Quality & Testing](#code-quality--testing)
8. [Pull Request & Contribution Process](#pull-request--contribution-process)

---

## Architecture Overview

SignalForge is built as a clean modular monorepo:

```
stock-analyst/
├── apps/
│   ├── api/            # FastAPI REST & streaming API (port 8000)
│   ├── web/            # Next.js 14 App Router, Tailwind CSS, TypeScript frontend (port 3000)
│   └── worker/         # Arq async background worker for data pipelines & scoring
├── packages/
│   ├── common/         # Core settings, database connection, models, caching
│   ├── fundamentals/   # Earnings ingest (Bronze/Silver/Gold), Screener.in parser, Smart Money Flow
│   ├── scoring/        # 7-component evidence synthesis engine (Research Score v3)
│   ├── market_data/    # Daily OHLCV candles, TradingView technical momentum signals
│   ├── momentum/       # 52-week breakouts & Volatility Contraction Pattern (VCP) scanner
│   ├── analyst_estimates/ # Target prices, upside percentages, and analyst ratings
│   ├── ai/             # Vertex AI / Gemini integration, thesis generator, AI Alpha Picks
│   └── kronos/         # Deep learning price trajectory forecast models
├── migrations/         # Alembic database migrations
├── scripts/            # CLI utilities (parallel sweeps, backfills, diagnostics)
└── infra/              # Docker, deployment, and networking configurations
```

---

## Prerequisites & Development Environment

To contribute to SignalForge, you will need:

* **Docker & Docker Compose** (v2.20+ recommended)
* **Python 3.12+** (if running services directly on host)
* **Node.js 20+** and **pnpm** (for frontend development)
* **Git**

---

## Quickstart: 1-Command Startup

The easiest way to get the entire stack (PostgreSQL 16, Redis 7, FastAPI Backend, Arq Worker, and Next.js Web) running locally is:

```bash
# 1. Clone the repository
git clone https://github.com/sandeepj15/stock-analyst.git
cd stock-analyst

# 2. Copy the environment template
cp .env.example .env

# 3. Start everything in Docker
./start.sh
# Or alternatively:
docker compose up --build -d
```

### Accessing Local Services

* **Web UI (Quant Screener, Market Pulse, AI Picks)**: [http://localhost:3000](http://localhost:3000)
* **FastAPI Interactive Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
* **API Health Check**: [http://localhost:8000/health/db](http://localhost:8000/health/db)

---

## Local Development Workflow

If you prefer hot-reloading on your local machine without running everything inside Docker containers:

### 1. Start Supporting Infra (Postgres & Redis)
```bash
docker compose up -d postgres redis
```

### 2. Running the Backend (FastAPI)
```bash
# Create and activate a Python virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

# Run database migrations
alembic upgrade head

# Start API server with live reload
uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. Running the Frontend (Next.js)
```bash
cd apps/web

# Install packages
pnpm install

# Start Next.js development server
pnpm dev
```
Open [http://localhost:3000](http://localhost:3000) to view changes in real time.

### 4. Running the Background Worker (Arq)
```bash
source .venv/bin/activate
arq apps.worker.settings.WorkerSettings
```

---

## Database Migrations (Alembic)

Database schemas are managed using **Alembic** with asynchronous SQLAlchemy:

* **Generate a new migration after editing models**:
  ```bash
  # Inside Docker:
  docker compose exec api alembic revision --autogenerate -m "add_new_feature_table"
  # Or on host:
  alembic revision --autogenerate -m "add_new_feature_table"
  ```
* **Apply pending migrations**:
  ```bash
  docker compose exec api alembic upgrade head
  ```
* **Downgrade one migration**:
  ```bash
  docker compose exec api alembic downgrade -1
  ```

---

## Data Pipelines & Scraping Tools

SignalForge includes automated scraping and synchronization utilities in `scripts/`:

* **High-Performance 5-Worker Screener.in Parallel Sweep**:
  Ingests Q2 FY27 earnings, BSE results announcements, and September 2026 shareholding patterns with serialized rate-limit pacing:
  ```bash
  docker compose exec -T api python /app/parallel_screener_sweep.py --workers 5
  ```
* **Market-Wide Research Score Recomputation**:
  Recalculates 7-component evidence scores across all 1,509 active equities:
  ```bash
  docker compose exec api python -c "
  import asyncio
  from packages.common.db import session_scope
  from packages.scoring.engine import recompute_universe_scores
  asyncio.run(recompute_universe_scores())
  "
  ```
* **Flush Cache Keys**:
  ```bash
  docker compose exec redis redis-cli eval "
  local k = redis.call('keys', 'instruments_listing:*')
  for i, key in ipairs(k) do redis.call('del', key) end
  return 'OK'
  " 0
  ```

---

## Code Quality & Testing

Before submitting a pull request, ensure your code conforms to project standards:

### Python Standards
* Use **type annotations** for all function signatures.
* Format and lint with **ruff**:
  ```bash
  ruff format .
  ruff check . --fix
  ```
* Run the test suite:
  ```bash
  pytest tests/
  ```

### TypeScript / Next.js Standards
* Strict typing: Avoid `any` where possible.
* Use Tailwind CSS utility classes adhering to the dark/light design system.
* Check types and linting:
  ```bash
  cd apps/web
  pnpm lint
  pnpm build
  ```

---

## Pull Request & Contribution Process

1. **Fork the repository** on GitHub.
2. **Create a branch** for your work:
   ```bash
   git checkout -b feat/add-relative-volume-filter
   # or: git checkout -b fix/screener-pagination
   ```
3. **Commit your changes** following [Conventional Commits](https://www.conventionalcommits.org/):
   * `feat: add relative volume spike filter to quant screener`
   * `fix: handle missing interest expense in quarterly table parsing`
   * `docs: update deployment and environment variables guide`
   * `perf: cache sector average score queries in redis`
4. **Push to your fork**:
   ```bash
   git push origin feat/add-relative-volume-filter
   ```
5. **Open a Pull Request** against `main` on the upstream repository with:
   * A clear summary of the problem and solution.
   * Screenshots or animated GIFs for UI changes.
   * Confirmation that migrations and tests pass.

---

### Need Help?

Feel free to open an issue or ask questions in the discussions tab on GitHub. Happy coding!
