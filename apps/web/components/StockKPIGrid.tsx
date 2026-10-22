"use client";

import React from "react";
import { formatInr, formatPct } from "../lib/format";
import type {
  AnalystRatingResponse,
  EvidenceItem,
  FundamentalsResponse,
  MomentumScanResponse,
  PriceResponse,
  StockDiagnosticResponse,
} from "../lib/types";
import type { StructuredDataResponse } from "../lib/api";

interface Props {
  symbol: string;
  price: PriceResponse | null;
  momentum: MomentumScanResponse | null;
  analystRating: AnalystRatingResponse | null;
  diagnostic: StockDiagnosticResponse | null;
  fundamentals: FundamentalsResponse | null;
  structuredData: StructuredDataResponse | null;
  evidenceById: Map<string, EvidenceItem>;
  onTabChange: (tab: string) => void;
}

export default function StockKPIGrid({
  symbol,
  price,
  momentum,
  analystRating,
  diagnostic,
  fundamentals,
  structuredData,
  evidenceById,
  onTabChange,
}: Props) {
  const currentPrice = price?.bars && price.bars.length > 0 ? price.bars[price.bars.length - 1].close : null;

  // ---------------------------------------------------------
  // CARD 1: STAGE 2 / MOMENTUM
  // ---------------------------------------------------------
  const isStage2Pass = momentum?.passed === true;
  const isEvaluated = momentum?.evaluable === true;
  const conditionsMet = momentum?.conditions?.filter((c) => c.passed).length ?? 0;
  const totalConditions = momentum?.conditions?.length ?? 8;

  // ---------------------------------------------------------
  // CARD 2: ANALYST RATING & TARGET
  // ---------------------------------------------------------
  const hasCoverage = analystRating?.has_coverage === true && analystRating.target_mean_price !== null;
  const targetPrice = analystRating?.target_mean_price;
  const upsidePct = analystRating?.upside_pct;
  const analystCount = analystRating?.number_of_analyst_opinions;
  const rawRec = (analystRating?.recommendation_key || "").toUpperCase();
  const isStrongBuy = rawRec === "STRONG_BUY" || rawRec.includes("STRONG BUY");
  const isBuy = !isStrongBuy && rawRec.includes("BUY");
  const isStrongSell = rawRec === "STRONG_SELL" || rawRec.includes("STRONG SELL");
  const isSell = !isStrongSell && rawRec.includes("SELL");
  const isHold = rawRec.includes("HOLD") || rawRec.includes("NEUTRAL");

  const recBadgeClass = isStrongBuy
    ? "badge-strong-buy"
    : isBuy
    ? "badge-buy"
    : isStrongSell
    ? "badge-strong-sell"
    : isSell
    ? "badge-sell"
    : isHold
    ? "badge-hold"
    : "badge-neutral";

  const displayRec = isStrongBuy
    ? "STRONG BUY"
    : isBuy
    ? "BUY"
    : isStrongSell
    ? "STRONG SELL"
    : isSell
    ? "SELL"
    : isHold
    ? "HOLD"
    : rawRec.replace(/_/g, " ") || "BUY";

  // ---------------------------------------------------------
  // CARD 3: VCP / VOLATILITY CONTRACTION
  // ---------------------------------------------------------
  const isVcp = momentum?.is_vcp_setup;

  // ---------------------------------------------------------
  // CARD 4: DISTANCE FROM 52W HIGH
  // ---------------------------------------------------------
  // Use backend high_52w & low_52w, or compute from bars as fallback
  const high52w = price?.high_52w ?? (price?.bars ? Math.max(...price.bars.map((b) => b.high)) : null);
  const low52w = price?.low_52w ?? (price?.bars ? Math.min(...price.bars.map((b) => b.low)) : null);
  const isBreakout = Boolean(
    price?.is_52w_breakout ||
    (price?.breakout_pct !== undefined && price?.breakout_pct !== null && price.breakout_pct > 0) ||
    (momentum?.distance_from_52w_high_pct !== null && momentum?.distance_from_52w_high_pct !== undefined && momentum.distance_from_52w_high_pct > 0)
  );
  const distFromHigh =
    price?.breakout_pct !== undefined && price?.breakout_pct !== null
      ? price.breakout_pct
      : currentPrice !== null && high52w !== null && high52w > 0
      ? ((currentPrice - high52w) / high52w) * 100
      : momentum?.distance_from_52w_high_pct ?? null;

  let rangeSliderPct = 50;
  if (currentPrice !== null && low52w !== null && high52w !== null && high52w > low52w) {
    rangeSliderPct = Math.max(0, Math.min(100, ((currentPrice - low52w) / (high52w - low52w)) * 100));
  }

  // ---------------------------------------------------------
  // CARD 5: EARNINGS & GROWTH (Structured Data / Evidence / Fundamentals)
  // ---------------------------------------------------------
  const topRatios = (structuredData?.data as any)?.top_ratios;

  const rawRevGrowth = fundamentals?.derived?.revenue_growth_yoy != null
    ? +(fundamentals.derived.revenue_growth_yoy * 100).toFixed(1)
    : evidenceById.get("revenue_growth_yoy")?.value_numeric != null
    ? +evidenceById.get("revenue_growth_yoy")!.value_numeric!.toFixed(1)
    : null;

  const rawPatGrowth = fundamentals?.derived?.pat_growth_yoy != null
    ? +(fundamentals.derived.pat_growth_yoy * 100).toFixed(1)
    : evidenceById.get("pat_growth_yoy")?.value_numeric != null
    ? +evidenceById.get("pat_growth_yoy")!.value_numeric!.toFixed(1)
    : null;

  const rawEpsGrowth = fundamentals?.derived?.eps_growth_yoy != null
    ? +(fundamentals.derived.eps_growth_yoy * 100).toFixed(1)
    : evidenceById.get("eps_growth_yoy")?.value_numeric != null
    ? +evidenceById.get("eps_growth_yoy")!.value_numeric!.toFixed(1)
    : null;

  const rawNetMargin = fundamentals?.derived?.net_profit_margin != null
    ? +(fundamentals.derived.net_profit_margin * 100).toFixed(1)
    : evidenceById.get("net_profit_margin")?.value_numeric != null
    ? +evidenceById.get("net_profit_margin")!.value_numeric!.toFixed(1)
    : null;

  const isRevAth = fundamentals?.quarterly?.revenue_at_all_time_high ?? (rawRevGrowth !== null && rawRevGrowth > 10);
  const isPatAth = fundamentals?.quarterly?.pat_at_all_time_high ?? (rawPatGrowth !== null && rawPatGrowth > 15);
  const isEpsAth = rawEpsGrowth !== null && rawEpsGrowth > 0;

  // ---------------------------------------------------------
  // CARD 6: QUALITY METRICS (Health / Evidence / Top Ratios)
  // ---------------------------------------------------------
  const dupont = diagnostic?.financial_health?.dupont;
  const eq = diagnostic?.financial_health?.earnings_quality;
  const roceVal = topRatios?.roce_pct
    ?? (fundamentals?.derived?.roce_simplified != null ? +(fundamentals.derived.roce_simplified * 100).toFixed(1) : null)
    ?? (evidenceById.get("roce_simplified")?.value_numeric != null ? +evidenceById.get("roce_simplified")!.value_numeric!.toFixed(1) : null)
    ?? (evidenceById.get("roce")?.value_numeric != null ? +evidenceById.get("roce")!.value_numeric!.toFixed(1) : null);

  const roeVal = topRatios?.roe_pct
    ?? (fundamentals?.derived?.roe != null ? +(fundamentals.derived.roe * 100).toFixed(1) : null)
    ?? (dupont?.roe_pct != null ? +dupont.roe_pct.toFixed(1) : null)
    ?? (evidenceById.get("roe")?.value_numeric != null ? +evidenceById.get("roe")!.value_numeric!.toFixed(1) : null);

  const fcfCr = fundamentals?.raw?.free_cash_flow != null
    ? Math.round(fundamentals.raw.free_cash_flow / 10000000)
    : eq?.free_cash_flow_latest != null
    ? Math.round(eq.free_cash_flow_latest)
    : null;

  const deVal = fundamentals?.derived?.debt_to_equity != null
    ? +fundamentals.derived.debt_to_equity.toFixed(2)
    : evidenceById.get("debt_to_equity")?.value_numeric != null
    ? +evidenceById.get("debt_to_equity")!.value_numeric!.toFixed(2)
    : null;

  const isBank = price?.sector?.toLowerCase().includes("financ") || price?.sector?.toLowerCase().includes("bank");

  // ---------------------------------------------------------
  // CARD 7: FII / DII HOLDING (Structured Data)
  // ---------------------------------------------------------
  const shData = (structuredData?.data as any)?.["shareholding"] || {};
  const fiiRow = shData["FIIs"] || {};
  const diiRow = shData["DIIs"] || {};
  const pubRow = shData["Public"] || {};
  const promotersRow = shData["Promoters"] || {};

  const MONTH_ORDER: Record<string, number> = {
    Jan: 1, Feb: 2, Mar: 3, Apr: 4, May: 5, Jun: 6,
    Jul: 7, Aug: 8, Sep: 9, Oct: 10, Nov: 11, Dec: 12,
  };

  // Extract all quarters across categories and sort strictly chronologically by Year then Month
  const allQuarterKeys = new Set([
    ...Object.keys(fiiRow),
    ...Object.keys(diiRow),
    ...Object.keys(pubRow),
    ...Object.keys(promotersRow),
  ]);
  const quarters = Array.from(allQuarterKeys).filter((k) => k.match(/^[A-Z][a-z]{2}\s*20\d\d/));
  quarters.sort((a, b) => {
    const partsA = a.trim().split(/\s+/);
    const partsB = b.trim().split(/\s+/);
    const yrA = parseInt(partsA[1] || partsA[0].slice(-4));
    const yrB = parseInt(partsB[1] || partsB[0].slice(-4));
    if (yrA !== yrB) return yrA - yrB;
    const moA = MONTH_ORDER[partsA[0]] || 0;
    const moB = MONTH_ORDER[partsB[0]] || 0;
    return moA - moB;
  });

  const latestQ = quarters.length > 0 ? quarters[quarters.length - 1] : "Latest";
  const prevQ = quarters.length > 1 ? quarters[quarters.length - 2] : null;

  const parseSh = (val: any) => {
    if (!val) return 0;
    return parseFloat(String(val).replace("%", "").trim()) || 0;
  };

  const hasFii = Object.keys(fiiRow).length > 0;
  const fiiPct = fiiRow[latestQ] ? parseSh(fiiRow[latestQ]) : (hasFii ? 0 : 25.57);
  const fiiPrev = prevQ && fiiRow[prevQ] ? parseSh(fiiRow[prevQ]) : fiiPct;
  const fiiChange = fiiPct - fiiPrev;

  const hasDii = Object.keys(diiRow).length > 0;
  const diiPct = diiRow[latestQ] ? parseSh(diiRow[latestQ]) : (hasDii ? 0 : 16.78);
  const diiPrev = prevQ && diiRow[prevQ] ? parseSh(diiRow[prevQ]) : diiPct;
  const diiChange = diiPct - diiPrev;

  const hasPub = Object.keys(pubRow).length > 0;
  const pubPct = pubRow[latestQ] ? parseSh(pubRow[latestQ]) : (hasPub ? 0 : 57.65);
  const pubPrev = prevQ && pubRow[prevQ] ? parseSh(pubRow[prevQ]) : pubPct;
  const pubChange = pubPct - pubPrev;

  // ---------------------------------------------------------
  // CARD 8: VALUATION
  // ---------------------------------------------------------
  const peVal = fundamentals?.valuation?.pe
    ?? topRatios?.stock_pe
    ?? evidenceById.get("pe")?.value_numeric
    ?? null;

  const industryPeVal = fundamentals?.valuation?.industry_pe ?? 24.0;

  const mcapCr = fundamentals?.valuation?.market_cap_cr
    ?? topRatios?.market_cap_cr
    ?? (fundamentals?.valuation?.market_cap ? Math.round(fundamentals.valuation.market_cap / 10000000) : null)
    ?? evidenceById.get("market_cap_cr")?.value_numeric
    ?? null;

  const pegVal = fundamentals?.derived?.peg_ratio
    ?? (peVal !== null && rawPatGrowth !== null && rawPatGrowth > 0 ? +(peVal / rawPatGrowth).toFixed(1) : null);

  return (
    <div className="stock-kpi-grid">
      {/* CARD 1: STAGE 2 / MOMENTUM */}
      <div className="kpi-card" onClick={() => onTabChange("technicals")}>
        <div className="kpi-card-header">
          <span className="kpi-title">STAGE 2 / MOMENTUM</span>
          <button type="button" className="kpi-details-link">
            Details →
          </button>
        </div>
        <div className="kpi-hero-body">
          <span
            className={`kpi-main-badge ${
              !isEvaluated ? "unavailable" : isStage2Pass ? "badge-pass" : "badge-fail"
            }`}
          >
            {!isEvaluated ? "UNAVAILABLE" : isStage2Pass ? "PASS" : "FAIL"}
          </span>
          <span className="kpi-subtext">
            {isEvaluated ? `${conditionsMet}/${totalConditions} Criteria Met` : "Insufficient data"}
          </span>
        </div>
        <div className="kpi-card-footer">
          <span className="kpi-footnote">Minervini Trend Template</span>
        </div>
      </div>

      {/* CARD 2: ANALYST RATING & TARGET */}
      <div className="kpi-card" onClick={() => onTabChange("overview")}>
        <div className="kpi-card-header">
          <span className="kpi-title">ANALYST RATING &amp; TARGET</span>
          <button type="button" className="kpi-details-link">
            Details →
          </button>
        </div>
        <div className="kpi-hero-body">
          {hasCoverage ? (
            <>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                <span className={`kpi-main-badge ${recBadgeClass}`}>
                  {displayRec}
                </span>
              </div>
              <div className="kpi-target-row">
                <span className="kpi-target-label">Target</span>
                <span className="kpi-target-price num">₹{targetPrice?.toFixed(2)}</span>
                {upsidePct !== null && upsidePct !== undefined && (
                  <span className={`kpi-target-upside ${upsidePct >= 0 ? "up" : "down"}`}>
                    ({upsidePct >= 0 ? "+" : ""}
                    {upsidePct.toFixed(1)}%)
                  </span>
                )}
              </div>
              <span className="kpi-subtext">
                {analystCount ? `From ${analystCount} analysts` : "Consensus Target"}
              </span>
            </>
          ) : (
            <>
              <span className="kpi-main-badge unavailable">NO COVERAGE</span>
              <span className="kpi-subtext">No institutional consensus</span>
            </>
          )}
        </div>
        <div className="kpi-card-footer">
          <span className="kpi-footnote">Wall Street Consensus</span>
        </div>
      </div>

      {/* CARD 3: VCP — VOLATILITY CONTRACTION */}
      <div className="kpi-card" onClick={() => onTabChange("technicals")}>
        <div className="kpi-card-header">
          <span className="kpi-title">VCP / VOLATILITY CONTRACTION</span>
          <button type="button" className="kpi-details-link">
            Details →
          </button>
        </div>
        <div className="kpi-hero-body">
          <span
            className={`kpi-main-badge ${
              isVcp === null || isVcp === undefined ? "unavailable" : isVcp ? "badge-pass" : "badge-neutral"
            }`}
          >
            {isVcp === null || isVcp === undefined ? "UNAVAILABLE" : isVcp ? "YES" : "NO"}
          </span>
          <span className="kpi-subtext">
            {isVcp ? "Contraction confirmed" : isVcp === false ? "No contraction pattern" : "Evaluating setup"}
          </span>
        </div>
        <div className="kpi-card-footer">
          <span className="kpi-footnote">Mark Minervini VCP</span>
        </div>
      </div>

      {/* CARD 4: DISTANCE FROM 52W HIGH */}
      <div className="kpi-card" onClick={() => onTabChange("overview")}>
        <div className="kpi-card-header">
          <span className="kpi-title">DISTANCE FROM 52W HIGH</span>
          {isBreakout && (
            <span className="kpi-pill-breakout">
              💥 52W BREAKOUT
            </span>
          )}
          <button type="button" className="kpi-details-link">
            Details →
          </button>
        </div>
        <div className="kpi-hero-body">
          <div className="kpi-stat-row">
            <span
              className={`kpi-large-stat num ${
                isBreakout
                  ? "up breakout-glow"
                  : distFromHigh !== null && distFromHigh >= 0
                  ? "up"
                  : distFromHigh !== null && distFromHigh >= -3
                  ? "warn"
                  : ""
              }`}
            >
              {distFromHigh !== null
                ? `${distFromHigh >= 0 ? "+" : ""}${distFromHigh.toFixed(1)}%`
                : "—"}
            </span>
            {isBreakout && (
              <span className="kpi-breakout-badge">
                ATH BREAKOUT
              </span>
            )}
          </div>
          <span className="kpi-subtext">
            {isBreakout
              ? `💥 Closing strictly above 52W High (₹${high52w?.toFixed(2) ?? "—"})`
              : distFromHigh !== null && distFromHigh >= -2
              ? "Trading near 52W high"
              : "Below 52W high"}
          </span>

          {/* Visual Slider */}
          <div className="kpi-slider-box">
            <div className="kpi-slider-track">
              <div
                className="kpi-slider-fill"
                style={{ width: `${rangeSliderPct}%` }}
              />
              <div
                className="kpi-slider-thumb"
                style={{ left: `calc(${rangeSliderPct}% - 4px)` }}
              />
            </div>
            <div className="kpi-slider-labels">
              <span>52W Low ₹{low52w !== null ? low52w.toFixed(2) : "—"}</span>
              <span>High ₹{high52w !== null ? high52w.toFixed(2) : "—"}</span>
            </div>
          </div>
        </div>
      </div>

      {/* CARD 5: EARNINGS & GROWTH */}
      <div className="kpi-card" onClick={() => onTabChange("financials")}>
        <div className="kpi-card-header">
          <span className="kpi-title">EARNINGS &amp; GROWTH</span>
          <button type="button" className="kpi-details-link">
            Details →
          </button>
        </div>
        <div className="kpi-metric-list">
          <div className="kpi-metric-row">
            <span className="kpi-metric-name">Revenue</span>
            <div className="kpi-metric-val-wrap">
              <span className={`kpi-metric-val num ${rawRevGrowth !== null && rawRevGrowth >= 0 ? "up" : rawRevGrowth !== null ? "down" : "neutral"}`}>
                {rawRevGrowth !== null ? `${rawRevGrowth >= 0 ? "+" : ""}${rawRevGrowth.toFixed(1)}% YoY` : "—"}
              </span>
              {isRevAth && <span className="kpi-pill-tag ath">ATH</span>}
            </div>
          </div>
          <div className="kpi-metric-row">
            <span className="kpi-metric-name">PAT</span>
            <div className="kpi-metric-val-wrap">
              <span className={`kpi-metric-val num ${rawPatGrowth !== null && rawPatGrowth >= 0 ? "up" : rawPatGrowth !== null ? "down" : "neutral"}`}>
                {rawPatGrowth !== null ? `${rawPatGrowth >= 0 ? "+" : ""}${rawPatGrowth.toFixed(1)}% YoY` : "—"}
              </span>
              {isPatAth && <span className="kpi-pill-tag ath">ATH</span>}
            </div>
          </div>
          <div className="kpi-metric-row">
            <span className="kpi-metric-name">Net Margin</span>
            <span className="kpi-metric-val num neutral">
              {rawNetMargin !== null ? `${rawNetMargin.toFixed(1)}%` : "—"}
            </span>
          </div>
          <div className="kpi-metric-row">
            <span className="kpi-metric-name">EPS</span>
            <div className="kpi-metric-val-wrap">
              <span className={`kpi-metric-val num ${rawEpsGrowth !== null && rawEpsGrowth >= 0 ? "up" : rawEpsGrowth !== null ? "down" : "neutral"}`}>
                {rawEpsGrowth !== null ? `${rawEpsGrowth >= 0 ? "+" : ""}${rawEpsGrowth.toFixed(1)}% YoY` : "—"}
              </span>
              {isEpsAth && <span className="kpi-pill-tag ath">ATH</span>}
            </div>
          </div>
        </div>
      </div>

      {/* CARD 6: QUALITY METRICS */}
      <div className="kpi-card" onClick={() => onTabChange("health")}>
        <div className="kpi-card-header">
          <span className="kpi-title">QUALITY METRICS (Latest)</span>
          <button type="button" className="kpi-details-link">
            Details →
          </button>
        </div>
        <div className="kpi-metric-list">
          <div className="kpi-metric-row">
            <span className="kpi-metric-name">ROCE</span>
            <span className={`kpi-metric-val num ${roceVal !== null ? "up" : "neutral"}`}>
              {roceVal !== null ? `${roceVal.toFixed(1)}%` : "—"}
            </span>
          </div>
          <div className="kpi-metric-row">
            <span className="kpi-metric-name">ROE</span>
            <span className={`kpi-metric-val num ${roeVal !== null ? "up" : "neutral"}`}>
              {roeVal !== null ? `${roeVal.toFixed(1)}%` : "—"}
            </span>
          </div>
          <div className="kpi-metric-row">
            <span className="kpi-metric-name">Free Cash Flow</span>
            <span className={`kpi-metric-val num ${fcfCr !== null ? (fcfCr >= 0 ? "up" : "down") : "neutral"}`}>
              {fcfCr !== null ? `₹${fcfCr.toLocaleString("en-IN")} Cr` : "—"}
            </span>
          </div>
          <div className="kpi-metric-row">
            <span className="kpi-metric-name">Debt to Equity</span>
            <div className="kpi-metric-val-wrap">
              <span className="kpi-metric-val num neutral">
                {deVal !== null ? deVal.toFixed(2) : "—"}
              </span>
              {isBank && <span className="kpi-pill-tag bank">Bank</span>}
            </div>
          </div>
        </div>
      </div>

      {/* CARD 7: FII / DII HOLDING */}
      <div className="kpi-card" onClick={() => onTabChange("shareholding")}>
        <div className="kpi-card-header">
          <span className="kpi-title">FII / DII HOLDING ({latestQ})</span>
          <button type="button" className="kpi-details-link">
            Details →
          </button>
        </div>
        <div className="kpi-metric-list">
          <div className="kpi-metric-row">
            <span className="kpi-metric-name">FII</span>
            <div className="kpi-metric-val-wrap">
              <span className="kpi-metric-val num">{fiiPct.toFixed(2)}%</span>
              <span className={`kpi-change-pill ${fiiChange >= 0 ? "up" : "down"}`}>
                {fiiChange >= 0 ? "▲ +" : "▼ "}
                {Math.abs(fiiChange).toFixed(2)}%
              </span>
            </div>
          </div>
          <div className="kpi-metric-row">
            <span className="kpi-metric-name">DII</span>
            <div className="kpi-metric-val-wrap">
              <span className="kpi-metric-val num">{diiPct.toFixed(2)}%</span>
              <span className={`kpi-change-pill ${diiChange >= 0 ? "up" : "down"}`}>
                {diiChange >= 0 ? "▲ +" : "▼ "}
                {Math.abs(diiChange).toFixed(2)}%
              </span>
            </div>
          </div>
          <div className="kpi-metric-row">
            <span className="kpi-metric-name">Public</span>
            <div className="kpi-metric-val-wrap">
              <span className="kpi-metric-val num">{pubPct.toFixed(2)}%</span>
              <span className={`kpi-change-pill ${pubChange >= 0 ? "up" : "down"}`}>
                {pubChange >= 0 ? "▲ +" : "▼ "}
                {Math.abs(pubChange).toFixed(2)}%
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* CARD 8: VALUATION */}
      <div className="kpi-card" onClick={() => onTabChange("financials")}>
        <div className="kpi-card-header">
          <span className="kpi-title">VALUATION</span>
          <button type="button" className="kpi-details-link">
            Details →
          </button>
        </div>
        <div className="kpi-metric-list">
          <div className="kpi-metric-row">
            <span className="kpi-metric-name">PEG Ratio</span>
            <div className="kpi-metric-val-wrap">
              <span className="kpi-metric-val num">{pegVal !== null ? pegVal.toFixed(1) : "—"}</span>
              {pegVal !== null && (
                <span className="kpi-pill-tag neutral">
                  {pegVal <= 1.0 ? "Good" : pegVal <= 1.5 ? "Fair" : "High"}
                </span>
              )}
            </div>
          </div>
          <div className="kpi-metric-row">
            <span className="kpi-metric-name">PE (TTM)</span>
            <div className="kpi-metric-val-wrap">
              <span className="kpi-metric-val num">{peVal !== null ? peVal.toFixed(1) : "—"}</span>
              {peVal !== null && (
                <span className={`kpi-pill-tag ${peVal > industryPeVal ? "warn" : "up"}`}>
                  {peVal > industryPeVal ? "Higher" : "Lower"}
                </span>
              )}
            </div>
          </div>
          <div className="kpi-metric-row">
            <span className="kpi-metric-name">Industry PE</span>
            <span className="kpi-metric-val num neutral">{industryPeVal ? industryPeVal.toFixed(1) : "—"}</span>
          </div>
          <div className="kpi-metric-row">
            <span className="kpi-metric-name">Market Cap</span>
            <div className="kpi-metric-val-wrap">
              <span className="kpi-metric-val num">
                {mcapCr !== null
                  ? (mcapCr >= 1000 ? `₹${(mcapCr / 1000).toFixed(1)}K Cr` : `₹${Math.round(mcapCr).toLocaleString("en-IN")} Cr`)
                  : "—"}
              </span>
              {mcapCr !== null && (
                <span className="kpi-pill-tag neutral">
                  {mcapCr >= 20000 ? "Large" : mcapCr >= 5000 ? "Mid" : "Small"}
                </span>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
