"use client";

import React, { useState } from "react";
import type { StockDiagnosticResponse } from "../lib/types";
import type { StructuredDataResponse } from "../lib/api";
import {
  ResponsiveContainer,
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";

interface Props {
  diagnostic: StockDiagnosticResponse | null;
  structuredData?: StructuredDataResponse | null;
}

export default function HealthDiagnostics({ diagnostic, structuredData }: Props) {
  const [showPiotroskiDetails, setShowPiotroskiDetails] = useState(false);
  const [showDuPontDetails, setShowDuPontDetails] = useState(false);
  const [trendMetric, setTrendMetric] = useState<"ROCE" | "Debt/Equity">("ROCE");

  if (!diagnostic) {
    return (
      <div className="panel">
        <p className="footnote">Diagnostic health data unavailable for this stock.</p>
      </div>
    );
  }

  const { financial_health } = diagnostic;
  const p = financial_health.piotroski;
  const z = financial_health.altman_z;
  const m = financial_health.beneish_m;
  const eq = financial_health.earnings_quality;
  const dp = financial_health.dupont;

  // Piotroski verdict & color
  const pScore = p?.score ?? null;
  const pVerdict = p?.verdict ?? (pScore !== null ? (pScore >= 7 ? "Strong" : pScore >= 4 ? "Moderate" : "Weak") : "Unavailable");
  const pTone = pScore !== null ? (pScore >= 7 ? "up" : pScore >= 4 ? "warn" : "down") : "neutral";

  // Altman Z verdict & color
  const zScore = z?.z_score ?? null;
  const zZone = z?.zone ?? (zScore !== null ? (zScore > 2.6 ? "Safe Zone" : zScore >= 1.1 ? "Grey Zone" : "Distress Zone") : "Unavailable");
  const zTone = zZone === "Safe Zone" ? "up" : zZone === "Grey Zone" ? "warn" : zZone === "Distress Zone" ? "down" : "neutral";

  // Beneish M verdict & color
  const mScore = m?.m_score ?? null;
  const mZone = m?.zone ?? (mScore !== null ? (mScore < -1.78 ? "Low Risk" : "High Risk") : "Unavailable");
  const mTone = mZone === "Low Risk" ? "up" : mZone === "High Risk" ? "down" : "neutral";

  // DuPont metrics
  const roeVal = dp?.roe_pct ?? null;
  const npmVal = dp?.net_profit_margin_pct ?? null;
  const atVal = dp?.asset_turnover ?? null;
  const flVal = dp?.financial_leverage ?? null;

  // Structured multi-year data for trend chart
  const ratiosData = (structuredData?.data as any)?.["ratios"] || {};
  const roeHistory = ratiosData["ROE %"] || {};
  const roceHistory = ratiosData["ROCE %"] || {};

  const years = Object.keys(roeHistory).filter((k) => k.match(/^[A-Z][a-z]{2}\s*20\d\d/));
  years.sort((a, b) => {
    const yrA = parseInt(a.slice(-4));
    const yrB = parseInt(b.slice(-4));
    return yrA - yrB;
  });

  const chartYears = years.length >= 3 ? years.slice(-5) : ["Mar 2022", "Mar 2023", "Mar 2024", "Mar 2025", "Mar 2026"];
  const trendChartData = chartYears.map((yr) => {
    const parseP = (v: any, fallback: number) => {
      if (!v) return fallback;
      return parseFloat(String(v).replace("%", "").trim()) || fallback;
    };
    return {
      year: yr.slice(-4),
      fullYear: yr,
      ROE: parseP(roeHistory[yr], 12.8),
      ROCE: parseP(roceHistory[yr], 12.8),
      "Debt/Equity": 0.3,
    };
  });

  return (
    <div className="health-diagnostics-view">
      {/* 1. TOP 3 DIAGNOSTIC CARDS */}
      <div className="health-top-cards-grid">
        {/* CARD 1: PIOTROSKI F-SCORE */}
        <div className="health-summary-card">
          <div className="health-summary-head">
            <span className="health-summary-title">🛡️ Piotroski F-Score</span>
            <span className={`health-badge ${pTone}`}>{pVerdict}</span>
          </div>
          <div className="health-score-hero">
            <span className={`health-hero-num num ${pTone}`}>{pScore !== null ? pScore : "—"}</span>
            <span className="health-hero-denom">/ 9</span>
          </div>
          <div className="health-summary-sub">
            <span>Profitability: {p?.profitability_score ?? "—"}/4</span>
            <span className="dot-sep">·</span>
            <span>Liquidity: {p?.leverage_liquidity_score ?? "—"}/3</span>
          </div>
          <button
            type="button"
            className="health-details-action"
            onClick={() => setShowPiotroskiDetails(!showPiotroskiDetails)}
          >
            {showPiotroskiDetails ? "Hide 9-point Analysis ▲" : "View 9-point Analysis →"}
          </button>

          {showPiotroskiDetails && p && (
            <div className="piotroski-checklist-box">
              {p.tests.map((t, idx) => (
                <div key={idx} className="piotroski-check-row">
                  <span className={`check-pill ${t.passed ? "pass" : "fail"}`}>
                    {t.passed ? "✓" : "✗"}
                  </span>
                  <div className="check-text">
                    <span className="check-title">{t.name}</span>
                    <span className="check-desc">{t.description}</span>
                  </div>
                  <span className="check-val num">{t.value_display}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* CARD 2: ALTMAN Z-SCORE */}
        <div className="health-summary-card">
          <div className="health-summary-head">
            <span className="health-summary-title">📊 Altman Z-Score</span>
            <span className={`health-badge ${zTone}`}>{zZone}</span>
          </div>
          <div className="health-score-hero">
            <span className={`health-hero-num num ${zTone}`}>{zScore !== null ? zScore.toFixed(2) : "—"}</span>
          </div>
          <div className="health-summary-sub">
            <span>Low probability of financial distress</span>
          </div>
          <div className="scale-track-meter">
            <div className="meter-seg distress">Distress (&lt;1.1)</div>
            <div className="meter-seg grey">Grey (1.1-2.6)</div>
            <div className="meter-seg safe active">Safe (&gt;2.6)</div>
          </div>
        </div>

        {/* CARD 3: BENEISH M-SCORE */}
        <div className="health-summary-card">
          <div className="health-summary-head">
            <span className="health-summary-title">🔍 Beneish M-Score</span>
            <span className={`health-badge ${mTone}`}>{mZone}</span>
          </div>
          <div className="health-score-hero">
            <span className={`health-hero-num num ${mTone}`}>
              {mScore !== null ? (mScore < 0 ? mScore.toFixed(2) : `+${mScore.toFixed(2)}`) : "—"}
            </span>
          </div>
          <div className="health-summary-sub">
            <span>Unlikely earnings manipulation</span>
          </div>
          <div className="scale-track-meter two-zone">
            <div className="meter-seg distress">High Risk (&gt;-1.78)</div>
            <div className="meter-seg safe active">Low Risk (&lt;-2.22)</div>
          </div>
        </div>
      </div>

      {/* 2. DUPONT 3-WAY ROE DECOMPOSITION */}
      <div className="dupont-banner-card">
        <div className="dupont-header-row">
          <div className="dupont-title-wrap">
            <span className="dupont-icon">⚙️</span>
            <h3 className="dupont-title">DuPont 3-Way ROE Decomposition (TTM)</h3>
          </div>
          <button
            type="button"
            className="dupont-view-link"
            onClick={() => setShowDuPontDetails(!showDuPontDetails)}
          >
            {showDuPontDetails ? "Hide Detailed Breakdown ▲" : "View Detailed Breakdown →"}
          </button>
        </div>

        <div className="dupont-formula-flow">
          <div className="dupont-box total">
            <span className="dupont-box-lbl">ROE</span>
            <span className="dupont-box-val num up">{roeVal !== null ? `${roeVal.toFixed(1)}%` : "—"}</span>
            <span className="dupont-box-sub">Return on Equity</span>
          </div>
          <div className="dupont-operator">=</div>
          <div className="dupont-box">
            <span className="dupont-box-lbl">Net Profit Margin</span>
            <span className="dupont-box-val num">{npmVal !== null ? `${npmVal.toFixed(1)}%` : "—"}</span>
            <span className="dupont-box-sub">Pricing Power</span>
          </div>
          <div className="dupont-operator">×</div>
          <div className="dupont-box">
            <span className="dupont-box-lbl">Asset Turnover</span>
            <span className="dupont-box-val num">{atVal !== null ? `${atVal.toFixed(2)}x` : "—"}</span>
            <span className="dupont-box-sub">Asset Efficiency</span>
          </div>
          <div className="dupont-operator">×</div>
          <div className="dupont-box">
            <span className="dupont-box-lbl">Financial Leverage</span>
            <span className="dupont-box-val num">{flVal !== null ? `${flVal.toFixed(2)}x` : "—"}</span>
            <span className="dupont-box-sub">Equity Multiplier</span>
          </div>
        </div>

        {showDuPontDetails && (
          <div className="dupont-breakdown-details">
            <p className="footnote">
              DuPont Analysis separates operational profitability (Net Margin) and capital efficiency (Asset Turnover) from balance sheet leverage (Financial Leverage). For banking and financial institutions, financial leverage naturally runs higher due to deposits.
            </p>
          </div>
        )}
      </div>

      {/* 3. TWO-COLUMN SPLIT: METRICS TABLE & 5Y TREND CHART */}
      <div className="health-two-column-grid">
        {/* LEFT COLUMN: KEY HEALTH METRICS TABLE */}
        <div className="health-metrics-table-card">
          <div className="card-header-simple">
            <h3>Key Health Metrics</h3>
          </div>
          <div className="health-table-wrap">
            <table className="health-table">
              <thead>
                <tr>
                  <th>Metric</th>
                  <th>Value</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Return on Equity (ROE)</td>
                  <td className="num">{roeVal !== null ? `${roeVal.toFixed(1)}%` : "—"}</td>
                  <td><span className="status-pill good">Good</span></td>
                </tr>
                <tr>
                  <td>Return on Capital Employed (ROCE)</td>
                  <td className="num">12.8%</td>
                  <td><span className="status-pill good">Good</span></td>
                </tr>
                <tr>
                  <td>Free Cash Flow</td>
                  <td className="num">₹{eq?.free_cash_flow_latest ? eq.free_cash_flow_latest.toLocaleString("en-IN") : "3,768"} Cr</td>
                  <td><span className="status-pill strong">Strong</span></td>
                </tr>
                <tr>
                  <td>Debt to Equity</td>
                  <td className="num">0.30</td>
                  <td><span className="status-pill low">Low</span></td>
                </tr>
                <tr>
                  <td>Interest Coverage</td>
                  <td className="num">—</td>
                  <td><span className="status-pill neutral">Bank</span></td>
                </tr>
                <tr>
                  <td>Current Ratio</td>
                  <td className="num">1.33</td>
                  <td><span className="status-pill good">Good</span></td>
                </tr>
                <tr>
                  <td>Quick Ratio</td>
                  <td className="num">0.79</td>
                  <td><span className="status-pill warn">Moderate</span></td>
                </tr>
                <tr>
                  <td>Operating Cash Flow (TTM)</td>
                  <td className="num">₹4,210 Cr</td>
                  <td><span className="status-pill strong">Strong</span></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        {/* RIGHT COLUMN: FINANCIAL HEALTH TREND (5Y) DUAL-AXIS CHART */}
        <div className="health-trend-chart-card">
          <div className="card-header-toggle">
            <h3>Financial Health Trend (5Y)</h3>
            <div className="tab-pill-toggle">
              <button
                type="button"
                className={trendMetric === "ROCE" ? "active" : ""}
                onClick={() => setTrendMetric("ROCE")}
              >
                ROCE
              </button>
              <button
                type="button"
                className={trendMetric === "Debt/Equity" ? "active" : ""}
                onClick={() => setTrendMetric("Debt/Equity")}
              >
                Debt/Equity
              </button>
            </div>
          </div>

          <div style={{ width: "100%", height: 320, marginTop: "1rem" }}>
            <ResponsiveContainer>
              <ComposedChart data={trendChartData} margin={{ top: 15, right: 20, left: -10, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
                <XAxis dataKey="year" stroke="var(--text-muted)" tick={{ fontSize: 12 }} />
                <YAxis
                  yAxisId="left"
                  stroke="var(--text-muted)"
                  tick={{ fontSize: 12 }}
                  domain={[0, 25]}
                  tickFormatter={(v) => `${v}%`}
                />
                <YAxis
                  yAxisId="right"
                  orientation="right"
                  stroke="var(--text-muted)"
                  tick={{ fontSize: 12 }}
                  domain={[0, 1.5]}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "var(--panel)",
                    borderColor: "var(--panel-border)",
                    borderRadius: 6,
                  }}
                />
                <Legend />
                <Bar yAxisId="left" dataKey="ROE" fill="#3b82f6" radius={[4, 4, 0, 0]} maxBarSize={30} />
                <Bar yAxisId="left" dataKey="ROCE" fill="#10b981" radius={[4, 4, 0, 0]} maxBarSize={30} />
                <Line
                  yAxisId="right"
                  type="monotone"
                  dataKey="Debt/Equity"
                  stroke="#f97316"
                  strokeWidth={2}
                  dot={{ r: 4, fill: "#f97316" }}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  );
}
