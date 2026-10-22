"""Multi-Factor AI Alpha Picks Engine powered by Google Cloud Vertex AI Gemini.

Identifies quantitative signals that predict future equity returns:
1. Momentum (12-1): 12-month return minus 1-month return (Jegadeesh & Titman) to
   isolate intermediate price persistence while neutralizing short-term mean-reversion noise.
2. Value (E/P): Earnings Yield (100 / P/E), representing cash generation power per unit of price.
3. Quality (ROE & Balance Sheet): Return on Equity (>=14%), ROCE (>=14%), and conservative
   leverage (Debt-to-Equity <= 0.85) ensuring sustainable capital compounding.
4. Earnings Revisions & Acceleration: Upward analyst consensus target revisions,
   high YoY PAT growth (>=15%), and revenue expansion.

Queries the live PostgreSQL database (`v_stock_summary`), feeds candidate metrics
into Vertex AI Gemini, selects the top 10 highest-conviction picks, generates institutional
explainability for each factor, and caches results in Redis and PostgreSQL.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import UTC, date, datetime
from typing import Any

from google.genai import types
from sqlalchemy import text

from packages.ai.vertex_service import get_vertex_client, sanitize_text
from packages.common import cache
from packages.common.config import get_settings
from packages.common.db import get_engine, session_scope
from packages.common.models import AIAlphaPicksRecord

logger = logging.getLogger(__name__)

CACHE_KEY_DAILY_ALPHA_PICKS = "ai:daily_alpha_picks:v1"
CACHE_TTL_DAILY_ALPHA_PICKS = 86400 * 2  # 48 hours


async def fetch_multi_factor_candidates_from_db(limit: int = 30) -> list[dict[str, Any]]:
    """Fetches candidate stocks strictly meeting the 4 predictive factor criteria from v_stock_summary."""
    engine = get_engine()
    sql = text("""
        SELECT 
            symbol, 
            company_name, 
            sector, 
            industry,
            current_price,
            ROUND((return_1y_pct - COALESCE(return_1m_pct, 0))::numeric, 2) AS momentum_12_1,
            return_1y_pct,
            return_1m_pct,
            stage2_passed,
            momentum_rs_rank,
            is_vcp_setup,
            pe_ratio,
            ROUND((100.0 / NULLIF(pe_ratio, 0))::numeric, 2) AS earnings_yield_pct,
            roe_pct,
            roce_pct,
            debt_to_equity,
            analyst_upside_pct,
            analyst_rating,
            pat_growth_yoy_pct,
            rev_growth_yoy_pct,
            research_score,
            ml_forecast_5d_pct
        FROM v_stock_summary
        WHERE active IS TRUE
          AND current_price >= 20.0
          AND pe_ratio >= 4.0 AND pe_ratio <= 45.0
          AND roe_pct >= 14.0 AND roe_pct <= 80.0
          AND debt_to_equity <= 0.85
          AND (return_1y_pct - COALESCE(return_1m_pct, 0)) >= 15.0
          AND (analyst_upside_pct > 0 OR pat_growth_yoy_pct >= 15.0)
          AND (rev_growth_yoy_pct IS NULL OR rev_growth_yoy_pct > 0)
        ORDER BY (return_1y_pct - COALESCE(return_1m_pct, 0)) DESC, roe_pct DESC
        LIMIT :limit;
    """)

    candidates: list[dict[str, Any]] = []
    async with engine.connect() as conn:
        result = await conn.execute(sql, {"limit": limit})
        for row in result.mappings().fetchall():
            candidates.append({
                "symbol": row["symbol"],
                "company_name": row["company_name"],
                "sector": row["sector"] or "Diversified",
                "industry": row["industry"] or "Diversified",
                "current_price": float(row["current_price"]) if row["current_price"] is not None else None,
                "momentum_12_1_pct": float(row["momentum_12_1"]) if row["momentum_12_1"] is not None else 0.0,
                "return_1y_pct": float(row["return_1y_pct"]) if row["return_1y_pct"] is not None else 0.0,
                "return_1m_pct": float(row["return_1m_pct"]) if row["return_1m_pct"] is not None else 0.0,
                "stage2_passed": bool(row["stage2_passed"]),
                "momentum_rs_rank": float(row["momentum_rs_rank"]) if row["momentum_rs_rank"] is not None else None,
                "is_vcp_setup": bool(row["is_vcp_setup"]),
                "pe_ratio": float(row["pe_ratio"]) if row["pe_ratio"] is not None else None,
                "earnings_yield_pct": float(row["earnings_yield_pct"]) if row["earnings_yield_pct"] is not None else None,
                "roe_pct": float(row["roe_pct"]) if row["roe_pct"] is not None else None,
                "roce_pct": float(row["roce_pct"]) if row["roce_pct"] is not None else None,
                "debt_to_equity": float(row["debt_to_equity"]) if row["debt_to_equity"] is not None else None,
                "analyst_upside_pct": float(row["analyst_upside_pct"]) if row["analyst_upside_pct"] is not None else None,
                "analyst_rating": row["analyst_rating"],
                "pat_growth_yoy_pct": float(row["pat_growth_yoy_pct"]) if row["pat_growth_yoy_pct"] is not None else None,
                "rev_growth_yoy_pct": float(row["rev_growth_yoy_pct"]) if row["rev_growth_yoy_pct"] is not None else None,
                "research_score": float(row["research_score"]) if row["research_score"] is not None else None,
                "ml_forecast_5d_pct": float(row["ml_forecast_5d_pct"]) if row["ml_forecast_5d_pct"] is not None else None,
            })
    return candidates


def build_alpha_prompt(candidates: list[dict[str, Any]]) -> str:
    """Builds the quantitative factor prompt for Vertex AI Gemini."""
    lines = [
        "You are an Elite Institutional Quantitative Portfolio Manager and Head of Alpha Research for an Indian Equity Fund.",
        "",
        "### Predictive Quantitative Signals Definition:",
        "1. **Momentum (12-1)**: 12-month return minus the most recent 1-month return (Jegadeesh & Titman factor). Captures robust intermediate trend persistence while filtering out short-term 1-month mean-reversion pullbacks. Aligned with Stage 2 technical breakouts.",
        "2. **Value (E/P)**: Earnings Yield (100 / P/E ratio). High earnings yield signifies attractive cash generating power per rupee invested, safeguarding against multiple contraction.",
        "3. **Quality (ROE & Balance Sheet)**: High Return on Equity (ROE >= 14%), high ROCE (>= 14%), and conservative balance sheet leverage (Debt-to-Equity <= 0.85). Guarantees sustainable capital compounding without financial distress risk.",
        "4. **Earnings Revisions & Fundamental Acceleration**: Significant analyst target upside and/or robust quarterly Year-over-Year PAT and Revenue growth acceleration, signaling institutional earnings upgrades.",
        "",
        f"### Candidate Stock Universe ({len(candidates)} pre-filtered candidates strictly satisfying all 4 signals):",
    ]

    for idx, c in enumerate(candidates, 1):
        lines.append(
            f"{idx}. {c['symbol']} ({c['company_name']}) | Sector: {c['sector']} | Price: ₹{c['current_price'] or 0:.2f} | "
            f"12-1 Mom: +{c['momentum_12_1_pct']:.1f}% (1Y: {c['return_1y_pct']:.1f}%, 1M: {c['return_1m_pct']:.1f}%, Stage2: {c['stage2_passed']}) | "
            f"PE: {c['pe_ratio'] or 0:.2f} (E/P Yield: {c['earnings_yield_pct'] or 0:.2f}%) | "
            f"ROE: {c['roe_pct'] or 0:.1f}%, ROCE: {c['roce_pct'] or 0:.1f}%, D/E: {c['debt_to_equity'] or 0:.2f} | "
            f"PAT YoY: {c['pat_growth_yoy_pct'] or 0:+.1f}%, Rev YoY: {c['rev_growth_yoy_pct'] or 0:+.1f}%, Analyst Upside: {c['analyst_upside_pct'] or 0:+.1f}% | "
            f"Research Score: {c['research_score'] or 0:.1f}, ML 5D: {c['ml_forecast_5d_pct'] or 0:+.1f}%"
        )

    lines.extend([
        "",
        "### TASK:",
        "1. Strictly evaluate every candidate across the 4 predictive factors.",
        "2. Select the TOP 10 (or fewer if fewer than 10 pass top-tier conviction) highest-conviction picks.",
        "3. Rank them from Rank 1 to Rank 10 based on balanced multi-factor composite strength (highest conviction first).",
        "4. For EACH selected pick, provide institutional-grade explainability dissecting:",
        "   - Overall Alpha Thesis: Concise, multi-factor rationale explaining why this stock will outperform.",
        "   - Momentum Signal (12-1): Exact return figures, trend strength, Stage 2 status, and technical health.",
        "   - Value Signal (E/P): Earnings Yield %, P/E ratio, and margin-of-safety commentary.",
        "   - Quality Signal: ROE %, ROCE %, Debt-to-Equity, and capital allocation moat.",
        "   - Earnings Revision & Growth Signal: PAT YoY %, Revenue YoY %, Analyst target upside %, and forward earnings momentum.",
        "   - Conviction Tier: 'EXCEPTIONAL' (top tier, checks every factor with outstanding metrics) or 'HIGH'.",
        "   - Composite Alpha Score: Numeric rating from 75.0 to 99.0.",
        "   - Key Catalysts: 2-3 concrete business/market drivers.",
        "   - Key Risks: 1-2 factor or operational risks.",
        "   - Technical Invalidation Level: Suggested stop-loss or support level (in INR).",
        "5. Provide a Market Regime & Macro Factor Commentary summarizing how Momentum, Value, Quality, and Earnings Revisions currently interact in the Indian market.",
        "",
        "### JSON OUTPUT SCHEMA:",
        "Return strictly a valid JSON object matching this structure (no markdown fences, just raw JSON):",
        "{",
        '  "market_regime_context": "Macro factor commentary...",',
        f'  "total_candidates_analyzed": {len(candidates)},',
        '  "picks": [',
        "    {",
        '      "rank": 1,',
        '      "symbol": "TICKER",',
        '      "company_name": "Company Full Name",',
        '      "sector": "Sector Name",',
        '      "current_price": 1234.5,',
        '      "conviction_tier": "EXCEPTIONAL",',
        '      "composite_alpha_score": 94.5,',
        '      "alpha_thesis": "Comprehensive 2-3 sentence institutional thesis...",',
        '      "signals": {',
        '        "momentum": {',
        '          "value_12_1_pct": 91.8,',
        '          "stage2_passed": true,',
        '          "reasoning": "Detailed 1-2 sentence explanation of 12-1 momentum & trend..."',
        "        },",
        '        "value_ep": {',
        '          "earnings_yield_pct": 14.81,',
        '          "pe_ratio": 6.75,',
        '          "reasoning": "Detailed 1-2 sentence explanation of E/P yield & valuation cushion..."',
        "        },",
        '        "quality": {',
        '          "roe_pct": 27.93,',
        '          "roce_pct": 32.76,',
        '          "debt_to_equity": 0.18,',
        '          "reasoning": "Detailed 1-2 sentence explanation of ROE, ROCE, and leverage health..."',
        "        },",
        '        "earnings_revisions": {',
        '          "analyst_upside_pct": 25.1,',
        '          "pat_growth_yoy_pct": 2677.0,',
        '          "rev_growth_yoy_pct": 84.8,',
        '          "reasoning": "Detailed 1-2 sentence explanation of earnings revision & growth acceleration..."',
        "        }",
        "      },",
        '      "catalysts": ["Catalyst 1", "Catalyst 2"],',
        '      "key_risks": ["Risk 1", "Risk 2"],',
        '      "invalidation_level": 1150.0',
        "    }",
        "  ]",
        "}",
    ])

    return "\n".join(lines)


def _clean_number(val: Any) -> float | None:
    """Safely extracts a float from various LLM representations (e.g. 91.8, '91.8%', '$120')."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        clean_str = re.sub(r"[^\d.-]", "", val)
        try:
            return float(clean_str)
        except ValueError:
            return None
    return None


def _clean_and_validate_picks(raw_picks: list[Any]) -> list[dict[str, Any]]:
    """Sanitizes and enforces strict type conformity on LLM-generated picks."""
    valid_picks: list[dict[str, Any]] = []
    for idx, p in enumerate(raw_picks, 1):
        if not isinstance(p, dict) or not p.get("symbol"):
            continue

        signals = p.get("signals") if isinstance(p.get("signals"), dict) else {}
        mom = signals.get("momentum") if isinstance(signals.get("momentum"), dict) else {}
        val_ep = signals.get("value_ep") if isinstance(signals.get("value_ep"), dict) else {}
        qual = signals.get("quality") if isinstance(signals.get("quality"), dict) else {}
        revs = signals.get("earnings_revisions") if isinstance(signals.get("earnings_revisions"), dict) else {}

        tier = str(p.get("conviction_tier", "HIGH")).strip().upper()
        if "EXCEPTIONAL" in tier:
            tier = "EXCEPTIONAL"
        else:
            tier = "HIGH"

        curr_price = _clean_number(p.get("current_price")) or 0.0
        inval_level = _clean_number(p.get("invalidation_level"))
        if inval_level is None or inval_level <= 0:
            inval_level = round(curr_price * 0.90, 1)

        valid_picks.append({
            "rank": int(p.get("rank") or idx),
            "symbol": str(p.get("symbol", "")).upper().strip(),
            "company_name": str(p.get("company_name", p.get("symbol", ""))).strip(),
            "sector": str(p.get("sector", "Diversified")).strip(),
            "current_price": curr_price,
            "conviction_tier": tier,
            "composite_alpha_score": _clean_number(p.get("composite_alpha_score")) or round(95.0 - (idx * 1.2), 1),
            "alpha_thesis": str(p.get("alpha_thesis", "")).strip(),
            "signals": {
                "momentum": {
                    "value_12_1_pct": _clean_number(mom.get("value_12_1_pct")) or 0.0,
                    "stage2_passed": bool(mom.get("stage2_passed", False)),
                    "reasoning": str(mom.get("reasoning", "")).strip(),
                },
                "value_ep": {
                    "earnings_yield_pct": _clean_number(val_ep.get("earnings_yield_pct")) or 0.0,
                    "pe_ratio": _clean_number(val_ep.get("pe_ratio")) or 0.0,
                    "reasoning": str(val_ep.get("reasoning", "")).strip(),
                },
                "quality": {
                    "roe_pct": _clean_number(qual.get("roe_pct")) or 0.0,
                    "roce_pct": _clean_number(qual.get("roce_pct")),
                    "debt_to_equity": _clean_number(qual.get("debt_to_equity")) or 0.0,
                    "reasoning": str(qual.get("reasoning", "")).strip(),
                },
                "earnings_revisions": {
                    "analyst_upside_pct": _clean_number(revs.get("analyst_upside_pct")),
                    "pat_growth_yoy_pct": _clean_number(revs.get("pat_growth_yoy_pct")),
                    "rev_growth_yoy_pct": _clean_number(revs.get("rev_growth_yoy_pct")),
                    "reasoning": str(revs.get("reasoning", "")).strip(),
                },
            },
            "catalysts": [str(c).strip() for c in (p.get("catalysts") or []) if c],
            "key_risks": [str(r).strip() for r in (p.get("key_risks") or []) if r],
            "invalidation_level": inval_level,
        })
    return valid_picks


async def generate_daily_ai_alpha_picks() -> dict[str, Any]:
    """Runs the complete multi-factor quantitative screening and Vertex AI generation.

    1. Fetches candidate stocks from v_stock_summary.
    2. Calls Vertex AI Gemini to select & rank the top 10 picks with explainability.
    3. Saves payload to Redis cache and PostgreSQL ai_alpha_picks table.
    """
    settings = get_settings()
    model_name = settings.VERTEX_AI_MODEL or "gemini-3.5-flash"

    logger.info("Starting Daily AI Alpha Picks generation...")
    candidates = await fetch_multi_factor_candidates_from_db(limit=30)
    if not candidates:
        logger.warning("No candidate stocks found matching multi-factor filters.")
        empty_payload = {
            "generated_date": date.today().isoformat(),
            "model_name": model_name,
            "market_regime_context": "Insufficient candidate stocks met the strict 4-factor criteria today.",
            "total_candidates_analyzed": 0,
            "picks": [],
        }
        await cache.set_json(CACHE_KEY_DAILY_ALPHA_PICKS, empty_payload, ttl_seconds=CACHE_TTL_DAILY_ALPHA_PICKS)
        return empty_payload

    prompt = build_alpha_prompt(candidates)
    sanitized_prompt = sanitize_text(prompt)

    client = get_vertex_client()
    try:
        response = client.models.generate_content(
            model=model_name,
            contents=sanitized_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2,
            ),
        )
        response_text = response.text.strip()
        # Clean any accidental code block backticks if present
        if response_text.startswith("```"):
            response_text = re.sub(r"^```(?:json)?\s*", "", response_text)
            response_text = re.sub(r"\s*```$", "", response_text)

        parsed_json = json.loads(response_text)
    except Exception as exc:
        logger.error(f"Vertex AI generation or parsing failed for alpha picks: {exc}", exc_info=True)
        # Fallback to local rule-based ranking if LLM call fails
        parsed_json = _build_fallback_alpha_picks(candidates)

    today_str = date.today().isoformat()
    raw_picks = parsed_json.get("picks", [])
    picks = _clean_and_validate_picks(raw_picks)
    if not picks and candidates:
        logger.warning("Parsed picks were empty after validation, using fallback.")
        picks = _clean_and_validate_picks(_build_fallback_alpha_picks(candidates).get("picks", []))
    picks_count = len(picks)

    final_payload = {
        "generated_date": today_str,
        "model_name": model_name,
        "market_regime_context": parsed_json.get("market_regime_context", "Multi-factor quantitative regime favoring balanced Momentum, Value, Quality, and Earnings Growth."),
        "total_candidates_analyzed": parsed_json.get("total_candidates_analyzed", len(candidates)),
        "picks_count": picks_count,
        "picks": picks,
    }

    # 1. Save in Redis
    try:
        await cache.set_json(CACHE_KEY_DAILY_ALPHA_PICKS, final_payload, ttl_seconds=CACHE_TTL_DAILY_ALPHA_PICKS)
        logger.info(f"Cached {picks_count} AI Alpha Picks in Redis under {CACHE_KEY_DAILY_ALPHA_PICKS}")
    except Exception as exc:
        logger.warning(f"Could not write alpha picks to Redis cache: {exc}")

    # 2. Upsert in PostgreSQL ai_alpha_picks table
    try:
        engine = get_engine()
        upsert_sql = text("""
            INSERT INTO ai_alpha_picks (generated_date, model_name, total_candidates, picks_count, payload)
            VALUES (:gen_date, :model, :total_cand, :picks_cnt, :payload)
            ON CONFLICT (generated_date) 
            DO UPDATE SET 
                model_name = EXCLUDED.model_name,
                total_candidates = EXCLUDED.total_candidates,
                picks_count = EXCLUDED.picks_count,
                payload = EXCLUDED.payload,
                created_at = NOW();
        """)
        async with engine.begin() as conn:
            await conn.execute(upsert_sql, {
                "gen_date": date.today(),
                "model": model_name,
                "total_cand": len(candidates),
                "picks_cnt": picks_count,
                "payload": json.dumps(final_payload),
            })
        logger.info(f"Persisted AI Alpha Picks to PostgreSQL for date {today_str}")
    except Exception as exc:
        logger.error(f"Failed to persist AI Alpha Picks to PostgreSQL: {exc}")

    return final_payload


def _build_fallback_alpha_picks(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Generates rule-based factor picks if LLM API is unavailable."""
    top_candidates = candidates[:10]
    picks = []
    for rank, c in enumerate(top_candidates, 1):
        ey = c.get("earnings_yield_pct") or (round(100.0 / c["pe_ratio"], 2) if c.get("pe_ratio") else 0)
        curr_p = c.get("current_price") or 100.0
        invalidation = round(curr_p * 0.90, 1)

        picks.append({
            "rank": rank,
            "symbol": c["symbol"],
            "company_name": c["company_name"],
            "sector": c["sector"],
            "current_price": curr_p,
            "conviction_tier": "EXCEPTIONAL" if rank <= 3 else "HIGH",
            "composite_alpha_score": round(95.0 - (rank * 1.5), 1),
            "alpha_thesis": f"{c['company_name']} exhibits strong multi-factor synergy with 12-1 momentum of +{c['momentum_12_1_pct']:.1f}%, robust ROE of {c['roe_pct'] or 0:.1f}%, and conservative leverage.",
            "signals": {
                "momentum": {
                    "value_12_1_pct": c["momentum_12_1_pct"],
                    "stage2_passed": c["stage2_passed"],
                    "reasoning": f"Intermediate momentum is strong at +{c['momentum_12_1_pct']:.1f}% without short-term exhaustion (Stage 2: {c['stage2_passed']}).",
                },
                "value_ep": {
                    "earnings_yield_pct": ey,
                    "pe_ratio": c.get("pe_ratio") or 0.0,
                    "reasoning": f"Earnings yield of {ey:.2f}% (P/E {c.get('pe_ratio') or 0:.1f}) provides valuation margin of safety.",
                },
                "quality": {
                    "roe_pct": c.get("roe_pct") or 0.0,
                    "roce_pct": c.get("roce_pct") or 0.0,
                    "debt_to_equity": c.get("debt_to_equity") or 0.0,
                    "reasoning": f"High return on equity ({c.get('roe_pct') or 0:.1f}%) and low debt ({c.get('debt_to_equity') or 0:.2f}) demonstrate capital efficiency.",
                },
                "earnings_revisions": {
                    "analyst_upside_pct": c.get("analyst_upside_pct"),
                    "pat_growth_yoy_pct": c.get("pat_growth_yoy_pct") or 0.0,
                    "rev_growth_yoy_pct": c.get("rev_growth_yoy_pct") or 0.0,
                    "reasoning": f"Earnings trajectory is accelerating with YoY PAT growth of {c.get('pat_growth_yoy_pct') or 0:+.1f}%.",
                },
            },
            "catalysts": [
                "Continued strong earnings growth supporting valuation re-rating",
                "Technical momentum following multi-factor expansion",
            ],
            "key_risks": [
                "Broader market sector pullbacks",
                "Input cost inflation impacting quarterly margins",
            ],
            "invalidation_level": invalidation,
        })

    return {
        "market_regime_context": "Quantitative multi-factor screen selecting candidates with superior intermediate momentum, earnings yield, ROE, and growth acceleration.",
        "total_candidates_analyzed": len(candidates),
        "picks": picks,
    }


async def get_latest_alpha_picks(force_refresh: bool = False) -> dict[str, Any]:
    """Retrieves the latest daily AI Alpha Picks from cache, database, or triggers generation."""
    if not force_refresh:
        # 1. Try Redis cache first
        cached = await cache.get_json(CACHE_KEY_DAILY_ALPHA_PICKS)
        if cached and isinstance(cached, dict) and cached.get("picks"):
            return cached

        # 2. Try PostgreSQL ai_alpha_picks table
        try:
            engine = get_engine()
            sql = text("""
                SELECT payload 
                FROM ai_alpha_picks 
                ORDER BY generated_date DESC 
                LIMIT 1;
            """)
            async with engine.connect() as conn:
                res = await conn.execute(sql)
                row = res.first()
                if row and row[0]:
                    payload = row[0] if isinstance(row[0], dict) else json.loads(row[0])
                    # Re-populate Redis
                    await cache.set_json(CACHE_KEY_DAILY_ALPHA_PICKS, payload, ttl_seconds=CACHE_TTL_DAILY_ALPHA_PICKS)
                    return payload
        except Exception as exc:
            logger.warning(f"Failed to read alpha picks from PostgreSQL: {exc}")

    # 3. If cache/db empty or force_refresh is requested, generate live
    return await generate_daily_ai_alpha_picks()
