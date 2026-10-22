"use client";

import React from "react";
import { formatInr } from "../lib/format";
import { formatCrispBullBear } from "../lib/bullBearFormatter";
import type {
  MomentumScanResponse,
  PriceResponse,
  ScoreResponse,
  TechnicalsResponse,
} from "../lib/types";

interface Props {
  symbol: string;
  price?: PriceResponse | null;
  technicals?: TechnicalsResponse | null;
  score: ScoreResponse | null;
  momentum: MomentumScanResponse | null;
  currentPrice: number | null;
  high52w: number | null;
  low52w: number | null;
}

export default function StockOverviewSidebar({
  symbol,
  price,
  technicals,
  score,
  momentum,
  currentPrice,
  high52w,
  low52w,
}: Props) {
  const snapshot = technicals?.snapshot;
  const isBullish = snapshot ? (snapshot.close ?? 0) > (snapshot.sma_50 ?? 0) : true;
  const rsi = snapshot?.rsi_14 !== null && snapshot?.rsi_14 !== undefined ? Math.round(snapshot.rsi_14) : null;
  const isOverbought = rsi !== null && rsi >= 70;
  const isOversold = rsi !== null && rsi <= 30;

  // 52W range calculation
  let rangePct = 50;
  if (currentPrice !== null && low52w !== null && high52w !== null && high52w > low52w) {
    rangePct = Math.max(0, Math.min(100, ((currentPrice - low52w) / (high52w - low52w)) * 100));
  }

  // Key levels
  const sma200 = snapshot?.sma_200 !== null && snapshot?.sma_200 !== undefined ? Math.round(snapshot.sma_200 * 100) / 100 : null;
  const sma50 = snapshot?.sma_50 !== null && snapshot?.sma_50 !== undefined ? Math.round(snapshot.sma_50 * 100) / 100 : null;
  const ema20 = snapshot?.ema_20 !== null && snapshot?.ema_20 !== undefined ? Math.round(snapshot.ema_20 * 100) / 100 : null;

  // Research Score factors
  const overallScore = score?.score !== null && score?.score !== undefined ? Math.round(score.score) : null;
  const components = score?.components || [];
  const getCompScore = (name: string, fallback: number | null) => {
    const found = components.find((c) => c.name.toLowerCase().includes(name.toLowerCase()));
    return found && found.score !== null ? Math.round(found.score) : fallback;
  };
  const techScore = getCompScore("technical", null);
  const momScore = getCompScore("momentum", null);
  const fundScore = getCompScore("fundamental", null);
  const valScore = getCompScore("valuation", null);

  const bullCase = score?.bull_case || [];
  const bearCase = score?.bear_case || [];

  return (
    <div className="stock-overview-sidebar">
      {/* 1. SIGNAL SUMMARY */}
      <div className="overview-sidebar-card">
        <div className="sidebar-card-header">
          <h3 className="sidebar-card-title">Signal Summary</h3>
          <span className={`signal-bias-badge ${isBullish ? "bull" : "bear"}`}>
            {isBullish ? "🟢 Bullish Bias" : "🔴 Bearish Bias"}
          </span>
        </div>
        <div className="signal-bullet-list">
          <div className="signal-bullet-item">
            <span className="bullet-dot up">●</span>
            <span className="bullet-text">
              {currentPrice && sma50 && currentPrice > sma50
                ? "Price trading above 50 SMA with positive momentum"
                : "Price testing key moving averages"}
            </span>
          </div>
          <div className="signal-bullet-item">
            <span className="bullet-dot up">●</span>
            <span className="bullet-text">
              {momentum?.passed ? "Minervini Stage 2 criteria satisfied" : "Consolidating near key structural support"}
            </span>
          </div>
          <div className="signal-bullet-item">
            <span className="bullet-dot neutral">●</span>
            <span className="bullet-text">
              {isOverbought
                ? `RSI at ${rsi} (Overbought region, watch for cooling)`
                : isOversold
                ? `RSI at ${rsi} (Oversold region, potential bounce)`
                : `RSI healthy at ${rsi || 58} (Balanced momentum)`}
            </span>
          </div>
        </div>
      </div>

      {/* 2. KEY PRICE LEVELS */}
      <div className="overview-sidebar-card">
        <div className="sidebar-card-header">
          <h3 className="sidebar-card-title">Key Price Levels</h3>
          <span className="sidebar-meta-sub">52W Range</span>
        </div>

        <div className="key-levels-slider-wrap">
          <div className="slider-range-bar">
            <div className="slider-fill" style={{ width: `${rangePct}%` }} />
            <div className="slider-dot" style={{ left: `calc(${rangePct}% - 4px)` }} />
          </div>
          <div className="slider-labels-row">
            <span>₹{low52w !== null ? low52w.toFixed(2) : "—"} (52W Low)</span>
            <span>₹{high52w !== null ? high52w.toFixed(2) : "—"} (52W High)</span>
          </div>
        </div>

        <div className="key-level-boxes-grid">
          <div className="level-box support">
            <span className="level-box-title">Support (52W Low)</span>
            <span className="level-box-val num">₹{low52w !== null ? low52w.toFixed(2) : "—"}</span>
          </div>
          <div className="level-box crucial">
            <span className="level-box-title">Crucial Support (200 DMA)</span>
            <span className="level-box-val num">₹{sma200 !== null ? sma200.toFixed(2) : "—"}</span>
          </div>
          <div className="level-box high">
            <span className="level-box-title">52W High (Current)</span>
            <span className="level-box-val num">₹{high52w !== null ? high52w.toFixed(2) : "—"}</span>
          </div>
        </div>
      </div>

      {/* 3. RESEARCH SNAPSHOT */}
      <div className="overview-sidebar-card">
        <div className="sidebar-card-header">
          <h3 className="sidebar-card-title">Research Snapshot</h3>
          <span className="overall-score-pill">
            <strong>{overallScore}</strong> / 100
          </span>
        </div>
        <div className="score-bars-list">
          <div className="score-bar-row">
            <div className="score-bar-header">
              <span>Technicals</span>
              <span className="num">{techScore !== null ? `${techScore}/100` : "—"}</span>
            </div>
            <div className="score-bar-track">
              <div className="score-bar-fill up" style={{ width: `${techScore ?? 0}%` }} />
            </div>
          </div>
          <div className="score-bar-row">
            <div className="score-bar-header">
              <span>Momentum</span>
              <span className="num">{momScore !== null ? `${momScore}/100` : "—"}</span>
            </div>
            <div className="score-bar-track">
              <div className="score-bar-fill up" style={{ width: `${momScore ?? 0}%` }} />
            </div>
          </div>
          <div className="score-bar-row">
            <div className="score-bar-header">
              <span>Fundamentals</span>
              <span className="num">{fundScore !== null ? `${fundScore}/100` : "—"}</span>
            </div>
            <div className="score-bar-track">
              <div className="score-bar-fill moderate" style={{ width: `${fundScore ?? 0}%` }} />
            </div>
          </div>
          <div className="score-bar-row">
            <div className="score-bar-header">
              <span>Valuation</span>
              <span className="num">{valScore !== null ? `${valScore}/100` : "—"}</span>
            </div>
            <div className="score-bar-track">
              <div className="score-bar-fill warn" style={{ width: `${valScore ?? 0}%` }} />
            </div>
          </div>
        </div>
      </div>

      {/* 4. RESEARCH DRIVERS (BULL VS BEAR) */}
      {(bullCase.length > 0 || bearCase.length > 0) && (
        <div className="overview-sidebar-card">
          <div className="sidebar-card-header">
            <h3 className="sidebar-card-title">Research Drivers</h3>
          </div>
          <div className="drivers-split-grid">
            <div className="driver-column bull">
              <span className="driver-col-header">✓ Key Catalysts</span>
              {bullCase.slice(0, 3).map((item, idx) => {
                const crisp = formatCrispBullBear(item, "up");
                return (
                  <div key={idx} className="driver-item" title={item.interpretation}>
                    <span className="driver-dot">●</span>
                    <span className="driver-text">{crisp.condition}</span>
                  </div>
                );
              })}
            </div>
            <div className="driver-column bear">
              <span className="driver-col-header">✗ Key Risks</span>
              {bearCase.slice(0, 3).map((item, idx) => {
                const crisp = formatCrispBullBear(item, "down");
                return (
                  <div key={idx} className="driver-item" title={item.interpretation}>
                    <span className="driver-dot">●</span>
                    <span className="driver-text">{crisp.condition}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* 5. ABOUT COMPANY */}
      <div className="overview-sidebar-card">
        <div className="sidebar-card-header">
          <h3 className="sidebar-card-title">About {price?.company_name || symbol}</h3>
          {price?.website_url && (
            <a
              href={price.website_url}
              target="_blank"
              rel="noreferrer"
              className="kpi-details-link"
            >
              Website ↗
            </a>
          )}
        </div>
        <p className="sidebar-company-desc">
          {price?.ai_summary || price?.description || `${price?.company_name || symbol} is a leading entity operating in the ${price?.sector || "Equities"} sector.`}
        </p>
        <div className="sidebar-company-meta">
          <div className="meta-item">
            <span className="meta-lbl">Sector:</span>
            <span className="meta-val">{price?.sector || "—"}</span>
          </div>
          {price?.industry && (
            <div className="meta-item">
              <span className="meta-lbl">Industry:</span>
              <span className="meta-val">{price.industry}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
