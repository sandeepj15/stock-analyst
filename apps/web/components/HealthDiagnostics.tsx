"use client";

import { useState } from "react";
import type { StockDiagnosticResponse } from "../lib/types";

interface Props {
  diagnostic: StockDiagnosticResponse | null;
}

export default function HealthDiagnostics({ diagnostic }: Props) {
  const [showPiotroskiDetails, setShowPiotroskiDetails] = useState(false);

  if (!diagnostic) {
    return (
      <div className="panel">
        <p className="footnote">Diagnostic health data unavailable for this stock.</p>
      </div>
    );
  }

  const { financial_health, shareholding_flow, technical_health } = diagnostic;
  const p = financial_health.piotroski;
  const z = financial_health.altman_z;
  const eq = financial_health.earnings_quality;
  const dp = financial_health.dupont;
  const shield = financial_health.forensic_shield;

  // Piotroski color
  const pScore = p?.score ?? 0;
  const pTone = pScore >= 7 ? "up" : pScore >= 4 ? "warn" : "down";

  // Altman Z color
  const zZone = z?.zone ?? "Unavailable";
  const zTone = zZone === "Safe Zone" ? "up" : zZone === "Grey Zone" ? "warn" : "down";

  // U/D Volume ratio color
  const udRatio = technical_health.up_down_volume_ratio ?? 1.0;
  const udTone = udRatio >= 1.25 ? "up" : udRatio <= 0.85 ? "down" : "flat";

  // Range position pct
  const rangePct = Math.max(0, Math.min(100, technical_health.range_position_pct ?? 50));

  return (
    <div className="health-diagnostics-container">
      {/* ---------------- 1. FINANCIAL HEALTH & FORENSICS ---------------- */}
      <div className="panel health-panel">
        <div className="panel-header">
          <div className="panel-title-group">
            <h3>Financial Health & Forensic Diagnostic</h3>
            <span className="footnote">
              Based on audited annual statements ({financial_health.fiscal_year_latest ?? "Latest FY"})
            </span>
          </div>
          {shield && (
            <div className={`shield-badge ${shield.is_clean ? "shield-clean" : "shield-alert"}`}>
              <span className="shield-icon">{shield.is_clean ? "🛡️" : "⚠️"}</span>
              <span className="shield-text">{shield.verdict}</span>
            </div>
          )}
        </div>

        {/* Forensic Flags Alert Box if any flags */}
        {shield && !shield.is_clean && (
          <div className="forensic-alert-box">
            <div className="forensic-alert-title">Forensic Warning Signals:</div>
            <div className="forensic-alert-list">
              {shield.flags.map((flag) => (
                <div key={flag.code} className={`forensic-alert-item ${flag.severity}`}>
                  <strong>{flag.title}:</strong> {flag.detail}
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="health-grid">
          {/* Piotroski F-Score Card */}
          <div className="sub-panel health-card">
            <div className="health-card-head">
              <span className="health-card-label">Piotroski F-Score</span>
              <span className={`badge ${pTone}`}>{p?.verdict ?? "N/A"}</span>
            </div>
            <div className="health-metric-hero">
              <span className={`health-hero-value num ${pTone}`}>{p?.score ?? "—"}</span>
              <span className="health-hero-max">/ 9</span>
            </div>
            <div className="piotroski-pill-row">
              <span className="mini-chip">Profitability: {p?.profitability_score ?? 0}/4</span>
              <span className="mini-chip">Liquidity: {p?.leverage_liquidity_score ?? 0}/3</span>
              <span className="mini-chip">Efficiency: {p?.operating_efficiency_score ?? 0}/2</span>
            </div>
            <button
              type="button"
              className="toggle-text-btn"
              onClick={() => setShowPiotroskiDetails(!showPiotroskiDetails)}
            >
              {showPiotroskiDetails ? "Hide 9 Health Checks ▲" : "View 9 Health Checks ▼"}
            </button>
            {showPiotroskiDetails && p && (
              <div className="piotroski-checklist">
                {p.tests.map((t, idx) => (
                  <div key={idx} className="checklist-row">
                    <span className={`check-icon ${t.passed ? "up" : "down"}`}>{t.passed ? "✓" : "✗"}</span>
                    <div className="check-info">
                      <div className="check-name">
                        {t.name} <span className="check-cat">({t.category})</span>
                      </div>
                      <div className="check-desc">{t.description}</div>
                    </div>
                    <span className="check-val num">{t.value_display}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Altman Z-Score Card */}
          <div className="sub-panel health-card">
            <div className="health-card-head">
              <span className="health-card-label">Altman Z&apos;&apos;-Score (Solvency)</span>
              <span className={`badge ${zTone}`}>{zZone}</span>
            </div>
            <div className="health-metric-hero">
              <span className={`health-hero-value num ${zTone}`}>{z?.z_score !== null ? z?.z_score : "—"}</span>
              <span className="health-hero-sub">Z&apos;&apos; Score</span>
            </div>
            <p className="footnote health-desc">{z?.description ?? "Credit risk score"}</p>
            <div className="z-scale-track">
              <div className="z-scale-segment z-distress">Distress (&lt;1.1)</div>
              <div className="z-scale-segment z-grey">Grey (1.1–2.6)</div>
              <div className="z-scale-segment z-safe">Safe (&gt;2.6)</div>
            </div>
          </div>

          {/* Earnings Quality Card */}
          <div className="sub-panel health-card">
            <div className="health-card-head">
              <span className="health-card-label">Earnings Quality & Cash Flow</span>
              <span className={`badge ${(eq?.cfo_to_pat ?? 0) >= 1.0 ? "up" : (eq?.cfo_to_pat ?? 0) >= 0.7 ? "flat" : "down"}`}>
                {(eq?.cfo_to_pat ?? 0) >= 1.0 ? "High Cash Backing" : "Accrual Drag"}
              </span>
            </div>
            <div className="eq-stat-grid">
              <div className="eq-stat">
                <span className="eq-label">CFO / PAT Ratio</span>
                <span className="eq-val num font-bold">
                  {eq?.cfo_to_pat !== null && eq?.cfo_to_pat !== undefined ? `${eq.cfo_to_pat}x` : "—"}
                </span>
              </div>
              <div className="eq-stat">
                <span className="eq-label">Free Cash Flow</span>
                <span className="eq-val num">
                  {eq?.free_cash_flow_latest !== null && eq?.free_cash_flow_latest !== undefined
                    ? `₹${eq.free_cash_flow_latest.toLocaleString()} Cr`
                    : "—"}
                </span>
              </div>
              <div className="eq-stat">
                <span className="eq-label">Cash Conversion Cycle</span>
                <span className="eq-val num">
                  {eq?.cash_conversion_cycle_days !== null && eq?.cash_conversion_cycle_days !== undefined
                    ? `${eq.cash_conversion_cycle_days} days`
                    : "—"}
                </span>
              </div>
              <div className="eq-stat">
                <span className="eq-label">Debtor Days (YoY Δ)</span>
                <span className="eq-val num">
                  {eq?.debtor_days !== null && eq?.debtor_days !== undefined
                    ? `${eq.debtor_days}d (${(eq.debtor_days_yoy_change ?? 0) > 0 ? "+" : ""}${eq.debtor_days_yoy_change ?? 0}d)`
                    : "—"}
                </span>
              </div>
            </div>
            <p className="footnote health-desc">{eq?.cfo_to_pat_verdict ?? ""}</p>
          </div>
        </div>

        {/* DuPont 3-Way ROE Decomposition */}
        {dp && dp.roe_pct !== null && (
          <div className="dupont-box">
            <div className="dupont-title-row">
              <span className="dupont-title">DuPont 3-Way ROE Decomposition</span>
              <span className="dupont-driver">
                Primary Driver: <strong>{dp.primary_driver}</strong>
              </span>
            </div>
            <div className="dupont-flow">
              <div className="dupont-step dupont-total">
                <span className="dupont-step-label">ROE</span>
                <span className="dupont-step-val num up">{dp.roe_pct?.toFixed(1)}%</span>
              </div>
              <div className="dupont-op">=</div>
              <div className="dupont-step">
                <span className="dupont-step-label">Net Profit Margin</span>
                <span className="dupont-step-val num">{dp.net_profit_margin_pct?.toFixed(1)}%</span>
                <span className="dupont-sublabel">Pricing Power</span>
              </div>
              <div className="dupont-op">×</div>
              <div className="dupont-step">
                <span className="dupont-step-label">Asset Turnover</span>
                <span className="dupont-step-val num">{dp.asset_turnover?.toFixed(2)}x</span>
                <span className="dupont-sublabel">Asset Efficiency</span>
              </div>
              <div className="dupont-op">×</div>
              <div className="dupont-step">
                <span className="dupont-step-label">Financial Leverage</span>
                <span className="dupont-step-val num">{dp.financial_leverage?.toFixed(2)}x</span>
                <span className="dupont-sublabel">Equity Multiplier</span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ---------------- 2. SMART MONEY & OWNERSHIP FLOWS ---------------- */}
      <div className="panel health-panel">
        <div className="panel-header">
          <div className="panel-title-group">
            <h3>Smart Money & Institutional Ownership</h3>
            <span className="footnote">
              Quarterly trend as of {shareholding_flow.latest_quarter ?? "Latest"}
            </span>
          </div>
          <span
            className={`badge ${
              shareholding_flow.smart_money_verdict.includes("Accumulation")
                ? "up"
                : shareholding_flow.smart_money_verdict.includes("Alert") ||
                  shareholding_flow.smart_money_verdict.includes("Outflows")
                ? "warn"
                : "flat"
            }`}
          >
            {shareholding_flow.smart_money_verdict}
          </span>
        </div>

        <div className="smart-money-banner">
          <span className="banner-icon">🏦</span>
          <span className="banner-text">{shareholding_flow.smart_money_description}</span>
        </div>

        <div className="ownership-metric-row">
          <div className="ownership-stat-card">
            <span className="ownership-stat-label">Promoters</span>
            <span className="ownership-stat-val num">
              {shareholding_flow.promoter_current !== null ? `${shareholding_flow.promoter_current}%` : "0.0%"}
            </span>
            <span
              className={`ownership-stat-chg num ${
                (shareholding_flow.promoter_qoq_change ?? 0) >= 0 ? "up" : "down"
              }`}
            >
              QoQ: {(shareholding_flow.promoter_qoq_change ?? 0) >= 0 ? "+" : ""}
              {shareholding_flow.promoter_qoq_change?.toFixed(2) ?? "0.00"}%
            </span>
          </div>

          <div className="ownership-stat-card">
            <span className="ownership-stat-label">FIIs (Foreign Inst.)</span>
            <span className="ownership-stat-val num">
              {shareholding_flow.fii_current !== null ? `${shareholding_flow.fii_current}%` : "—"}
            </span>
            <span
              className={`ownership-stat-chg num ${(shareholding_flow.fii_qoq_change ?? 0) >= 0 ? "up" : "down"}`}
            >
              QoQ: {(shareholding_flow.fii_qoq_change ?? 0) >= 0 ? "+" : ""}
              {shareholding_flow.fii_qoq_change?.toFixed(2) ?? "0.00"}% (1Y:{" "}
              {(shareholding_flow.fii_yoy_change ?? 0) >= 0 ? "+" : ""}
              {shareholding_flow.fii_yoy_change?.toFixed(2) ?? "0.00"}%)
            </span>
          </div>

          <div className="ownership-stat-card">
            <span className="ownership-stat-label">DIIs (Domestic Inst.)</span>
            <span className="ownership-stat-val num">
              {shareholding_flow.dii_current !== null ? `${shareholding_flow.dii_current}%` : "—"}
            </span>
            <span
              className={`ownership-stat-chg num ${(shareholding_flow.dii_qoq_change ?? 0) >= 0 ? "up" : "down"}`}
            >
              QoQ: {(shareholding_flow.dii_qoq_change ?? 0) >= 0 ? "+" : ""}
              {shareholding_flow.dii_qoq_change?.toFixed(2) ?? "0.00"}% (1Y:{" "}
              {(shareholding_flow.dii_yoy_change ?? 0) >= 0 ? "+" : ""}
              {shareholding_flow.dii_yoy_change?.toFixed(2) ?? "0.00"}%)
            </span>
          </div>

          <div className="ownership-stat-card">
            <span className="ownership-stat-label">Public / Retail</span>
            <span className="ownership-stat-val num">
              {shareholding_flow.public_current !== null ? `${shareholding_flow.public_current}%` : "—"}
            </span>
            <span className="ownership-stat-sub footnote">
              {shareholding_flow.shareholders_count_current
                ? `${shareholding_flow.shareholders_count_current.toLocaleString()} holders`
                : "Public float"}
            </span>
          </div>
        </div>

        {/* 8-Quarter Ownership Progress Table */}
        {shareholding_flow.quarters_history.length > 0 && (
          <div className="sh-history-table-wrapper">
            <table className="sh-history-table">
              <thead>
                <tr>
                  <th>Quarter</th>
                  <th>Promoter %</th>
                  <th>FII %</th>
                  <th>DII %</th>
                  <th>Public %</th>
                  <th>Holders Count</th>
                </tr>
              </thead>
              <tbody>
                {shareholding_flow.quarters_history.map((q, idx) => (
                  <tr key={idx}>
                    <td className="font-medium">{q.quarter}</td>
                    <td className="num">{q.promoter !== null ? `${q.promoter.toFixed(2)}%` : "—"}</td>
                    <td className="num">{q.fii !== null ? `${q.fii.toFixed(2)}%` : "—"}</td>
                    <td className="num">{q.dii !== null ? `${q.dii.toFixed(2)}%` : "—"}</td>
                    <td className="num">{q.public !== null ? `${q.public.toFixed(2)}%` : "—"}</td>
                    <td className="num">{q.shareholders_count ? q.shareholders_count.toLocaleString() : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ---------------- 3. TECHNICAL HEALTH & VOLUME DYNAMICS ---------------- */}
      <div className="panel health-panel">
        <div className="panel-header">
          <div className="panel-title-group">
            <h3>Technical Health, Volume Flow & Range Structure</h3>
            <span className="footnote">Multi-timeframe trend & institutional volume footprint</span>
          </div>
          <span
            className={`badge ${
              technical_health.trend_alignment_grade.includes("Bullish")
                ? "up"
                : technical_health.trend_alignment_grade.includes("Pullback")
                ? "warn"
                : technical_health.trend_alignment_grade.includes("Bearish")
                ? "down"
                : "flat"
            }`}
          >
            {technical_health.trend_alignment_grade}
          </span>
        </div>

        <div className="tech-hero-banner">
          <p className="tech-summary">{technical_health.trend_summary}</p>
        </div>

        <div className="tech-grid">
          {/* Moving Averages Alignment Card */}
          <div className="sub-panel health-card">
            <span className="health-card-label">Trend Stacking & Distance</span>
            <div className="dma-stack-list">
              <div className="dma-row">
                <span className="dma-label">20 EMA (Short-term)</span>
                <span className="dma-val num">₹{technical_health.ema_20 ?? "—"}</span>
                <span
                  className={`dma-diff num ${(technical_health.price_vs_20ema_pct ?? 0) >= 0 ? "up" : "down"}`}
                >
                  {(technical_health.price_vs_20ema_pct ?? 0) >= 0 ? "+" : ""}
                  {technical_health.price_vs_20ema_pct ?? 0}%
                </span>
              </div>
              <div className="dma-row">
                <span className="dma-label">50 SMA (Medium-term)</span>
                <span className="dma-val num">₹{technical_health.sma_50 ?? "—"}</span>
                <span
                  className={`dma-diff num ${(technical_health.price_vs_50sma_pct ?? 0) >= 0 ? "up" : "down"}`}
                >
                  {(technical_health.price_vs_50sma_pct ?? 0) >= 0 ? "+" : ""}
                  {technical_health.price_vs_50sma_pct ?? 0}%
                </span>
              </div>
              <div className="dma-row">
                <span className="dma-label">200 SMA (Long-term)</span>
                <span className="dma-val num">₹{technical_health.sma_200 ?? "—"}</span>
                <span
                  className={`dma-diff num ${(technical_health.price_vs_200sma_pct ?? 0) >= 0 ? "up" : "down"}`}
                >
                  {(technical_health.price_vs_200sma_pct ?? 0) >= 0 ? "+" : ""}
                  {technical_health.price_vs_200sma_pct ?? 0}%
                </span>
              </div>
            </div>
          </div>

          {/* Volume Flow & Accumulation */}
          <div className="sub-panel health-card">
            <div className="health-card-head">
              <span className="health-card-label">Institutional Volume Flow</span>
              <span className={`badge ${udTone}`}>{technical_health.volume_flow_verdict.split(" ")[0]}</span>
            </div>
            <div className="health-metric-hero">
              <span className={`health-hero-value num ${udTone}`}>
                {technical_health.up_down_volume_ratio ?? "—"}x
              </span>
              <span className="health-hero-sub">Up/Down Volume Ratio (50D)</span>
            </div>
            <div className="vol-stat-row">
              <span className="footnote">
                Accumulation Days (20D):{" "}
                <strong className="num up">{technical_health.accumulation_days_count_20d} sessions</strong>
              </span>
            </div>
            <p className="footnote health-desc">{technical_health.volume_flow_verdict}</p>
          </div>

          {/* Volatility Squeeze & 52-Week Range */}
          <div className="sub-panel health-card">
            <div className="health-card-head">
              <span className="health-card-label">Volatility & Range Structure</span>
              <span
                className={`badge ${technical_health.is_volatility_squeeze ? "warn" : "flat"}`}
              >
                {technical_health.is_volatility_squeeze ? "Squeeze Active" : "Normal"}
              </span>
            </div>

            <div className="range-slider-wrapper">
              <div className="range-slider-head">
                <span className="range-slider-sub">
                  52W Low: ₹{technical_health.low_52w?.toLocaleString() ?? "—"}
                </span>
                <span className="range-slider-sub font-bold">
                  {technical_health.range_position_pct}% of Range
                </span>
                <span className="range-slider-sub">
                  52W High: ₹{technical_health.high_52w?.toLocaleString() ?? "—"}
                </span>
              </div>
              <div className="range-slider-track">
                <div className="range-slider-fill" style={{ width: `${rangePct}%` }} />
                <div className="range-slider-thumb" style={{ left: `${rangePct}%` }} />
              </div>
              <div className="range-distances">
                <span className="footnote num">
                  {(technical_health.pct_from_52w_low ?? 0) >= 0 ? "+" : ""}
                  {technical_health.pct_from_52w_low}% from Low
                </span>
                <span className="footnote num down">
                  {technical_health.pct_from_52w_high}% from High
                </span>
              </div>
            </div>

            <p className="footnote health-desc mt-2">{technical_health.volatility_state}</p>
          </div>
        </div>
      </div>
    </div>
  );
}
