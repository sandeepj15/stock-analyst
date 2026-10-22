"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getMlPerformance } from "../lib/api";
import type { ForecastCallItem, MlPerformanceResponse, PrecisionTier } from "../lib/types";

type CallTab = "bullish" | "bearish" | "pinpoint";

export default function MlPerformanceWidget() {
  const router = useRouter();
  const [data, setData] = useState<MlPerformanceResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [activeTab, setActiveTab] = useState<CallTab>("bullish");

  useEffect(() => {
    let mounted = true;
    getMlPerformance()
      .then((res) => {
        if (mounted) {
          setData(res);
          setLoading(false);
        }
      })
      .catch((err) => {
        console.error("Failed to load ML performance:", err);
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  if (loading) {
    return (
      <div className="pulse-card ml-perf-card">
        <div className="pulse-card-head">
          <h3>ML Forecast Accuracy & Performance</h3>
          <span className="footnote">Evaluating historical predictions…</span>
        </div>
        <p className="footnote" style={{ padding: "1.5rem 0", textAlign: "center" }}>
          Loading evaluation metrics…
        </p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="pulse-card ml-perf-card">
        <div className="pulse-card-head">
          <h3>ML Forecast Accuracy & Performance</h3>
        </div>
        <p className="footnote" style={{ padding: "1rem 0" }}>
          ML forecast evaluations run weekly upon market close every Friday. No realized forecast evaluations found yet.
        </p>
      </div>
    );
  }

  const highPrecisionCount = (data.tiers.find((t) => t.tier === "under_2")?.count || 0) +
    (data.tiers.find((t) => t.tier === "2_to_5")?.count || 0);
  const highPrecisionPct = data.evaluated_count > 0 ? ((highPrecisionCount / data.evaluated_count) * 100).toFixed(1) : "0";

  const callsToDisplay: ForecastCallItem[] =
    activeTab === "bullish"
      ? data.top_bullish_calls
      : activeTab === "bearish"
      ? data.top_bearish_calls
      : data.pinpoint_calls;

  return (
    <div className="pulse-card ml-perf-card">
      {/* Header */}
      <div className="pulse-card-head" style={{ marginBottom: "0.85rem" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <span style={{ fontSize: "1.1rem" }}>🤖</span>
            <h3 style={{ margin: 0, fontWeight: 700, letterSpacing: "0.05em" }}>
              5D ML Forecast Accuracy & Directional Alpha
            </h3>
          </div>
          <span className="footnote" style={{ marginTop: "0.2rem", display: "inline-block" }}>
            Realized week: <strong>{data.eval_start_date ?? data.as_of_date} → {data.eval_end_date ?? "Latest"}</strong> ·{" "}
            <strong>{data.evaluated_count.toLocaleString()}</strong> NSE stocks evaluated
          </span>
        </div>
        <span
          style={{
            padding: "0.2rem 0.6rem",
            borderRadius: "6px",
            fontSize: "0.75rem",
            fontWeight: 700,
            background: data.directional_win_rate_pct >= 50 ? "rgba(34, 197, 94, 0.15)" : "rgba(239, 68, 68, 0.15)",
            color: data.directional_win_rate_pct >= 50 ? "var(--up, #22c55e)" : "var(--down, #ef4444)",
            border: `1px solid ${data.directional_win_rate_pct >= 50 ? "rgba(34, 197, 94, 0.3)" : "rgba(239, 68, 68, 0.3)"}`,
          }}
        >
          {data.directional_win_rate_pct}% Directional Win Rate
        </span>
      </div>

      {/* KPI Overview Grid */}
      <div className="ml-perf-kpi-grid">
        {/* KPI 1: Win Rate */}
        <div className="ml-perf-kpi-card">
          <span className="ml-perf-kpi-label">Directional Calls</span>
          <div className="ml-perf-kpi-val" style={{ color: "var(--up, #22c55e)" }}>
            {data.directional_win_rate_pct}%
          </div>
          <span className="ml-perf-kpi-sub">
            <strong style={{ color: "var(--up, #22c55e)" }}>{data.correct_count} Right</strong> /{" "}
            <span style={{ color: "var(--down, #ef4444)" }}>{data.incorrect_count} Wrong</span>
          </span>
        </div>

        {/* KPI 2: Median MAPE */}
        <div className="ml-perf-kpi-card">
          <span className="ml-perf-kpi-label">Median Forecast Error</span>
          <div className="ml-perf-kpi-val">
            {data.median_mape_pct.toFixed(2)}%
          </div>
          <span className="ml-perf-kpi-sub">
            Average MAPE: {data.avg_mape_pct.toFixed(2)}%
          </span>
        </div>

        {/* KPI 3: High Precision Coverage */}
        <div className="ml-perf-kpi-card">
          <span className="ml-perf-kpi-label">High Precision (&lt;5% Error)</span>
          <div className="ml-perf-kpi-val" style={{ color: "var(--accent, #3b82f6)" }}>
            {highPrecisionPct}%
          </div>
          <span className="ml-perf-kpi-sub">
            {highPrecisionCount} of {data.evaluated_count} stocks
          </span>
        </div>

        {/* KPI 4: Pinpoint Win Rate */}
        <div className="ml-perf-kpi-card">
          <span className="ml-perf-kpi-label">Pinpoint Tier Win Rate</span>
          <div className="ml-perf-kpi-val" style={{ color: "#10b981" }}>
            {data.tiers[0]?.win_rate_pct ?? 0}%
          </div>
          <span className="ml-perf-kpi-sub">
            On stocks with &lt;2% error margin
          </span>
        </div>
      </div>

      {/* Distribution Tiers Section */}
      <div style={{ marginTop: "1rem", marginBottom: "0.5rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.4rem" }}>
          <span style={{ fontSize: "0.75rem", textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--text-muted)", fontWeight: 600 }}>
            Precision Error Distribution (MAPE Tiers)
          </span>
          <span style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}>
            Lower error = tighter price projection
          </span>
        </div>

        {/* Multi-segment stacked bar */}
        <div
          style={{
            display: "flex",
            height: "12px",
            borderRadius: "6px",
            overflow: "hidden",
            background: "var(--surface-alt, #1e293b)",
            marginBottom: "0.6rem",
          }}
        >
          {data.tiers.map((t, idx) => {
            const colors = [
              "linear-gradient(90deg, #10b981, #059669)", // under 2%
              "linear-gradient(90deg, #3b82f6, #2563eb)", // 2-5%
              "linear-gradient(90deg, #f59e0b, #d97706)", // 5-10%
              "linear-gradient(90deg, #ef4444, #dc2626)", // >10%
            ];
            return (
              <div
                key={t.tier}
                title={`${t.label}: ${t.count} stocks (${t.pct}%)`}
                style={{
                  width: `${t.pct}%`,
                  background: colors[idx % colors.length],
                }}
              />
            );
          })}
        </div>

        {/* Tier Cards Row */}
        <div className="ml-perf-tier-grid">
          {data.tiers.map((t, idx) => {
            const badgeColors = ["#10b981", "#3b82f6", "#f59e0b", "#ef4444"];
            return (
              <div key={t.tier} className="ml-perf-tier-card">
                <div style={{ display: "flex", alignItems: "center", gap: "0.35rem", marginBottom: "0.2rem" }}>
                  <span
                    style={{
                      width: "8px",
                      height: "8px",
                      borderRadius: "50%",
                      background: badgeColors[idx % badgeColors.length],
                      display: "inline-block",
                    }}
                  />
                  <span style={{ fontSize: "0.75rem", fontWeight: 700 }}>{t.label}</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                  <span style={{ fontSize: "0.85rem", fontWeight: 700 }} className="num">
                    {t.count} <span style={{ fontSize: "0.68rem", fontWeight: 400, color: "var(--text-muted)" }}>({t.pct}%)</span>
                  </span>
                  <span
                    style={{
                      fontSize: "0.72rem",
                      fontWeight: 600,
                      color: t.win_rate_pct >= 50 ? "var(--up, #22c55e)" : "var(--text-muted)",
                    }}
                  >
                    {t.win_rate_pct}% win
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Interactive Best / Bearish / Pinpoint Calls Showcase */}
      <div style={{ marginTop: "1.2rem", borderTop: "1px solid var(--panel-border)", paddingTop: "0.85rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.5rem", marginBottom: "0.75rem" }}>
          <div style={{ display: "flex", gap: "0.4rem" }}>
            <button
              type="button"
              className={`ml-perf-tab-btn ${activeTab === "bullish" ? "active" : ""}`}
              onClick={() => setActiveTab("bullish")}
            >
              🚀 Top Bullish Hits
            </button>
            <button
              type="button"
              className={`ml-perf-tab-btn ${activeTab === "bearish" ? "active" : ""}`}
              onClick={() => setActiveTab("bearish")}
            >
              🔻 Top Bearish Hits
            </button>
            <button
              type="button"
              className={`ml-perf-tab-btn ${activeTab === "pinpoint" ? "active" : ""}`}
              onClick={() => setActiveTab("pinpoint")}
            >
              🎯 Pinpoint Matches
            </button>
          </div>
          <span style={{ fontSize: "0.72rem", color: "var(--text-muted)" }}>
            Click any stock to inspect full technical & ML chart
          </span>
        </div>

        {/* Calls Table */}
        <div className="ml-perf-table-wrapper">
          <table className="ml-perf-table">
            <thead>
              <tr>
                <th>Stock</th>
                <th style={{ textAlign: "right" }}>Predicted 5D %</th>
                <th style={{ textAlign: "right" }}>Actual Realized %</th>
                <th style={{ textAlign: "right" }}>Error (MAPE)</th>
                <th style={{ textAlign: "center" }}>Direction</th>
              </tr>
            </thead>
            <tbody>
              {callsToDisplay.map((call) => {
                const predSign = call.pred_return_pct > 0 ? "+" : "";
                const actSign = call.act_return_pct > 0 ? "+" : "";
                const isCorrect = (call.pred_return_pct >= 0) === (call.act_return_pct >= 0);
                return (
                  <tr
                    key={call.symbol}
                    className="ml-perf-row"
                    onClick={() => router.push(`/stocks/${call.symbol}`)}
                    title={`View ${call.company_name} (${call.symbol})`}
                  >
                    <td>
                      <div style={{ display: "flex", flexDirection: "column" }}>
                        <span style={{ fontWeight: 700, color: "var(--accent, #3b82f6)" }}>
                          {call.symbol}
                        </span>
                        <span
                          style={{
                            fontSize: "0.7rem",
                            color: "var(--text-muted)",
                            maxWidth: "240px",
                            whiteSpace: "nowrap",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                          }}
                        >
                          {call.company_name}
                        </span>
                      </div>
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <span className={`num ${call.pred_return_pct > 0 ? "up" : call.pred_return_pct < 0 ? "down" : "flat"}`}>
                        {predSign}{call.pred_return_pct.toFixed(2)}%
                      </span>
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <span className={`num ${call.act_return_pct > 0 ? "up" : call.act_return_pct < 0 ? "down" : "flat"}`} style={{ fontWeight: 700 }}>
                        {actSign}{call.act_return_pct.toFixed(2)}%
                      </span>
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <span className="num" style={{ fontSize: "0.82rem", color: call.mape_pct < 2 ? "#10b981" : call.mape_pct < 5 ? "#3b82f6" : "inherit" }}>
                        {call.mape_pct.toFixed(2)}%
                      </span>
                    </td>
                    <td style={{ textAlign: "center" }}>
                      <span
                        style={{
                          padding: "2px 6px",
                          borderRadius: "4px",
                          fontSize: "0.7rem",
                          fontWeight: 700,
                          background: isCorrect ? "rgba(34, 197, 94, 0.15)" : "rgba(239, 68, 68, 0.15)",
                          color: isCorrect ? "var(--up, #22c55e)" : "var(--down, #ef4444)",
                        }}
                      >
                        {isCorrect ? "✓ RIGHT" : "✗ WRONG"}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
