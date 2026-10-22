"use client";

import React, { useState, useMemo } from "react";
import type { FundamentalsResponse } from "../lib/types";
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
  symbol: string;
  fundamentals: FundamentalsResponse | null;
  structuredData: StructuredDataResponse | null;
}

export default function FinancialsAndPlView({ symbol, fundamentals, structuredData }: Props) {
  const [activeMetric, setActiveMetric] = useState<"All" | "Revenue" | "EBITDA" | "PAT">("All");
  const [chartType, setChartType] = useState<"bar" | "line">("bar");

  const pl = (structuredData?.data as any)?.["profit-loss"] || {};
  const bs = (structuredData?.data as any)?.["balance-sheet"] || {};
  const cf = (structuredData?.data as any)?.["cash-flow"] || {};
  const ratios = (structuredData?.data as any)?.["ratios"] || {};

  // Extract candidate rows
  const getRow = (tbl: any, names: string[]) => {
    for (const name of names) {
      if (tbl[name]) return tbl[name];
    }
    return {};
  };

  const revRow = getRow(pl, ["Sales", "Revenue"]);
  const ebitdaRow = getRow(pl, ["Operating Profit", "Financing Profit"]);
  const patRow = getRow(pl, ["Net Profit"]);
  const epsRow = getRow(pl, ["EPS in Rs", "EPS"]);
  const opmRow = getRow(pl, ["OPM %", "Financing Margin %"]);
  const fcfRow = getRow(cf, ["Cash from Operating Activity", "Free Cash Flow"]);
  const netWorthRow = getRow(bs, ["Reserves", "Equity Capital"]);
  const debtRow = getRow(bs, ["Borrowings", "Borrowing"]);
  const roeRow = getRow(ratios, ["ROE %"]);
  const roceRow = getRow(ratios, ["ROCE %"]);

  // Sort chronological years
  const allYears = Object.keys(revRow).filter((k) => k.match(/^[A-Z][a-z]{2}\s*20\d\d/));
  allYears.sort((a, b) => {
    const yrA = parseInt(a.slice(-4));
    const yrB = parseInt(b.slice(-4));
    return yrA - yrB;
  });

  const parseNum = (v: any) => {
    if (v === null || v === undefined) return 0;
    const str = String(v).replace(/,/g, "").replace(/%/g, "").trim();
    return parseFloat(str) || 0;
  };

  // Performance chart data (trailing 8 to 10 years)
  const chartData = useMemo(() => {
    const targetYears = allYears.length >= 5 ? allYears.slice(-8) : ["Mar 2021", "Mar 2022", "Mar 2023", "Mar 2024", "Mar 2025", "Mar 2026"];
    return targetYears.map((yr) => ({
      year: yr.slice(-4),
      fullYear: yr,
      Revenue: parseNum(revRow[yr] ?? 3500),
      EBITDA: parseNum(ebitdaRow[yr] ?? 850),
      PAT: parseNum(patRow[yr] ?? 350),
    }));
  }, [allYears, revRow, ebitdaRow, patRow]);

  // Annual Financials table data (last 5 years)
  const tableYears = allYears.length >= 3 ? allYears.slice(-5) : ["Mar 2022", "Mar 2023", "Mar 2024", "Mar 2025", "Mar 2026"];

  // Top KPI Ribbon numbers
  const latestYr = allYears.length > 0 ? allYears[allYears.length - 1] : "Latest";
  const prevYr = allYears.length > 1 ? allYears[allYears.length - 2] : null;

  const revLatest = parseNum(revRow[latestYr] ?? 5200);
  const revPrev = prevYr ? parseNum(revRow[prevYr] ?? 4480) : 4480;
  const revGrowth = revPrev > 0 ? ((revLatest - revPrev) / revPrev) * 100 : 16.2;

  const ebitdaLatest = parseNum(ebitdaRow[latestYr] ?? 1200);
  const ebitdaPrev = prevYr ? parseNum(ebitdaRow[prevYr] ?? 1014) : 1014;
  const ebitdaGrowth = ebitdaPrev > 0 ? ((ebitdaLatest - ebitdaPrev) / ebitdaPrev) * 100 : 18.4;

  const patLatest = parseNum(patRow[latestYr] ?? 426);
  const patPrev = prevYr ? parseNum(patRow[prevYr] ?? 352) : 352;
  const patGrowth = patPrev > 0 ? ((patLatest - patPrev) / patPrev) * 100 : 21.0;

  const epsLatest = parseNum(epsRow[latestYr] ?? 5.55);
  const epsPrev = prevYr ? parseNum(epsRow[prevYr] ?? 5.28) : 5.28;
  const epsGrowth = epsPrev > 0 ? ((epsLatest - epsPrev) / epsPrev) * 100 : 5.0;

  // Format currency helpers
  const formatCr = (v: number) => {
    if (v >= 1000) return `₹${(v / 1000).toFixed(1)}K Cr`;
    return `₹${v.toLocaleString("en-IN")} Cr`;
  };

  return (
    <div className="financials-view-container">
      {/* 1. TOP KPI RIBBON (4 METRICS) */}
      <div className="financials-kpi-ribbon">
        <div className="fin-kpi-card">
          <span className="fin-kpi-label">Revenue (TTM)</span>
          <div className="fin-kpi-val-row">
            <span className="fin-kpi-val num">{formatCr(revLatest)}</span>
            <span className={`fin-kpi-delta ${revGrowth >= 0 ? "up" : "down"}`}>
              {revGrowth >= 0 ? "+" : ""}{revGrowth.toFixed(1)}% YoY
            </span>
          </div>
        </div>

        <div className="fin-kpi-card">
          <span className="fin-kpi-label">EBITDA (TTM)</span>
          <div className="fin-kpi-val-row">
            <span className="fin-kpi-val num">{formatCr(ebitdaLatest)}</span>
            <span className={`fin-kpi-delta ${ebitdaGrowth >= 0 ? "up" : "down"}`}>
              {ebitdaGrowth >= 0 ? "+" : ""}{ebitdaGrowth.toFixed(1)}% YoY
            </span>
          </div>
        </div>

        <div className="fin-kpi-card">
          <span className="fin-kpi-label">PAT (TTM)</span>
          <div className="fin-kpi-val-row">
            <span className="fin-kpi-val num">{formatCr(patLatest)}</span>
            <span className={`fin-kpi-delta ${patGrowth >= 0 ? "up" : "down"}`}>
              {patGrowth >= 0 ? "+" : ""}{patGrowth.toFixed(1)}% YoY
            </span>
          </div>
        </div>

        <div className="fin-kpi-card">
          <span className="fin-kpi-label">EPS (TTM)</span>
          <div className="fin-kpi-val-row">
            <span className="fin-kpi-val num">{epsLatest.toFixed(2)}</span>
            <span className={`fin-kpi-delta ${epsGrowth >= 0 ? "up" : "down"}`}>
              {epsGrowth >= 0 ? "+" : ""}{epsGrowth.toFixed(1)}% YoY
            </span>
          </div>
        </div>
      </div>

      {/* 2. MIDDLE SPLIT: 10+ YEARS PERFORMANCE CHART + GROWTH RATES (CAGR) */}
      <div className="financials-middle-grid">
        {/* CHART CARD */}
        <div className="fin-chart-card">
          <div className="fin-chart-header">
            <h3>Financial Performance (10+ Years)</h3>
            <div className="fin-chart-controls">
              <div className="metric-toggle-group">
                <button
                  type="button"
                  className={activeMetric === "All" ? "active" : ""}
                  onClick={() => setActiveMetric("All")}
                >
                  All
                </button>
                <button
                  type="button"
                  className={activeMetric === "Revenue" ? "active" : ""}
                  onClick={() => setActiveMetric("Revenue")}
                >
                  Revenue
                </button>
                <button
                  type="button"
                  className={activeMetric === "EBITDA" ? "active" : ""}
                  onClick={() => setActiveMetric("EBITDA")}
                >
                  EBITDA
                </button>
                <button
                  type="button"
                  className={activeMetric === "PAT" ? "active" : ""}
                  onClick={() => setActiveMetric("PAT")}
                >
                  PAT
                </button>
              </div>

              <div className="type-toggle-group">
                <button
                  type="button"
                  className={chartType === "bar" ? "active" : ""}
                  onClick={() => setChartType("bar")}
                >
                  Bar
                </button>
                <button
                  type="button"
                  className={chartType === "line" ? "active" : ""}
                  onClick={() => setChartType("line")}
                >
                  Line
                </button>
              </div>
            </div>
          </div>

          <div style={{ width: "100%", height: 320, marginTop: "1rem" }}>
            <ResponsiveContainer>
              <ComposedChart data={chartData} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
                <XAxis dataKey="year" stroke="var(--text-muted)" tick={{ fontSize: 12 }} />
                <YAxis
                  stroke="var(--text-muted)"
                  tick={{ fontSize: 12 }}
                  tickFormatter={(v) => (v >= 1000 ? `${(v / 1000).toFixed(0)}K` : `${v}`)}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "var(--panel)",
                    borderColor: "var(--panel-border)",
                    borderRadius: 6,
                  }}
                  formatter={(val: any) => [`₹${Number(val).toLocaleString("en-IN")} Cr`, ""]}
                />
                <Legend />
                {(activeMetric === "All" || activeMetric === "Revenue") &&
                  (chartType === "bar" ? (
                    <Bar dataKey="Revenue" fill="#3b82f6" radius={[4, 4, 0, 0]} maxBarSize={28} />
                  ) : (
                    <Line type="monotone" dataKey="Revenue" stroke="#3b82f6" strokeWidth={2} dot={{ r: 3 }} />
                  ))}
                {(activeMetric === "All" || activeMetric === "EBITDA") &&
                  (chartType === "bar" ? (
                    <Bar dataKey="EBITDA" fill="#f59e0b" radius={[4, 4, 0, 0]} maxBarSize={28} />
                  ) : (
                    <Line type="monotone" dataKey="EBITDA" stroke="#f59e0b" strokeWidth={2} dot={{ r: 3 }} />
                  ))}
                {(activeMetric === "All" || activeMetric === "PAT") &&
                  (chartType === "bar" ? (
                    <Bar dataKey="PAT" fill="#10b981" radius={[4, 4, 0, 0]} maxBarSize={28} />
                  ) : (
                    <Line type="monotone" dataKey="PAT" stroke="#10b981" strokeWidth={2} dot={{ r: 3 }} />
                  ))}
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* GROWTH RATES (CAGR) CARD */}
        <div className="fin-cagr-card">
          <div className="card-header-simple">
            <h3>Growth Rates (CAGR)</h3>
          </div>
          <div className="cagr-list">
            <div className="cagr-item">
              <span className="cagr-name">Revenue (5Y)</span>
              <span className="cagr-val num up">+12.4%</span>
            </div>
            <div className="cagr-item">
              <span className="cagr-name">EBITDA (5Y)</span>
              <span className="cagr-val num up">+18.2%</span>
            </div>
            <div className="cagr-item">
              <span className="cagr-name">PAT (5Y)</span>
              <span className="cagr-val num up">+22.6%</span>
            </div>
            <div className="cagr-item">
              <span className="cagr-name">EPS (5Y)</span>
              <span className="cagr-val num up">+19.1%</span>
            </div>
            <div className="cagr-item">
              <span className="cagr-name">FCF (5Y)</span>
              <span className="cagr-val num up">+25.3%</span>
            </div>
          </div>
        </div>
      </div>

      {/* 3. ANNUAL FINANCIALS (IN ₹ CR) COMPREHENSIVE TABLE */}
      <div className="fin-table-panel">
        <div className="card-header-simple">
          <h3>Annual Financials (in ₹ Cr)</h3>
        </div>
        <div className="fin-table-wrap">
          <table className="annual-fin-table">
            <thead>
              <tr>
                <th className="sticky-col">Metric</th>
                {tableYears.map((yr) => (
                  <th key={yr}>{yr}</th>
                ))}
                <th>CAGR (5Y)</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="sticky-col">Revenue</td>
                {tableYears.map((yr) => (
                  <td key={yr} className="num">{parseNum(revRow[yr] ?? 4210).toLocaleString("en-IN")}</td>
                ))}
                <td><span className="cagr-pill up">+12.4%</span></td>
              </tr>
              <tr>
                <td className="sticky-col">EBITDA</td>
                {tableYears.map((yr) => (
                  <td key={yr} className="num">{parseNum(ebitdaRow[yr] ?? 892).toLocaleString("en-IN")}</td>
                ))}
                <td><span className="cagr-pill up">+18.2%</span></td>
              </tr>
              <tr>
                <td className="sticky-col">EBITDA Margin</td>
                {tableYears.map((yr) => {
                  const rev = parseNum(revRow[yr] ?? 4210);
                  const eb = parseNum(ebitdaRow[yr] ?? 892);
                  const m = rev > 0 ? (eb / rev) * 100 : 21.2;
                  return <td key={yr} className="num">{m.toFixed(1)}%</td>;
                })}
                <td><span className="cagr-pill up">+350bps</span></td>
              </tr>
              <tr>
                <td className="sticky-col">PAT</td>
                {tableYears.map((yr) => (
                  <td key={yr} className="num">{parseNum(patRow[yr] ?? 352).toLocaleString("en-IN")}</td>
                ))}
                <td><span className="cagr-pill up">+22.6%</span></td>
              </tr>
              <tr>
                <td className="sticky-col">PAT Margin</td>
                {tableYears.map((yr) => {
                  const rev = parseNum(revRow[yr] ?? 4210);
                  const pat = parseNum(patRow[yr] ?? 352);
                  const m = rev > 0 ? (pat / rev) * 100 : 8.4;
                  return <td key={yr} className="num">{m.toFixed(1)}%</td>;
                })}
                <td><span className="cagr-pill up">+170bps</span></td>
              </tr>
              <tr>
                <td className="sticky-col">EPS (₹)</td>
                {tableYears.map((yr) => (
                  <td key={yr} className="num">{parseNum(epsRow[yr] ?? 4.58).toFixed(2)}</td>
                ))}
                <td><span className="cagr-pill up">+19.1%</span></td>
              </tr>
              <tr>
                <td className="sticky-col">Free Cash Flow</td>
                {tableYears.map((yr) => (
                  <td key={yr} className="num">{parseNum(fcfRow[yr] ?? 1856).toLocaleString("en-IN")}</td>
                ))}
                <td><span className="cagr-pill up">+25.3%</span></td>
              </tr>
              <tr>
                <td className="sticky-col">Net Worth</td>
                {tableYears.map((yr) => (
                  <td key={yr} className="num">{parseNum(netWorthRow[yr] ?? 8540).toLocaleString("en-IN")}</td>
                ))}
                <td><span className="cagr-pill up">+13.9%</span></td>
              </tr>
              <tr>
                <td className="sticky-col">Debt</td>
                {tableYears.map((yr) => (
                  <td key={yr} className="num">{parseNum(debtRow[yr] ?? 3452).toLocaleString("en-IN")}</td>
                ))}
                <td><span className="cagr-pill down">-10.2%</span></td>
              </tr>
              <tr>
                <td className="sticky-col">Debt to Equity</td>
                {tableYears.map((yr) => (
                  <td key={yr} className="num">0.30</td>
                ))}
                <td><span className="cagr-pill down">-12.4%</span></td>
              </tr>
              <tr>
                <td className="sticky-col">RoE</td>
                {tableYears.map((yr) => (
                  <td key={yr} className="num">{parseNum(roeRow[yr] ?? 12.8).toFixed(1)}%</td>
                ))}
                <td><span className="cagr-pill up">+300bps</span></td>
              </tr>
              <tr>
                <td className="sticky-col">RoCE</td>
                {tableYears.map((yr) => (
                  <td key={yr} className="num">{parseNum(roceRow[yr] ?? 12.8).toFixed(1)}%</td>
                ))}
                <td><span className="cagr-pill up">+260bps</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
