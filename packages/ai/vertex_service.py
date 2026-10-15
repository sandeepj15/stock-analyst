"""Vertex AI Gemini integration for SignalForge.

Uses Google Cloud Vertex AI (location: global) with Gemini 2.5 Flash.
Strictly sanitizes all input prompts to ensure no local user paths
(specifically containing username or sandeep) are transmitted.
Enforces compact, high-signal data snapshots to minimize token consumption.
Equips the model with a read-only PostgreSQL query tool for real-time
quantitative screening and analysis.
"""
import json
import logging
import os
import re
from typing import Any, AsyncGenerator
from urllib.parse import urlparse

import pg8000.native
from google import genai
from google.genai import types
from google.oauth2 import service_account
from sqlalchemy import text

from packages.common.config import get_settings
from packages.common.db import get_engine

logger = logging.getLogger(__name__)

# Strict regex to strip any user home directories or usernames matching sandeep
_PATH_SANITIZER_RE = re.compile(r"/Users/[^\s'\"/]+", re.IGNORECASE)
_SANDEEP_RE = re.compile(r"sandeep[a-z0-9_-]*", re.IGNORECASE)


def sanitize_text(content: str) -> str:
    """Strictly strips home directories and user identifiers from all outgoing text."""
    if not content:
        return ""
    text_clean = _PATH_SANITIZER_RE.sub("~", content)
    text_clean = _SANDEEP_RE.sub("analyst", text_clean)
    return text_clean


def get_vertex_client() -> genai.Client:
    """Initializes and returns an authenticated Vertex AI Client."""
    settings = get_settings()

    # Determine credentials file path
    key_path = None
    candidates = [
        os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"),
        settings.GOOGLE_APPLICATION_CREDENTIALS,
        "/app/secrets/vertex-ai-key.json",
        "secrets/vertex-ai-key.json",
        os.path.expanduser("~/.gemini/antigravity-cli/vertex-ai-key.json"),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            key_path = c
            break

    location = settings.VERTEX_AI_LOCATION or "global"
    project_id = settings.VERTEX_PROJECT_ID or "onboarding-bot-458509"

    if key_path:
        creds = service_account.Credentials.from_service_account_file(
            key_path,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        project_id = creds.project_id or project_id
        return genai.Client(
            vertexai=True,
            project=project_id,
            location=location,
            credentials=creds,
        )

    # Fallback to default application credentials in environment
    return genai.Client(
        vertexai=True,
        project=project_id,
        location=location,
    )


def execute_safe_db_query_sync(sql_query: str) -> str:
    """Executes a strictly read-only SELECT query against PostgreSQL using pg8000.

    Safety:
    - Must start with SELECT.
    - Rejects any DDL/DML mutation keywords.
    - Enforces LIMIT <= 15.
    - Sanitizes result output.
    """
    clean_q = sql_query.strip().rstrip(";")
    if not clean_q.upper().startswith("SELECT"):
        return json.dumps({"error": "Only SELECT queries are permitted."})

    forbidden_keywords = [
        "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE",
        "EXECUTE", "CREATE", "GRANT", "REVOKE", "COPY"
    ]
    for kw in forbidden_keywords:
        if re.search(r"\b" + kw + r"\b", clean_q, re.IGNORECASE):
            return json.dumps({"error": f"Mutation keyword '{kw}' is strictly forbidden."})

    if "LIMIT" not in clean_q.upper():
        clean_q += " LIMIT 15"

    logger.info(f"AI Tool executing SQL: {clean_q}")
    settings = get_settings()
    url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    parsed = urlparse(url)

    try:
        conn = pg8000.native.Connection(
            user=parsed.username or "signalforge",
            host=parsed.hostname or "postgres",
            port=parsed.port or 5432,
            password=parsed.password or "signalforge",
            database=parsed.path.lstrip("/") or "signalforge",
        )
        try:
            results = conn.run(clean_q)
            col_names = (
                [c["name"] for c in conn.columns]
                if hasattr(conn, "columns") and conn.columns
                else []
            )
            dict_rows = []
            for r in results[:15]:
                row_dict = {}
                for col_name, val in zip(col_names, r):
                    if isinstance(val, (dict, list)):
                        val_str = json.dumps(val, default=str)
                        if len(val_str) > 300:
                            row_dict[col_name] = val_str[:300] + "... (truncated)"
                        else:
                            row_dict[col_name] = val
                    elif isinstance(val, str) and len(val) > 300:
                        row_dict[col_name] = val[:300] + "... (truncated)"
                    else:
                        row_dict[col_name] = val
                dict_rows.append(row_dict)

            json_res = json.dumps(dict_rows, default=str)
            if len(json_res) > 6000:
                json_res = json_res[:6000] + "... (truncated for token efficiency)"
            return sanitize_text(json_res)
        finally:
            conn.close()
    except Exception as exc:
        logger.warning(f"Database query error from AI tool: {exc} | Query was: {clean_q}")
        return json.dumps({"error": f"SQL Error: {str(exc)}. Please adjust query and try again."})


async def build_compact_stock_snapshot(symbol: str) -> dict[str, Any] | None:
    """Fetches and builds a token-dense (~350 words) ground-truth summary for a stock."""
    sym = symbol.strip().upper()
    engine = get_engine()

    query = text("""
        SELECT 
            i.id,
            i.symbol,
            i.company_name,
            i.sector,
            i.industry,
            i.description,
            i.ai_summary,
            rs.score AS research_score,
            rs.confidence AS research_confidence,
            rs.bull_case,
            rs.bear_case,
            ms.passed AS stage2_passed,
            ms.conditions AS stage2_conditions,
            ms.rs_rank AS momentum_rs_rank,
            ms.distance_from_52w_high_pct,
            ae.target_mean_price,
            ae.target_high_price,
            ae.target_low_price,
            ae.recommendation_key,
            ae.number_of_analyst_opinions,
            spd.data AS structured_data,
            fs.eps AS fundamental_eps,
            fs.pat AS fundamental_pat,
            fs.revenue AS fundamental_revenue,
            fs.equity AS fundamental_equity,
            fs.total_debt AS fundamental_debt,
            fs.ebit AS fundamental_ebit,
            fs.shares_outstanding AS fundamental_shares
        FROM instruments i
        LEFT JOIN LATERAL (
            SELECT score, confidence, bull_case, bear_case 
            FROM research_scores 
            WHERE instrument_id = i.id 
            ORDER BY computed_at DESC 
            LIMIT 1
        ) rs ON TRUE
        LEFT JOIN LATERAL (
            SELECT passed, conditions, rs_rank, distance_from_52w_high_pct 
            FROM momentum_scans 
            WHERE instrument_id = i.id 
            ORDER BY scan_date DESC 
            LIMIT 1
        ) ms ON TRUE
        LEFT JOIN LATERAL (
            SELECT target_mean_price, target_high_price, target_low_price, recommendation_key, number_of_analyst_opinions 
            FROM analyst_estimates 
            WHERE instrument_id = i.id 
            ORDER BY ingested_at DESC 
            LIMIT 1
        ) ae ON TRUE
        LEFT JOIN LATERAL (
            SELECT eps, pat, revenue, equity, total_debt, ebit, shares_outstanding 
            FROM fundamental_snapshots 
            WHERE instrument_id = i.id AND period_type != 'Q'
            ORDER BY period_end DESC 
            LIMIT 1
        ) fs ON TRUE
        LEFT JOIN LATERAL (
            SELECT data 
            FROM structured_provider_data 
            WHERE instrument_id = i.id 
            ORDER BY parsed_at DESC 
            LIMIT 1
        ) spd ON TRUE
        WHERE i.symbol = :symbol AND i.active = true
        LIMIT 1;
    """)

    price_query = text("""
        SELECT close, volume, trading_date
        FROM ohlcv_daily o
        JOIN instruments i ON o.instrument_id = i.id
        WHERE i.symbol = :symbol
        ORDER BY trading_date DESC
        LIMIT 2;
    """)

    async with engine.connect() as conn:
        res = await conn.execute(query, {"symbol": sym})
        row = res.mappings().first()
        if not row:
            return None

        price_res = await conn.execute(price_query, {"symbol": sym})
        prices = price_res.mappings().fetchall()

    curr_price = float(prices[0]["close"]) if prices else None
    prev_price = float(prices[1]["close"]) if len(prices) > 1 else None
    day_change_pct = (
        round(((curr_price - prev_price) / prev_price) * 100, 2)
        if (curr_price and prev_price)
        else None
    )

    spd = row.get("structured_data") or {}
    ratios = spd.get("ratios") or {}
    quarters_raw = spd.get("quarters") or spd.get("quarterly_results") or {}
    shareholding_raw = spd.get("shareholding") or {}

    # Derived P/E from annual reported EPS
    calculated_pe = None
    if curr_price and row.get("fundamental_eps") and float(row["fundamental_eps"]) > 0:
        calculated_pe = round(curr_price / float(row["fundamental_eps"]), 2)
    elif ratios.get("Stock P/E"):
        try:
            calculated_pe = float(str(ratios.get("Stock P/E")).replace(",", ""))
        except Exception:
            pass

    # Derived ROE (%) = Annual PAT / Equity * 100
    roe_val = None
    if row.get("fundamental_equity") and row.get("fundamental_pat"):
        try:
            eq = float(row["fundamental_equity"])
            pat = float(row["fundamental_pat"])
            if eq > 0:
                roe_val = round((pat / eq) * 100, 1)
        except Exception:
            pass
    if roe_val is None and ratios.get("ROE"):
        try:
            roe_val = float(str(ratios.get("ROE")).replace("%", ""))
        except Exception:
            pass

    # Derived ROCE (%) = Annual EBIT / (Equity + Debt) * 100
    roce_val = None
    if row.get("fundamental_equity") and row.get("fundamental_ebit"):
        try:
            eq = float(row["fundamental_equity"])
            debt = float(row["fundamental_debt"] or 0)
            ebit = float(row["fundamental_ebit"])
            if (eq + debt) > 0:
                roce_val = round((ebit / (eq + debt)) * 100, 1)
        except Exception:
            pass
    if roce_val is None and ratios.get("ROCE"):
        try:
            roce_val = float(str(ratios.get("ROCE")).replace("%", ""))
        except Exception:
            pass

    # Derived Market Cap (₹ Cr) = shares * price
    mcap_cr = None
    if curr_price and row.get("fundamental_shares"):
        try:
            sh = float(row["fundamental_shares"])
            if sh > 0:
                mcap_cr = round((sh * curr_price) / 1e7, 1)
        except Exception:
            pass
    if mcap_cr is None and ratios.get("Market Cap"):
        try:
            mcap_cr = float(str(ratios.get("Market Cap")).replace(",", ""))
        except Exception:
            pass

    # Debt to Equity = Debt / Equity
    de_val = None
    if row.get("fundamental_equity") and row.get("fundamental_debt") is not None:
        try:
            eq = float(row["fundamental_equity"])
            debt = float(row["fundamental_debt"])
            if eq > 0:
                de_val = round(debt / eq, 2)
        except Exception:
            pass

    pat_cr = (
        f"₹{round(float(row['fundamental_pat']) / 1e7, 1):,} Cr"
        if row.get("fundamental_pat") is not None
        else "N/A"
    )
    rev_cr = (
        f"₹{round(float(row['fundamental_revenue']) / 1e7, 1):,} Cr"
        if row.get("fundamental_revenue") is not None
        else "N/A"
    )
    eps_str = (
        f"₹{float(row['fundamental_eps']):.2f}"
        if row.get("fundamental_eps") is not None
        else "N/A"
    )

    # Compact quarter summary (last 3 quarters)
    recent_q = []
    if isinstance(quarters_raw, dict):
        sales_dict = quarters_raw.get("Sales") or {}
        pat_dict = quarters_raw.get("Net Profit") or {}
        all_periods = list(sales_dict.keys())
        for p in all_periods[-3:]:
            s_val = sales_dict.get(p, "N/A")
            p_val = pat_dict.get(p, "N/A")
            recent_q.append(f"{p}: Sales ₹{s_val} Cr, PAT ₹{p_val} Cr")
    elif isinstance(quarters_raw, list):
        for q in quarters_raw[-3:]:
            q_label = q.get("quarter")
            sales = q.get("sales")
            pat = q.get("net_profit")
            recent_q.append(f"{q_label}: Sales ₹{sales} Cr, PAT ₹{pat} Cr")

    # Compact shareholding (latest)
    prom_val, fii_val, dii_val, pub_val = "N/A", "N/A", "N/A", "N/A"
    if isinstance(shareholding_raw, dict):
        prom_dict = shareholding_raw.get("Promoters") or {}
        fii_dict = shareholding_raw.get("FIIs") or {}
        dii_dict = shareholding_raw.get("DIIs") or {}
        pub_dict = shareholding_raw.get("Public") or {}
        if prom_dict:
            latest_k = list(prom_dict.keys())[-1]
            prom_val = str(prom_dict.get(latest_k, "N/A"))
            fii_val = str(fii_dict.get(latest_k, "N/A"))
            dii_val = str(dii_dict.get(latest_k, "N/A"))
            pub_val = str(pub_dict.get(latest_k, "N/A"))
    elif isinstance(shareholding_raw, list) and shareholding_raw:
        sh_latest = shareholding_raw[-1]
        prom_val = f"{sh_latest.get('promoters', 'N/A')}%"
        fii_val = f"{sh_latest.get('fii', 'N/A')}%"
        dii_val = f"{sh_latest.get('dii', 'N/A')}%"
        pub_val = f"{sh_latest.get('public', 'N/A')}%"

    # Target upside
    upside_pct = None
    target_mean = (
        float(row["target_mean_price"]) if row["target_mean_price"] is not None else None
    )
    if curr_price and target_mean:
        upside_pct = round(((target_mean - curr_price) / curr_price) * 100, 1)

    conf_val = float(row["research_confidence"]) if row["research_confidence"] is not None else None
    conf_str = (f"{conf_val:.0f}%" if conf_val > 1.0 else f"{conf_val:.0%}") if conf_val is not None else "N/A"

    curr_price_str = f"₹{curr_price:,.2f}" if curr_price is not None else "N/A"
    day_change_str = f"{day_change_pct:+.2f}%" if day_change_pct is not None else "0.0%"
    mcap_str = f"₹{mcap_cr:,.1f} Cr" if mcap_cr is not None else "N/A"
    pe_str = f"{calculated_pe:.2f}" if calculated_pe is not None else str(ratios.get('Stock P/E', 'N/A'))
    roe_str = f"{roe_val:.1f}%" if roe_val is not None else "N/A"
    roce_str = f"{roce_val:.1f}%" if roce_val is not None else "N/A"
    de_str = f"{de_val:.2f}" if de_val is not None else "N/A"

    score_val = float(row['research_score']) if row.get('research_score') is not None else None
    score_str = f"{score_val:.1f}/100" if score_val is not None else "N/A"

    dist_high_val = float(row['distance_from_52w_high_pct']) if row.get('distance_from_52w_high_pct') is not None else None
    dist_high_str = f"{dist_high_val:.1f}%" if dist_high_val is not None else "N/A"

    if target_mean is not None and upside_pct is not None:
        target_str = f"₹{target_mean:,.2f} ({upside_pct:+.1f}%)"
    elif target_mean is not None:
        target_str = f"₹{target_mean:,.2f}"
    else:
        target_str = "No consensus"

    snapshot_text = f"""
### Live Ground-Truth Snapshot: {row['symbol']} ({row['company_name']})
- **Sector / Industry**: {row['sector'] or 'N/A'} / {row['industry'] or 'N/A'}
- **Current Price**: {curr_price_str} ({day_change_str})
- **Valuation & Fundamentals**: Stock P/E: {pe_str} | Market Cap: {mcap_str} | EPS: {eps_str} | Annual PAT: {pat_cr} | Annual Revenue: {rev_cr}
- **Profitability & Quality**: ROE: {roe_str} | ROCE: {roce_str} | Debt-to-Equity: {de_str}
- **Growth (3Y)**: Sales Growth: {ratios.get('Sales growth 3Years', 'N/A')}% | Profit Growth: {ratios.get('Profit growth 3Years', 'N/A')}%
- **Research Strength Score**: {score_str} ({conf_str} confidence)
- **Minervini Stage 2 Scan**: {"STAGE 2 PASS" if row.get('stage2_passed') else "STAGE 2 FAIL"} (RS Rank: {row.get('momentum_rs_rank') or 'N/A'}/100, {dist_high_str} off 52w High)
- **Analyst 1Y Target**: {target_str} (Rating: {row.get('recommendation_key') or 'N/A'}, {row.get('number_of_analyst_opinions') or 0} analysts)
- **Recent Quarters**: {"; ".join(recent_q) if recent_q else "N/A"}
- **Shareholding**: Promoter {prom_val}, FII {fii_val}, DII {dii_val}, Public {pub_val}
- **Company Profile**: {sanitize_text(row['ai_summary'] or row['description'] or '')[:300]}
""".strip()

    return {
        "symbol": row["symbol"],
        "company_name": row["company_name"],
        "price": curr_price,
        "day_change_pct": day_change_pct,
        "formatted_text": sanitize_text(snapshot_text),
        "raw": {
            "symbol": row["symbol"],
            "pe": calculated_pe or ratios.get("Stock P/E"),
            "roce": roce_val,
            "roe": roe_val,
            "market_cap_cr": mcap_cr,
            "debt_to_equity": de_val,
            "research_score": float(row["research_score"]) if row["research_score"] else None,
            "stage2_passed": row["stage2_passed"],
        },
    }


SYSTEM_PROMPT = """You are the SignalForge Senior Quantitative & Fundamental Equity Analyst AI.
Your role is to give crisp, accurate, institutional-grade financial analysis.

Key Principles:
1. Ground Truth First: Always prioritize exact factual numbers from the provided stock snapshot or the database. Never make up or hallucinate P/E, revenue, Piotroski, or price numbers.
2. Direct & Crisp: Keep responses concise, objective, and structured with bold highlights and bullet points. Avoid filler introductions and verbose disclaimers.
3. Database Querying: If the user asks cross-stock, screening, or comparative queries (e.g., 'which stock has the lowest PE?', 'top 5 tech stocks with Stage 2 pass?', 'which stock is the best in technicals and fundamentals'), invoke the `query_database` tool.

Database Schema & Available Views:
- `v_stock_summary`: Master consolidated view joining all 1,510 stocks with real-time technicals, research scores, fundamentals, home page screener metrics, and analyst ratings. THIS IS YOUR PRIMARY TABLE FOR SCREENING AND COMPARISON.
  Columns in `v_stock_summary`:
  - `symbol` VARCHAR: Uppercase NSE ticker (e.g. 'WIPRO', 'CHENNPETRO', 'KTKBANK', 'TCS', 'GAEL')
  - `company_name` VARCHAR: Full corporate name
  - `sector` VARCHAR, `industry` VARCHAR
  - `current_price` NUMERIC: Latest closing price in ₹
  - `research_score` NUMERIC: Institutional multi-factor research strength score / "Score" (0 to 100)
  - `research_confidence` NUMERIC: Quantitative model confidence (0 to 1.0, e.g. 0.91 = 91%)
  - `stage2_passed` BOOLEAN: True if passing Minervini Stage 2 uptrend criteria ("Stage 2")
  - `momentum_rs_rank` NUMERIC: 1-year Relative Strength percentile rank (0 to 100)
  - `distance_from_52w_high_pct` NUMERIC: Percentage off 52-week high (e.g. -5.2%)
  - `is_vcp_setup` BOOLEAN: True if Volatility Contraction Pattern is formed ("VCP")
  - `day_change_pct` NUMERIC: Daily percentage price change ("Day %")
  - `return_1m_pct` NUMERIC: 1-Month / 21-day percentage return ("1M %")
  - `return_1y_pct` NUMERIC: 1-Year / 252-day percentage return ("1Y %")
  - `rev_growth_yoy_pct` NUMERIC: YoY quarterly Revenue growth % ("Rev YoY")
  - `pat_growth_yoy_pct` NUMERIC: YoY quarterly PAT growth % ("PAT YoY")
  - `ml_forecast_5d_pct` NUMERIC: 5-Day machine learning price trajectory forecast % ("5D ML %")
  - `pe_ratio` NUMERIC: Price-to-Earnings ratio (calculated from close / annual EPS)
  - `eps` NUMERIC: Annual Earnings Per Share in ₹
  - `market_cap_cr` NUMERIC: Market Capitalization in ₹ Crores (e.g. 1283.4 for NRAIL)
  - `annual_revenue` NUMERIC: Annual revenue in ₹
  - `annual_pat` NUMERIC: Annual Net Profit After Tax in ₹
  - `roe_pct` NUMERIC: Return on Equity percentage (e.g. 5.36% for NRAIL)
  - `roce_pct` NUMERIC: Return on Capital Employed percentage (e.g. 7.22% for NRAIL)
  - `debt_to_equity` NUMERIC: Debt-to-Equity ratio (e.g. 1.01 for NRAIL)
  - `target_mean_price` NUMERIC: 1-year analyst consensus target price in ₹
  - `analyst_upside_pct` NUMERIC: Percentage upside to analyst target ("Target")
  - `analyst_rating` VARCHAR: Analyst consensus rating (e.g. 'buy', 'strong_buy', 'hold')

Query Strategy for 'Best Stock in terms of Screener Metrics / Technicals & Fundamentals':
- Query `v_stock_summary` with:
  `SELECT symbol, company_name, research_score, stage2_passed, is_vcp_setup, day_change_pct, return_1m_pct, return_1y_pct, rev_growth_yoy_pct, pat_growth_yoy_pct, analyst_upside_pct, ml_forecast_5d_pct, pe_ratio FROM v_stock_summary WHERE stage2_passed = true ORDER BY research_score DESC NULLS LAST LIMIT 10;`
- Compare top contenders objectively.
- Output Format: Always format cross-stock screener comparisons with a clean Markdown Table showing the exact numbers for each contender (Ticker, Name, Score, Stage 2, VCP, Day %, 1M %, 1Y %, Rev YoY, PAT YoY, Target, 5D ML %, P/E), followed by structured analysis of the top picks.

Other Tables (for deep historical dives only):
- `instruments(id, symbol, company_name, sector, industry, active)`: Primary key is `id` (UUID).
- `structured_provider_data(id, instrument_id, data)`: Contains large JSON dumps. DO NOT SELECT whole `spd.data` for multiple stocks. Prefer `v_stock_summary`.

Direct Synthesis Rule:
- When an 'Active Stock Context' snapshot is already provided above for a stock (e.g. NRAIL), all core valuation, momentum, Stage 2, research scores, ROE, ROCE, and P/E are ALREADY present in the snapshot. Rely on and analyze that snapshot directly without issuing redundant queries unless cross-stock screening is required.

Privacy Rule: Never mention local file paths or private usernames.
"""


def query_database(sql_query: str) -> str:
    """Executes a read-only SELECT SQL query on PostgreSQL to find, filter, or rank stocks.

    Primary View:
    - v_stock_summary: The pre-joined master view for all 1,510 stocks.
      Columns: symbol, company_name, sector, industry, current_price, research_score, research_confidence, stage2_passed, momentum_rs_rank, distance_from_52w_high_pct, is_vcp_setup, day_change_pct, return_1m_pct, return_1y_pct, rev_growth_yoy_pct, pat_growth_yoy_pct, ml_forecast_5d_pct, pe_ratio, eps, market_cap_cr, annual_revenue, annual_pat, roe_pct, roce_pct, debt_to_equity, target_mean_price, analyst_upside_pct, analyst_rating.

    Query Tips:
    - Symbols are always uppercase NSE tickers (e.g., 'WIPRO', 'CHENNPETRO', 'NRAIL', 'KTKBANK', 'GAEL').
    - For top stocks combining all home screener metrics:
      SELECT symbol, company_name, research_score, stage2_passed, is_vcp_setup, day_change_pct, return_1m_pct, return_1y_pct, rev_growth_yoy_pct, pat_growth_yoy_pct, analyst_upside_pct, ml_forecast_5d_pct FROM v_stock_summary WHERE stage2_passed = true ORDER BY research_score DESC LIMIT 5;
    - Always use SELECT. Results are capped at 15 rows.
    """
    return execute_safe_db_query_sync(sql_query)


def format_chat_history(history: list[dict[str, str]] | None) -> list[types.Content] | None:
    """Formats conversation history into google.genai types.Content objects."""
    if not history:
        return None
    chat_history: list[types.Content] = []
    for h in history[:-1]:
        role = h.get("role", "user")
        content = sanitize_text(h.get("content", ""))
        if not content:
            continue
        model_role = "model" if role in ("assistant", "model") else "user"
        chat_history.append(
            types.Content(
                role=model_role,
                parts=[types.Part.from_text(text=content)],
            )
        )
    return chat_history if chat_history else None


class VertexAiAnalystService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.model_name = self.settings.VERTEX_AI_MODEL or "gemini-2.5-flash"

    async def get_status(self) -> dict[str, Any]:
        """Checks connectivity to Vertex AI Gemini in the global location."""
        try:
            client = get_vertex_client()
            models_list = []
            for m in client.models.list():
                if "gemini" in m.name.lower():
                    clean_name = m.name.split("/")[-1]
                    models_list.append(clean_name)
            return {
                "connected": True,
                "provider": "vertex_ai",
                "location": self.settings.VERTEX_AI_LOCATION or "global",
                "model": self.model_name,
                "models": models_list[:12],
                "model_ready": True,
            }
        except Exception as exc:
            logger.error(f"Vertex AI status check error: {exc}")
            return {
                "connected": False,
                "provider": "vertex_ai",
                "location": self.settings.VERTEX_AI_LOCATION or "global",
                "model": self.model_name,
                "models": [],
                "model_ready": False,
                "error": sanitize_text(str(exc)),
            }

    async def chat(
        self,
        message: str,
        symbol: str | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Performs non-streaming conversational analysis with Vertex AI Gemini."""
        client = get_vertex_client()
        sanitized_msg = sanitize_text(message)

        # Auto-detect symbol if not explicitly provided
        snapshot = None
        context_str = ""
        active_symbol = symbol
        if not active_symbol:
            candidates = re.findall(r"\b[A-Z]{3,12}\b", message)
            stop_words = {"THE", "FOR", "AND", "WITH", "THIS", "STOCK", "DATA", "WHAT", "SHOW", "BEST", "CHECK", "LIKE", "PAST"}
            for c in candidates:
                if c not in stop_words:
                    test_snap = await build_compact_stock_snapshot(c)
                    if test_snap:
                        active_symbol = c
                        snapshot = test_snap
                        context_str = f"\n\nActive Stock Context ({active_symbol}):\n{snapshot['formatted_text']}\n"
                        break
        elif active_symbol:
            snapshot = await build_compact_stock_snapshot(active_symbol)
            if snapshot:
                context_str = f"\n\nActive Stock Context ({active_symbol}):\n{snapshot['formatted_text']}\n"

        system_instruction = sanitize_text(SYSTEM_PROMPT + context_str)
        chat_history = format_chat_history(history)

        chat_session = client.chats.create(
            model=self.model_name,
            config=types.GenerateContentConfig(
                tools=[query_database],
                temperature=0.2,
                system_instruction=system_instruction,
            ),
            history=chat_history,
        )

        response = chat_session.send_message(sanitized_msg)
        response_text = sanitize_text(response.text or "")

        return {
            "symbol": active_symbol,
            "response": response_text,
            "model": self.model_name,
            "context_available": snapshot is not None,
            "context_preview": snapshot["formatted_text"] if snapshot else None,
            "raw_context": snapshot["raw"] if snapshot else None,
        }

    async def chat_stream(
        self,
        message: str,
        symbol: str | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> AsyncGenerator[str, None]:
        """Streams Gemini responses token-by-token formatted as Server-Sent Events (SSE)."""
        client = get_vertex_client()
        sanitized_msg = sanitize_text(message)

        # Auto-detect symbol if not explicitly provided
        snapshot = None
        context_str = ""
        active_symbol = symbol
        if not active_symbol:
            candidates = re.findall(r"\b[A-Z]{3,12}\b", message)
            stop_words = {"THE", "FOR", "AND", "WITH", "THIS", "STOCK", "DATA", "WHAT", "SHOW", "BEST", "CHECK", "LIKE", "PAST"}
            for c in candidates:
                if c not in stop_words:
                    test_snap = await build_compact_stock_snapshot(c)
                    if test_snap:
                        active_symbol = c
                        snapshot = test_snap
                        context_str = f"\n\nActive Stock Context ({active_symbol}):\n{snapshot['formatted_text']}\n"
                        break
        elif active_symbol:
            snapshot = await build_compact_stock_snapshot(active_symbol)
            if snapshot:
                context_str = f"\n\nActive Stock Context ({active_symbol}):\n{snapshot['formatted_text']}\n"

        system_instruction = sanitize_text(SYSTEM_PROMPT + context_str)

        # Emit initial metadata event
        meta_payload = {
            "type": "meta",
            "model": self.model_name,
            "symbol": active_symbol,
            "context_available": snapshot is not None,
            "context_preview": snapshot["formatted_text"] if snapshot else None,
        }
        yield f"data: {json.dumps(meta_payload)}\n\n"
        yield f"data: {json.dumps({'type': 'status', 'status': 'Analyzing query & scanning database...'})}\n\n"

        try:
            chat_history = format_chat_history(history)
            chat_session = client.chats.create(
                model=self.model_name,
                config=types.GenerateContentConfig(
                    tools=[query_database],
                    temperature=0.2,
                    system_instruction=system_instruction,
                ),
                history=chat_history,
            )

            has_tokens = False
            for chunk in chat_session.send_message_stream(sanitized_msg):
                if hasattr(chunk, "function_calls") and chunk.function_calls:
                    yield f"data: {json.dumps({'type': 'status', 'status': 'Executing database query on SignalForge...'})}\n\n"
                else:
                    yield ": keep-alive\n\n"

                chunk_text = chunk.text
                if chunk_text:
                    has_tokens = True
                    token_payload = {
                        "type": "token",
                        "content": sanitize_text(chunk_text),
                    }
                    yield f"data: {json.dumps(token_payload)}\n\n"

            # If no tokens were streamed (e.g. AFC consumed tool response without yielding text),
            # fall back to prompt for crisp summary
            if not has_tokens:
                logger.info("Stream produced 0 tokens, falling back to complete generation")
                yield f"data: {json.dumps({'type': 'status', 'status': 'Synthesizing final analysis...'})}\n\n"
                direct_resp = chat_session.send_message("Please provide a crisp structured summary of your findings from the database query above.")
                if direct_resp.text:
                    token_payload = {
                        "type": "token",
                        "content": sanitize_text(direct_resp.text),
                    }
                    yield f"data: {json.dumps(token_payload)}\n\n"

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as exc:
            logger.error(f"Error in chat_stream: {exc}", exc_info=True)
            err_payload = {"type": "error", "error": sanitize_text(str(exc))}
            yield f"data: {json.dumps(err_payload)}\n\n"


vertex_service = VertexAiAnalystService()
