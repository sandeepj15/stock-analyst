# SignalForge Database Dump & Restore Guide

This directory contains the production database dump of **SignalForge**, capturing the complete universe of 1,509 active Indian equities, historical price candles, 14-quarter financial results (including Q2 FY27 / Sep 2026 earnings), Smart Money Flow patterns, and multi-factor Research Scores.

---

## Dump Overview

* **File**: `signalforge_backup_20261023.dump`
* **Format**: PostgreSQL Custom Compressed Archive (`-Fc`, `gzip`)
* **Compressed File Size**: ~167 MB
* **Uncompressed Database Size**: ~1.05 GB
* **Target PostgreSQL Version**: 16.x (compatible with PostgreSQL 14+)
* **Database / User**: `signalforge` / `signalforge`

---

## Included Tables & Data

1. **`instruments`**: 1,509 active NSE/BSE equities with sector classifications, exchanges, and Screener logo URLs.
2. **`fundamental_snapshots`**: 14 quarters of normalized financial snapshots (Revenue, EBITDA, EBIT, PAT, EPS, Interest Expense), including newly declared **Q2 FY27 (September 2026)** quarterly earnings.
3. **`institutional_holdings`**: **1,507 Smart Money Flow records** detailing FII, DII, Promoter, and retail shareholder QoQ & YoY changes.
4. **`ohlcv_daily`**: Daily historical candle data (Open, High, Low, Close, Volume) across all universe instruments.
5. **`research_scores` & `evidence_items`**: 7-component evidence synthesis composite scores (0–100), confidence ratings, and dynamic bull/bear case interpretations.
6. **`market_regimes`**: Daily regime classifications (`BEARISH_TREND` / `BULLISH_TREND`), 200 DMA breadth, and rolling volatility.
7. **`momentum_scans` & `vcp_scans`**: Technical momentum and Volatility Contraction Pattern (VCP) breakout scans.
8. **`ai_alpha_picks`**: Curated high-conviction AI stock pick portfolios.
9. **`structured_provider_data` & `raw_provider_scrapes`**: Silver (parsed JSON) and Bronze (raw scrape HTML) provider layers.

---

## How to Restore

### Option 1: Restoring into Docker Compose (Recommended)

If you are running SignalForge with the default `docker compose`:

```bash
# 1. Ensure the postgres container is running
docker compose up -d postgres

# 2. Copy the dump file into the postgres container
docker compose cp db_dumps/signalforge_backup_20261023.dump postgres:/tmp/signalforge.dump

# 3. Restore the database (drops existing objects if any, creates fresh schema and tables)
docker compose exec -T postgres pg_restore -U signalforge -d signalforge --clean --if-exists /tmp/signalforge.dump

# 4. Clean up temporary file inside container
docker compose exec -T postgres rm -f /tmp/signalforge.dump

# 5. Flush Redis cache so the frontend queries fresh data immediately
docker compose exec redis redis-cli flushall
```

---

### Option 2: Restoring into a Local PostgreSQL Server

If running PostgreSQL directly on your host machine:

```bash
# 1. Create the database and user if they do not already exist
psql -U postgres -c "CREATE USER signalforge WITH PASSWORD 'signalforge';"
psql -U postgres -c "CREATE DATABASE signalforge OWNER signalforge;"

# 2. Restore using pg_restore
pg_restore -U signalforge -h localhost -p 5432 -d signalforge --clean --if-exists db_dumps/signalforge_backup_20261023.dump
```

---

## Verification after Restore

Run the following query to verify all records are restored properly:

```bash
docker compose exec postgres psql -U signalforge -d signalforge -c "
SELECT 
    COUNT(DISTINCT i.id) as total_active_equities,
    COUNT(DISTINCT CASE WHEN fs.period_end >= '2026-09-30' THEN fs.instrument_id END) as q2_stocks,
    COUNT(DISTINCT ih.instrument_id) as holdings_tracked
FROM instruments i
LEFT JOIN fundamental_snapshots fs ON fs.instrument_id = i.id AND fs.period_type = 'Q'
LEFT JOIN institutional_holdings ih ON ih.instrument_id = i.id
WHERE i.active = true AND i.instrument_type = 'EQUITY';
"
```

Expected output:
* `total_active_equities`: **1509**
* `q2_stocks`: **160**
* `holdings_tracked`: **1507**
