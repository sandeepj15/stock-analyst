"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import type { InstrumentSummary } from "../lib/types";
import { bandColor } from "../lib/bands";

interface MlTacticalPlaybookWidgetProps {
  instruments?: InstrumentSummary[];
}

export default function MlTacticalPlaybookWidget({ instruments = [] }: MlTacticalPlaybookWidgetProps) {
  const router = useRouter();
  const [activeScenario, setActiveScenario] = useState<"bullish" | "bearish">("bullish");
  const [showAllBearish, setShowAllBearish] = useState(false);

  const { bullishLeaders, bearishBreakdowns } = useMemo(() => {
    if (!instruments || instruments.length === 0) {
      return { bullishLeaders: [], bearishBreakdowns: [] };
    }

    const bullish = instruments
      .filter(
        (r) =>
          r.ml_forecast_5d_pct !== null &&
          r.ml_forecast_5d_pct >= 1.5 &&
          r.score !== null &&
          r.score >= 60 &&
          (r.momentum_pass === true || (r.distance_from_52w_high_pct !== null && r.distance_from_52w_high_pct >= -15.5))
      )
      .sort((a, b) => (b.ml_forecast_5d_pct ?? 0) - (a.ml_forecast_5d_pct ?? 0));

    const bearish = instruments
      .filter(
        (r) =>
          r.ml_forecast_5d_pct !== null &&
          r.ml_forecast_5d_pct <= -2.5 &&
          r.score !== null &&
          r.score <= 45 &&
          r.distance_from_52w_high_pct !== null &&
          r.distance_from_52w_high_pct <= -20.0
      )
      .sort((a, b) => (a.ml_forecast_5d_pct ?? 0) - (b.ml_forecast_5d_pct ?? 0));

    return { bullishLeaders: bullish, bearishBreakdowns: bearish };
  }, [instruments]);

  const displayedList =
    activeScenario === "bullish"
      ? bullishLeaders
      : showAllBearish
      ? bearishBreakdowns
      : bearishBreakdowns.slice(0, 25);

  return (
    <div className="pulse-card ml-perf-card" style={{ marginTop: "0.5rem" }}>
      {/* Header */}
      <div
        className="pulse-card-head"
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "0.75rem",
          marginBottom: "0.85rem",
        }}
      >
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <span style={{ fontSize: "1.2rem" }}>⚡</span>
            <h3 style={{ margin: 0, fontWeight: 700, letterSpacing: "0.03em" }}>
              Forward 5-Day Tactical Confluence Playbook
            </h3>
          </div>
          <span className="footnote" style={{ marginTop: "0.25rem", display: "inline-block" }}>
            High-probability trade setups filtered by empirical 2,849-forecast confluence rules
          </span>
        </div>

        {/* Regime Toggle Pills */}
        <div style={{ display: "flex", gap: "0.4rem" }}>
          <button
            type="button"
            className={`ml-perf-tab-btn ${activeScenario === "bullish" ? "active" : ""}`}
            onClick={() => setActiveScenario("bullish")}
            style={
              activeScenario === "bullish"
                ? {
                    background: "rgba(16, 185, 129, 0.15)",
                    color: "#10b981",
                    borderColor: "rgba(16, 185, 129, 0.4)",
                    fontWeight: 700,
                  }
                : {}
            }
          >
            🟢 ML Bullish Leaders ({bullishLeaders.length})
          </button>
          <button
            type="button"
            className={`ml-perf-tab-btn ${activeScenario === "bearish" ? "active" : ""}`}
            onClick={() => setActiveScenario("bearish")}
            style={
              activeScenario === "bearish"
                ? {
                    background: "rgba(239, 68, 68, 0.15)",
                    color: "#ef4444",
                    borderColor: "rgba(239, 68, 68, 0.4)",
                    fontWeight: 700,
                  }
                : {}
            }
          >
            🔴 ML Breakdowns / Exits ({bearishBreakdowns.length})
          </button>
        </div>
      </div>

      {/* Playbook Description Banner */}
      <div
        style={{
          padding: "0.6rem 0.85rem",
          borderRadius: "6px",
          marginBottom: "0.85rem",
          fontSize: "0.78rem",
          background:
            activeScenario === "bullish"
              ? "rgba(16, 185, 129, 0.08)"
              : "rgba(239, 68, 68, 0.08)",
          border: `1px solid ${
            activeScenario === "bullish"
              ? "rgba(16, 185, 129, 0.25)"
              : "rgba(239, 68, 68, 0.25)"
          }`,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "0.5rem",
        }}
      >
        <div>
          {activeScenario === "bullish" ? (
            <>
              <strong style={{ color: "#10b981" }}>🟢 Bullish NIFTY Scenario (Long Setups):</strong>{" "}
              Filtered for predicted return ≥ +1.5%, Research Score ≥ 60 (Moderate/Strong band), and Stage 2 confirmed or within 15% of 52W High. Avoids catching falling knives.
            </>
          ) : (
            <>
              <strong style={{ color: "#ef4444" }}>🔴 Bearish NIFTY Scenario (Short / Exit Playbook):</strong>{" "}
              Filtered for predicted return ≤ -2.5%, Research Score ≤ 45 (Weak band), and Drawdown ≤ -20% from 52W High. High-risk breakdown candidates to exit or short.
            </>
          )}
        </div>
        <span style={{ fontSize: "0.72rem", color: "var(--text-muted)" }}>
          Click any stock to open in-depth research
        </span>
      </div>

      {/* Table */}
      <div className="ml-perf-table-wrapper">
        <table className="ml-perf-table">
          <thead>
            <tr>
              <th>Instrument</th>
              <th>Sector</th>
              <th style={{ textAlign: "right" }}>Research Score</th>
              <th style={{ textAlign: "right" }}>Fund Score</th>
              <th style={{ textAlign: "center" }}>Stage 2 / 52W High</th>
              <th style={{ textAlign: "right" }}>5D ML Forecast %</th>
              <th style={{ textAlign: "center" }}>TV Signal</th>
              <th style={{ textAlign: "right" }}>1D %</th>
            </tr>
          </thead>
          <tbody>
            {displayedList.map((stock) => {
              const mlSign = (stock.ml_forecast_5d_pct ?? 0) > 0 ? "+" : "";
              const daySign = (stock.day_change_pct ?? 0) > 0 ? "+" : "";
              const scoreCol = stock.band ? bandColor(stock.band) : "inherit";
              const fundCol = stock.fundamental_band ? bandColor(stock.fundamental_band) : "inherit";

              return (
                <tr
                  key={stock.symbol}
                  className="ml-perf-row"
                  onClick={() => router.push(`/stocks/${stock.symbol}`)}
                  title={`Open research dossier for ${stock.symbol}`}
                >
                  <td>
                    <div style={{ display: "flex", flexDirection: "column" }}>
                      <span style={{ fontWeight: 700, color: "var(--accent, #3b82f6)" }}>
                        {stock.symbol}
                      </span>
                      <span
                        style={{
                          fontSize: "0.7rem",
                          color: "var(--text-muted)",
                          maxWidth: "200px",
                          whiteSpace: "nowrap",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                        }}
                      >
                        {stock.company_name}
                      </span>
                    </div>
                  </td>
                  <td>
                    <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
                      {stock.sector ?? "—"}
                    </span>
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <span className="num" style={{ fontWeight: 700, color: scoreCol }}>
                      {stock.score !== null ? stock.score.toFixed(0) : "—"}
                    </span>
                    {stock.band && (
                      <span style={{ fontSize: "0.68rem", color: scoreCol, marginLeft: "4px" }}>
                        ({stock.band})
                      </span>
                    )}
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <span className="num" style={{ fontWeight: 700, color: fundCol }}>
                      {stock.fundamental_score !== null ? stock.fundamental_score.toFixed(0) : "—"}
                    </span>
                  </td>
                  <td style={{ textAlign: "center" }}>
                    {stock.momentum_pass === true ? (
                      <span
                        style={{
                          padding: "2px 6px",
                          borderRadius: "4px",
                          fontSize: "0.7rem",
                          fontWeight: 700,
                          background: "rgba(16, 185, 129, 0.15)",
                          color: "#10b981",
                        }}
                      >
                        ✓ Stage 2
                      </span>
                    ) : stock.distance_from_52w_high_pct !== null ? (
                      <span
                        className="num"
                        style={{
                          fontSize: "0.72rem",
                          color: stock.distance_from_52w_high_pct > -15 ? "var(--text-muted)" : "#ef4444",
                        }}
                      >
                        {stock.distance_from_52w_high_pct.toFixed(1)}%
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <span
                      className={`num ${(stock.ml_forecast_5d_pct ?? 0) >= 0 ? "up" : "down"}`}
                      style={{ fontWeight: 700, fontSize: "0.85rem" }}
                    >
                      {mlSign}
                      {stock.ml_forecast_5d_pct !== null ? stock.ml_forecast_5d_pct.toFixed(2) : "0.00"}%
                    </span>
                  </td>
                  <td style={{ textAlign: "center" }}>
                    <span style={{ fontSize: "0.72rem" }}>
                      {stock.tv_momentum_flag?.startsWith("STRONG_BUY") ? (
                        <span style={{ color: "#10b981", fontWeight: 700 }}>🟢 Strong Buy</span>
                      ) : stock.tv_momentum_flag?.startsWith("STRONG_SELL") ? (
                        <span style={{ color: "#ef4444", fontWeight: 700 }}>🔴 Strong Sell</span>
                      ) : (
                        <span style={{ color: "var(--text-muted)" }}>{stock.tv_signal_1d ?? "—"}</span>
                      )}
                    </span>
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <span
                      className={`num ${(stock.day_change_pct ?? 0) >= 0 ? "up" : "down"}`}
                      style={{ fontSize: "0.82rem" }}
                    >
                      {daySign}
                      {stock.day_change_pct !== null ? stock.day_change_pct.toFixed(2) : "0.00"}%
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination Footer for Bearish Scenario */}
      {activeScenario === "bearish" && bearishBreakdowns.length > 25 && (
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginTop: "0.75rem",
            paddingTop: "0.5rem",
            borderTop: "1px solid var(--panel-border)",
          }}
        >
          <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
            Showing {displayedList.length} of {bearishBreakdowns.length} high-risk breakdown candidates
          </span>
          <button
            type="button"
            className="ml-perf-tab-btn"
            onClick={() => setShowAllBearish((prev) => !prev)}
            style={{ fontSize: "0.75rem", padding: "4px 10px" }}
          >
            {showAllBearish ? "Show Top 25 Only" : `View All ${bearishBreakdowns.length} Breakdowns`}
          </button>
        </div>
      )}
    </div>
  );
}
