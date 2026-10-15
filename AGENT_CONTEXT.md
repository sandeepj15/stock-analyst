# SignalForge (stock-analyst) — Complete Codebase & Architecture Guide for AI Agents

> **Purpose of this document:**  
> This file is the primary end-to-end reference for AI coding agents (Claude, GPT, Gemini, Cursor, Copilot, etc.) working on the **SignalForge** (`stock-analyst`) codebase. It details the system architecture, domain models, mathematical formulas, data ingestion pipelines, background worker schedules, API endpoints, frontend design system, and operational rules so any agent can immediately orient itself, understand the full system context, and implement new features or refactors safely without introducing regressions.

---

## 1. System Overview & Core Philosophy

**SignalForge** is an institutional-grade, evidence-first quantitative stock research, ranking, and decision-support engine designed for **Indian Equities (NSE)** covering an active universe of **~1,510 stocks**.

### 1.1 Non-Negotiable Core Principles
1. **Evidence-First Over Opinion**: Every metric, score, or signal is computed deterministically from verified data. No LLM hallucinations or opaque black boxes in the analytical or scoring core.
2. **Never Overwrite Raw Source Data**: Data follows a Bronze $\rightarrow$ Silver $\rightarrow$ Gold pipeline:
   - *Bronze Layer* (`raw_provider_scrapes`): Verbatim HTML responses from providers (e.g., Screener.in).
   - *Silver Layer* (`structured_provider_data`): Normalized JSON representations of tables.
   - *Gold Layer* (`fundamental_snapshots`, `ohlcv_daily`): Validated, typed relational records.
3. **Strict Methodology Versioning**: If a scoring or scanning formula changes, the version must be incremented (e.g., `research_score_v1` $\rightarrow$ `research_score_v2`). Historical records are never retroactively modified or silently reinterpreted.
4. **Single Declarative ORM Base**: All SQLAlchemy tables across domain packages inherit from `packages.common.models.Base` to ensure seamless Alembic migrations and foreign key integrity.
5. **Redis Cache-First**: Expensive multi-stock computations (e.g., scores, technical indicators, momentum scans) are precomputed during scheduled worker runs and populated into Redis with explicit TTLs. API endpoints read from cache first.
6. **Postgres-Specific Async Implementation**: The database uses PostgreSQL 16 features (`UUID`, `JSONB`, native ENUMs, `on_conflict_do_update`). **Never attempt to run tests or migrations against SQLite.**

---

## 2. Technology Stack & Infrastructure

| Layer | Technologies & Libraries |
| :--- | :--- |
| **Backend API** | Python 3.12, FastAPI, Pydantic v2, Uvicorn |
| **Database & ORM** | PostgreSQL 16, SQLAlchemy 2.0 (async via `asyncpg`), Alembic |
| **Caching & Job Queue** | Redis 7, Arq (async Redis-backed background worker) |
| **Analytics & Quant** | NumPy, Pandas, SciPy, custom TA indicator library |
| **Machine Learning** | PyTorch, HuggingFace Safetensors, Kronos foundation model (fine-tuned on NSE) |
| **Frontend UI** | Next.js 14+ (App Router), React 18, TypeScript, CSS Variables, Lucide icons |
| **Data Providers** | `yfinance` (EOD prices, financials fallback), NSE official lists, Screener.in, TradingView batch scanner |
| **Containerization** | Docker, Docker Compose (multi-service: `postgres`, `redis`, `api`, `worker`, `web`) |

---

## 3. Repository Directory Layout

```
stock-analyst/
├── apps/
│   ├── api/                     # FastAPI application
│   │   ├── main.py              # Application factory & router registration
│   │   └── routes/              # Modular endpoint routers
│   │       ├── analyst.py       # Consensus analyst ratings & price targets
│   │       ├── fundamentals.py  # Financial statements & ratios
│   │       ├── health.py        # System health & readiness probes (/health, /health/db, /health/redis)
│   │       ├── instruments.py   # Instrument search, listing, and screener endpoints
│   │       ├── market.py        # Market regime, score distribution, sector aggregations
│   │       ├── momentum.py      # Minervini Stage 2 & momentum scan endpoints
│   │       ├── scoring.py       # Research Strength v2 scores & bull/bear evidence
│   │       └── stocks.py        # Consolidated ticker details (technicals, forecasts, forensics)
│   ├── worker/                  # Arq background worker service
│   │   ├── jobs.py              # Async ETL and cron tasks
│   │   └── settings.py          # Arq WorkerSettings & cron schedule definitions
│   └── web/                     # Next.js 14+ React Frontend (App Router)
│       ├── app/                 # Routes, layout, and global styling (globals.css)
│       ├── components/          # Reusable UI components
│       │   ├── AboutCompanySection.tsx   # Company overview, AI business summary, key segments & website
│       │   ├── BreadthGauge.tsx          # Market breadth gauge (DMA50 / DMA200)
│       │   ├── BullBearPanel.tsx         # Structured bull/bear thesis cards
│       │   ├── ComponentBreakdownPanel.tsx # 8-part score breakdown
│       │   ├── FundamentalsPanel.tsx     # Financial statements & DuPont analysis
│       │   ├── GlobalSearch.tsx          # Omnibar ticker search
│       │   ├── HealthDiagnostics.tsx     # Piotroski, Altman Z, Beneish forensics
│       │   ├── HomeBrowser.tsx           # Main screener, multi-sort bar, table view
│       │   ├── MarketPulse.tsx           # Market regime, sector heatmap, top movers
│       │   ├── ShareholdingChart.tsx     # Institutional shareholding flow (FII/DII)
│       │   ├── StockCharts.tsx           # Price charts & technical indicator overlays
│       │   ├── StockHeroTiles.tsx        # Hero KPI tiles (Research Score, Stage 2, Analyst Target)
│       │   └── StockPageClient.tsx       # Tabbed stock research page
│       └── lib/                 # Frontend client utilities (api.ts, types.ts, sort.ts, format.ts)
├── packages/                    # Modular internal Python domain packages
│   ├── analyst_estimates/       # Consensus target providers (TradingView batch, yfinance)
│   ├── analytics/               # Quantitative primitives (returns, volatility, trend, volume)
│   ├── common/                  # Shared database session, base models, config, logging, cache
│   ├── fundamentals/            # Financial statement parsing, forensic checks, shareholding flows
│   ├── indicators/              # Technical indicators (SMA, EMA, RSI, MACD, ATR, Bollinger, ADX)
│   ├── kronos/                  # ML price forecasting model & inference service
│   ├── market_data/             # Ingestion protocol, yfinance provider, data quality audits
│   ├── momentum/                # Minervini Stage 2 scanner, RS Percentile rank engine
│   ├── regime/                  # Market regime classifier (Nifty 50 vs 200 DMA + breadth)
│   ├── scoring/                 # Research Strength v2 score engine & evidence builder
│   └── strategy/                # VCP (Volatility Contraction Pattern) scanning models
├── migrations/                  # Alembic asynchronous database migrations
├── scripts/                     # Seeders, ETL pipelines, backfills, and CLI utilities
└── tests/                       # Unit, integration, and quantitative verification test suite
```

---

## 4. Database Schema & Domain Models

All models inherit from `packages.common.models.Base`.

```mermaid
erDiagram
    instruments ||--o{ ohlcv_daily : "has daily bars"
    instruments ||--o{ fundamental_snapshots : "has financials"
    instruments ||--o{ analyst_estimates : "has price targets"
    instruments ||--o{ research_scores : "has scores"
    instruments ||--o{ momentum_scans : "has stage 2 scans"
    instruments ||--o{ ml_forecasts : "has price predictions"
    instruments ||--o{ raw_provider_scrapes : "has raw HTML"
    instruments ||--o{ structured_provider_data : "has parsed JSON"
    instruments ||--o{ instrument_aliases : "has renamed tickers"

    instruments {
        uuid id PK
        string symbol UK "e.g. RELIANCE"
        string exchange "NSE"
        string isin UK
        string company_name
        string sector
        string industry
        boolean active
    }

    ohlcv_daily {
        uuid id PK
        uuid instrument_id FK
        date timestamp
        numeric open
        numeric high
        numeric low
        numeric close
        numeric adjusted_close
        numeric volume
    }

    research_scores {
        uuid id PK
        uuid instrument_id FK
        date as_of_date
        numeric total_score "0-100"
        string band "Very Strong -> Very Weak"
        jsonb component_scores
        jsonb evidence_items
        string methodology_version "research_score_v2"
    }

    fundamental_snapshots {
        uuid id PK
        uuid instrument_id FK
        date period_end
        string period_type "FY or TTM"
        numeric revenue
        numeric pat
        numeric eps
        numeric operating_cash_flow
        numeric total_debt
        numeric equity
        numeric roe
        numeric roce
    }

    market_regimes {
        uuid id PK
        date as_of_date UK
        string regime "BULLISH_TREND | BEARISH_TREND | CHOPPY"
        numeric benchmark_close
        numeric breadth_above_50dma_pct
        numeric breadth_above_200dma_pct
    }
```

### Key Models Reference:
- **`Instrument`** (`packages/common/models.py`): Primary ticker master. Natural key is `(exchange, symbol)`. Supports ticker renames via `InstrumentAlias` (e.g. `ZOMATO` $\rightarrow$ `ETERNAL`).
- **`OHLCVDaily`** (`packages/market_data/models.py`): EOD price bars. Crucially stores both unadjusted `close` and split/dividend-adjusted `adjusted_close`.
- **`DataQualityEvent`** (`packages/market_data/models.py`): Tracks ingestion anomalies (zero prices, extreme spikes, duplicate bars, missing dates).
- **`FundamentalSnapshot`** (`packages/fundamentals/models.py`): Standard financial metrics (Revenue, PAT, EPS, Debt, Equity, Cash Flow).
- **`RawProviderScrape` & `StructuredProviderData`** (`packages/fundamentals/models.py`): Bronze/Silver data lake storage for Screener.in scrapes, preserving full auditability.
- **`AnalystEstimate`** (`packages/analyst_estimates/models.py`): 1-year consensus target prices, upside percentage, analyst coverage count, and buy/hold/sell distributions.
- **`ResearchScore`** (`packages/scoring/models.py`): Total score (0-100), 8 component breakdowns, and bullish/bearish factual evidence points.
- **`MomentumScan`** (`packages/momentum/models.py`): Minervini Stage 2 criteria pass/fail status, individual condition states, and universe RS rank.
- **`MarketRegime`** (`packages/regime/models.py`): Daily macro environment tracking based on Nifty 50 and universe breadth.
- **`MLForecast`** (`packages/common/models.py`): Kronos 5-day predictive trajectory distributions.

---

## 5. Quantitative Methodologies & Algorithms

### 5.1 Research Strength Engine (`research_score_v2`)
The headline score ranges from **0 to 100** with a neutral baseline of **50**. Every component accumulates points based on deterministic thresholds and clamps to `[0, 100]`.

| Component | Weight | Package Function | Description |
| :--- | :---: | :--- | :--- |
| **Technical Structure** | **20%** | `score_technical_structure_points` | Trend alignment: Close vs SMA50/SMA200, Golden Cross, ADX, 20d Highs |
| **Fundamentals** | **20%** | `compute_fundamental_score` | 4 pillars: Growth, Profitability, Leverage, and Efficiency |
| **Momentum** | **15%** | `score_momentum_points` | RSI(14) momentum zones, MACD histogram expansion, volume trend |
| **Valuation** | **10%** | `score_valuation_points` | Historical P/E, P/B, EV/EBITDA, and sector-relative valuation |
| **Sector Relative Strength** | **10%** | `score_sector_relative_strength_points` | Outperformance of stock vs. its sector peer group |
| **Market Regime** | **10%** | `market_regime_signal` | Macro tailwind/headwind (+10 in Bull Trend, -10 in Bear Trend) |
| **Risk Quality** | **10%** | `score_risk_quality_points` | Volatility penalty, Maximum Drawdown, Beta |
| **Event / News Context** | **5%** | Neutral baseline | Reserved for future corporate announcements |

#### Score Bands
- **Very Strong**: 80 – 100 (Green)
- **Strong**: 65 – 79 (Light Green)
- **Moderate**: 50 – 64 (Blue)
- **Neutral**: 35 – 49 (Muted Gray)
- **Weak**: 20 – 34 (Orange)
- **Very Weak**: 0 – 19 (Red)

### 5.2 Minervini Stage 2 Momentum Scanner (`stage2_momentum_v1`)
A stock passes Minervini's Trend Template **only if all 8 conditions are met**:
1. `Close > SMA150` and `Close > SMA200`
2. `SMA150 > SMA200`
3. `SMA200` trending upward over lookback (default 22 trading days)
4. `SMA50 > SMA150` and `SMA50 > SMA200`
5. `Close > SMA50`
6. `Close >= 1.30 * 52_week_low` (at least 30% above 52-week low)
7. `Close >= 0.75 * 52_week_high` (within 25% of 52-week high)
8. `RS_Rank >= 70` (Relative strength in top 30% of the entire universe)

### 5.3 Financial Health & Forensic Forensics (`packages/fundamentals/health.py`)
- **Piotroski F-Score (0 to 9)**: Tests Profitability (ROA, CFO, $\Delta$ROA, Accrual), Leverage/Liquidity ($\Delta$Leverage, $\Delta$CurrentRatio, Dilution), and Operating Efficiency ($\Delta$GrossMargin, $\Delta$AssetTurnover).
- **Altman Z-Score**: Assesses bankruptcy distress risk using working capital, retained earnings, EBIT, equity/liabilities, and sales ratios.
- **DuPont Analysis**: 3-stage and 5-stage decomposition of Return on Equity into Tax Burden, Interest Burden, Operating Margin, Asset Turnover, and Financial Leverage.
- **Earnings Quality Shield**: Detects divergence between Net Income and Operating Cash Flow (CFO < PAT warnings, accrual anomalies).

### 5.4 Market Regime Engine (`packages/regime/classifier.py`)
Classifies overall market state using Nifty 50 (`^NSEI`) and the 1,510-stock universe:
- `BULLISH_TREND`: Index above 50 DMA and 200 DMA, Golden Cross active, breadth $> 50\%$.
- `BEARISH_TREND`: Index below 200 DMA or Death Cross active, breadth $< 40\%$.
- `DISTRIBUTION`: Index near highs but internal breadth deteriorating rapidly.
- `CHOPPY / NEUTRAL`: Mixed moving averages and consolidating breadth.

---

## 6. Background Jobs & Data Pipelines (Arq Worker)

The background worker (`apps/worker/`) manages batch synchronizations via Redis and Arq.

```mermaid
flowchart TD
    CronTrigger["18:30 IST / 13:00 UTC (Mon-Fri)"] --> DailySync["daily_market_close_sync()"]
    
    subgraph DailySyncPipeline["Daily Market Close Pipeline (~3.5 minutes)"]
        DailySync --> Step1["1. sync_daily_bars()<br/>Ingest EOD OHLCV via yfinance batch"]
        Step1 --> Step2["2. sync_market_regime()<br/>Classify Nifty & Breadth (% > 50/200 DMA)"]
        Step2 --> Step3["3. compute_all_scores_job()<br/>Calculate Research Score v2 for 1,509 stocks"]
        Step3 --> Step4["4. compute_all_momentum_scans_job()<br/>Run Minervini Stage 2 & RS percentiles"]
        Step4 --> Step5["5. Invalidate & Prime Redis Caches"]
    end

    SaturdayCron["Saturday 07:30 IST / 02:00 UTC"] --> WeeklySync["sync_analyst_estimates_job()<br/>TradingView Batch Scanner (4s run)"]
```

### Pipeline Details:
- **`daily_market_close_sync`**: Runs Monday through Friday at **18:30 IST (13:00 UTC)**, allowing a ~3-hour safety window after the 15:30 IST market close for data providers to settle EOD adjusted bars.
- **`sync_analyst_estimates_job`**: Uses `TradingViewAnalystProvider` in chunks of 250 tickers with browser user-agent headers to fetch 1Y consensus price targets across all 1,510 stocks in under 5 seconds. Runs weekly on Saturday morning.

---

## 7. API Routing & Endpoints Reference

Base URL: `http://localhost:8000` (or reverse-proxied at `/api/v1`)

### 7.1 Market & Discovery
- `GET /api/v1/instruments`: List/search instruments. Supports sorting by `score`, `pat_growth_yoy`, `revenue_growth_yoy`, `analyst_upside_pct`, `day_change_pct`, and filters for sector, score band, Stage 2 status.
- `GET /api/v1/instruments/search?q={query}`: Fast debounced ticker/name search.
- `GET /api/v1/instruments/{symbol}`: Instrument master profile and metadata.
- `GET /api/v1/market/regime`: Latest market regime, Nifty technical status, and breadth % metrics.
- `GET /api/v1/market/score-distribution`: Universe count distribution across the 6 score bands.
- `GET /api/v1/market/sectors`: Sector performance, stock counts, and average research score.

### 7.2 Stock Research Endpoints
- `GET /stocks/{symbol}/price`: Real-time/EOD price, day change, volume, historical bars.
- `GET /stocks/{symbol}/score`: Research Strength v2 breakdown, 8 component point values.
- `GET /stocks/{symbol}/evidence`: Top bullish and bearish factual evidence statements.
- `GET /stocks/{symbol}/momentum-scan`: Minervini Stage 2 evaluation, RS Rank, individual pass/fail criteria.
- `GET /stocks/{symbol}/fundamentals`: Financial statements, growth rates, ratios, DuPont decomposition.
- `GET /stocks/{symbol}/structured`: Raw structured balance sheets/income statements from the silver data lake.
- `GET /stocks/{symbol}/analyst-rating`: Consensus target price, upside %, analyst count, buy/hold/sell spread.
- `GET /stocks/{symbol}/technicals`: SMA (20, 50, 150, 200), EMA, RSI(14), MACD, ADX, Bollinger Bands.
- `GET /stocks/{symbol}/relative-strength`: Benchmark comparison and performance ratios.
- `GET /stocks/{symbol}/forecast`: Kronos 5-day ML price trajectory and expected return bounds.
- `GET /stocks/{symbol}/diagnostic`: Comprehensive health check (Piotroski F-score, Altman Z, Beneish warnings).

### 7.3 System Health
- `GET /health`: Overall API service check.
- `GET /health/db`: PostgreSQL async connection probe.
- `GET /health/redis`: Redis connection and latency probe.

---

## 8. Frontend Architecture & Design System

The frontend is built in **Next.js (App Router)** with a responsive, high-density financial terminal aesthetic inspired by platforms like Binance and Bloomberg.

### 8.1 Styling & Theme System (`apps/web/app/globals.css`)
All styling is driven by strict CSS variables. **Never hardcode arbitrary hex colors in components.**
- Surface tokens: `--bg` (`#05070a`), `--panel` (`#0c0f14`), `--surface-sunken` (`#080a0e`), `--surface-alt` (`#141a22`), `--surface-raised` (`#11161d`).
- Accent & Feedback: `--accent` (`#f2a93b` warm amber), `--up` (`#2fbf71` green), `--down` (`#f0494c` red), `--warn` (`#f0b429`).
- Tabular figures: Numeric values use class `.num` (`font-variant-numeric: tabular-nums`) so decimal columns align vertically.

### 8.2 Home Dashboard (`apps/web/components/HomeBrowser.tsx`)
1. **Market Pulse Strip**: Displays the current market regime badge, breadth gauge, Nifty mini-chart, top gainers/losers, and sector performance heatmap.
2. **Screener Filters**: Search query, sector dropdown, score min/max, min upside %, min revenue growth %, min PAT growth %, and 1M/6M/1Y return thresholds.
3. **Visual Sort & Filter Pills Bar**:
   - Sort priority chips (`[#1 PAT YoY ▼ DESC] [#2 Target ▼ DESC]`) with direction toggle (`▲`/`▼`) and individual removal (`✕`).
   - `+ Add Sort Column…` dropdown to dynamically chain multi-column tie-breakers.
   - Active filter chips with one-click dismiss and a `Clear All` button.
4. **Shift+Click Multi-Sort Table**:
   - Single click on header: sorts by that column exclusively.
   - **Shift + Click** on header: chains secondary/tertiary tie-breakers with priority number badges displayed in header cells (`1`, `2`).
   - Sticky pinned left columns for row index and Symbol/Company.

### 8.3 Stock Detail Page (`apps/web/components/StockPageClient.tsx`)
Structured with a sticky ticker summary header and 6 detailed analysis tabs:
1. **Overview**: Research Score gauge, bull/bear evidence cards, 8-component breakdown, analyst target summary.
2. **Fundamentals**: Quarterly/annual financial trends, growth metrics, profitability margins, debt structure.
3. **Shareholding**: Promoter, FII, DII, and retail holding changes across recent quarters with institutional inflow/outflow charts.
4. **Technicals & Charts**: Interactive candlestick charts with volume, moving average overlays, and RSI/MACD sub-charts.
5. **ML Forecasts**: Kronos 5-day predictive trajectory visualization with upper/lower bounds.
6. **Health Diagnostics**: Piotroski F-score breakdown (all 9 tests), Altman Z distress gauge, and forensic accounting flags.

---

## 9. Developer Rules & Best Practices for AI Agents

When working on this repository, all AI agents must follow these operational guidelines:

### 1. Database Operations & Tests
- **Never use SQLite.** All tests that touch the database must point to a real Postgres instance using `asyncpg`.
- When adding tables or columns, create an Alembic migration in `migrations/versions/` using `alembic revision -m "..."` and verify with `alembic upgrade head`.
- Use SQLAlchemy 2.0 syntax: `select()`, `where()`, and `async with session_scope() as session:`.

### 2. Provider Isolation
- **Never import `yfinance` or external web scrapers directly into routers or UI components.**
- All external data fetching must be encapsulated within `packages/<domain>/providers/` adhering to the domain's Protocol interface.

### 3. State & Caching
- Any computationally intensive algorithm must implement write-through caching in Redis using keys defined in the domain package (e.g., `packages/scoring/engine.py`).
- Cache invalidation is coordinated in `apps/worker/jobs.py`.

### 4. Code Style & Integrity
- Maintain strict TypeScript types in `apps/web/lib/types.ts` mirroring backend Pydantic schemas.
- Preserve existing comments, docstrings, and error handling.
- Use GitHub-style markdown file links when providing summaries to users (e.g., `[filename.py](file:///path/to/filename.py)`).

---

## 10. Common CLI Commands & Runbook

### Starting Local Services (Docker)
```bash
make up         # Starts postgres, redis, api, worker, web via docker compose
make down       # Stops all containers
make migrate    # Runs alembic upgrade head inside api container
make seed       # Seeds NSE stock universe and initial bars
```

### Running Tests & Linting
```bash
# Outside docker (requires local python 3.12 venv)
source .venv/bin/activate
export TEST_DATABASE_URL="postgresql+asyncpg://signalforge:signalforge@localhost:5432/signalforge_test"
export DATABASE_URL="postgresql+asyncpg://signalforge:signalforge@localhost:5432/signalforge"
pytest -q tests/

# Type checking frontend
cd apps/web && npx tsc --noEmit
```

### Triggering Background Jobs Manually
```bash
# Execute daily sync pipeline immediately via worker container
docker compose exec worker python -c "import asyncio; from apps.worker.jobs import daily_market_close_sync; asyncio.run(daily_market_close_sync({}))"

# Recompute all research scores
docker compose exec worker python -c "import asyncio; from apps.worker.jobs import compute_all_scores_job; asyncio.run(compute_all_scores_job({}))"

# Sync analyst estimates via TradingView batch provider
docker compose exec worker python -c "import asyncio; from apps.worker.jobs import sync_analyst_estimates_job; asyncio.run(sync_analyst_estimates_job({}))"
```

---

## 11. AI Assistant & Vertex AI Gemini Integration (Phase 10)

### Architecture
- **Provider & Model**: Google Cloud Vertex AI in the `global` region using `gemini-2.5-flash` (~1.5s latency, 1M token context, high reasoning).
- **Authentication**: Service account credentials loaded from `secrets/vertex-ai-key.json` or `GOOGLE_APPLICATION_CREDENTIALS`.
- **Zero-Hallucination & Token-Efficient Design**:
  1. **Live Ground-Truth Snapshot**: When a stock symbol is specified, the backend compiles a compact ~350-word factual brief from live PostgreSQL tables (`instruments`, `ohlcv_daily`, `research_scores`, `momentum_scans`, `analyst_estimates`, `structured_provider_data`) and injects it directly into Gemini's system instructions.
  2. **Read-Only Database Query Tool (`query_database`)**: When users ask cross-stock, ranking, or screening queries (e.g. "which stock has the healthiest PE for long term?", "top 5 tech stocks with Stage 2 pass"), Gemini writes and invokes a safe read-only SQL query via `pg8000.native`, inspects the real rows, and gives a crisp, factual answer.
- **Privacy & Safety Constraints**:
  - All outgoing prompts, contexts, and query results pass through `sanitize_text()`, which strictly strips any home directories or user identifiers.
  - Query executor permits only `SELECT` statements and enforces `LIMIT <= 15`.

### API Endpoints
- `GET /api/v1/ai/status`: Verifies Vertex AI connectivity, region (`global`), and model availability.
- `GET /api/v1/ai/stocks/{symbol}/context`: Returns the raw and formatted ground-truth snapshot for auditability.
- `POST /api/v1/ai/chat`: Non-streaming conversation endpoint.
- `POST /api/v1/ai/chat/stream`: Real-time Server-Sent Events (SSE) word-by-word streaming endpoint.

### Frontend Components
- **Global Page**: [`apps/web/app/ai/page.tsx`](file:///Users/sandeepjadhav/Desktop/stock-analyst/apps/web/app/ai/page.tsx) with interactive stock switcher and prompt chips.
- **Chat UI**: [`apps/web/components/AiAnalystChat.tsx`](file:///Users/sandeepjadhav/Desktop/stock-analyst/apps/web/components/AiAnalystChat.tsx) with streaming tokens, markdown renderer, and ground-truth inspector drawer.
- **Embedded Stock Tab**: `⚡ Ask AI` integrated into [`apps/web/components/StockPageClient.tsx`](file:///Users/sandeepjadhav/Desktop/stock-analyst/apps/web/components/StockPageClient.tsx) on `/stocks/[symbol]#ai`.

