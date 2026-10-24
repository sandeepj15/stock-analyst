"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import type { InstrumentSummary } from "../lib/types";
import { bandColor } from "../lib/bands";

interface MlTacticalPlaybookWidgetProps {
  instruments?: InstrumentSummary[];
}

type PlaybookSortKey =
  | "symbol"
  | "sector"
  | "score"
  | "fundamental_score"
  | "distance_from_52w_high_pct"
  | "ml_forecast_5d_pct"
  | "tv_signal"
  | "day_change_pct";

export default function MlTacticalPlaybookWidget({ instruments = [] }: MlTacticalPlaybookWidgetProps) {
  const router = useRouter();
  const [activeScenario, setActiveScenario] = useState<"bullish" | "bearish">("bullish");
  const [showAllBearish, setShowAllBearish] = useState(false);

  // Sorting state: default to forecast % descending for bullish, forecast % ascending for bearish
  const [sortKey, setSortKey] = useState<PlaybookSortKey>("ml_forecast_5d_pct");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");

  // Handle scenario toggle with appropriate default sort
  const handleScenarioChange = (scenario: "bullish" | "bearish") => {
    setActiveScenario(scenario);
    if (scenario === "bullish") {
      setSortKey("ml_forecast_5d_pct");
      setSortOrder("desc");
    } else {
      setSortKey("ml_forecast_5d_pct");
      setSortOrder("asc");
    }
  };

  const handleHeaderSort = (key: PlaybookSortKey) => {
    if (sortKey === key) {
      setSortOrder((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      // Numerical fields default to desc; text fields default to asc
      const isNum = [
        "score",
        "fundamental_score",
        "distance_from_52w_high_pct",
        "ml_forecast_5d_pct",
        "day_change_pct",
      ].includes(key);
      setSortOrder(isNum ? "desc" : "asc");
    }
  };

  const { bullishLeaders, bearishBreakdowns } = useMemo(() => {
    if (!instruments || instruments.length === 0) {
      return { bullishLeaders: [], bearishBreakdowns: [] };
    }

    const bullish = instruments.filter(
      (r) =>
        r.ml_forecast_5d_pct !== null &&
        r.ml_forecast_5d_pct >= 1.5 &&
        r.score !== null &&
        r.score >= 60 &&
        (r.momentum_pass === true || (r.distance_from_52w_high_pct !== null && r.distance_from_52w_high_pct >= -15.5))
    );

    const bearish = instruments.filter(
      (r) =>
        r.ml_forecast_5d_pct !== null &&
        r.ml_forecast_5d_pct <= -2.5 &&
        r.score !== null &&
        r.score <= 45 &&
        r.distance_from_52w_high_pct !== null &&
        r.distance_from_52w_high_pct <= -20.0
    );

    return { bullishLeaders: bullish, bearishBreakdowns: bearish };
  }, [instruments]);

  // Sort the active dataset
  const sortedList = useMemo(() => {
    const list = activeScenario === "bullish" ? [...bullishLeaders] : [...bearishBreakdowns];

    list.sort((a, b) => {
      let valA: string | number | null = null;
      let valB: string | number | null = null;

      if (sortKey === "symbol") {
        valA = a.symbol;
        valB = b.symbol;
      } else if (sortKey === "sector") {
        valA = a.sector ?? "";
        valB = b.sector ?? "";
      } else if (sortKey === "score") {
        valA = a.score;
        valB = b.score;
      } else if (sortKey === "fundamental_score") {
        valA = a.fundamental_score;
        valB = b.fundamental_score;
      } else if (sortKey === "distance_from_52w_high_pct") {
        valA = a.distance_from_52w_high_pct;
        valB = b.distance_from_52w_high_pct;
      } else if (sortKey === "ml_forecast_5d_pct") {
        valA = a.ml_forecast_5d_pct;
        valB = b.ml_forecast_5d_pct;
      } else if (sortKey === "tv_signal") {
        valA = a.tv_momentum_flag ?? a.tv_signal_1d ?? "";
        valB = b.tv_momentum_flag ?? b.tv_signal_1d ?? "";
      } else if (sortKey === "day_change_pct") {
        valA = a.day_change_pct;
        valB = b.day_change_pct;
      }

      if (valA === null && valB === null) return 0;
      if (valA === null) return 1;
      if (valB === null) return -1;

      let cmp = 0;
      if (typeof valA === "string" && typeof valB === "string") {
        cmp = valA.localeCompare(valB);
      } else {
        cmp = (valA as number) < (valB as number) ? -1 : (valA as number) > (valB as number) ? 1 : 0;
      }

      return sortOrder === "asc" ? cmp : -cmp;
    });

    return list;
  }, [activeScenario, bullishLeaders, bearishBreakdowns, sortKey, sortOrder]);

  const displayedList =
    activeScenario === "bullish"
      ? sortedList
      : showAllBearish
      ? sortedList
      : sortedList.slice(0, 25);

  const renderSortIndicator = (key: PlaybookSortKey) => {
    if (sortKey !== key) {
      return (
        <span style={{ opacity: 0.35, fontSize: "0.75rem", marginLeft: "4px" }}>
          ↕
        </span>
      );
    }
    return (
      <span
        style={{
          color: "var(--accent, #3b82f6)",
          fontSize: "0.82rem",
          fontWeight: 800,
          marginLeft: "4px",
        }}
      >
        {sortOrder === "asc" ? "▲" : "▼"}
      </span>
    );
  };

  return (
    <div className="pulse-card ml-perf-card" style={{ marginTop: "0.75rem" }}>
      {/* Header */}
      <div
        className="pulse-card-head"
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "0.75rem",
          marginBottom: "1rem",
        }}
      >
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "0.55rem" }}>
            <span style={{ fontSize: "1.35rem" }}>⚡</span>
            <h3 style={{ margin: 0, fontWeight: 700, fontSize: "1.15rem", letterSpacing: "0.02em" }}>
              Forward 5-Day Tactical Confluence Playbook
            </h3>
          </div>
          <span className="footnote" style={{ marginTop: "0.3rem", display: "inline-block", fontSize: "0.82rem" }}>
            High-probability trade setups filtered by empirical 2,849-forecast confluence rules
          </span>
        </div>

        {/* Regime Toggle Pills */}
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <button
            type="button"
            className={`ml-perf-tab-btn ${activeScenario === "bullish" ? "active" : ""}`}
            onClick={() => handleScenarioChange("bullish")}
            style={{
              fontSize: "0.88rem",
              padding: "0.45rem 0.9rem",
              ...(activeScenario === "bullish"
                ? {
                    background: "rgba(16, 185, 129, 0.16)",
                    color: "#10b981",
                    borderColor: "rgba(16, 185, 129, 0.45)",
                    fontWeight: 700,
                  }
                : {}),
            }}
          >
            🟢 ML Bullish Leaders ({bullishLeaders.length})
          </button>
          <button
            type="button"
            className={`ml-perf-tab-btn ${activeScenario === "bearish" ? "active" : ""}`}
            onClick={() => handleScenarioChange("bearish")}
            style={{
              fontSize: "0.88rem",
              padding: "0.45rem 0.9rem",
              ...(activeScenario === "bearish"
                ? {
                    background: "rgba(239, 68, 68, 0.16)",
                    color: "#ef4444",
                    borderColor: "rgba(239, 68, 68, 0.45)",
                    fontWeight: 700,
                  }
                : {}),
            }}
          >
            🔴 ML Breakdowns / Exits ({bearishBreakdowns.length})
          </button>
        </div>
      </div>

      {/* Playbook Description Banner */}
      <div
        style={{
          padding: "0.75rem 1rem",
          borderRadius: "8px",
          marginBottom: "1rem",
          fontSize: "0.88rem",
          lineHeight: "1.45",
          background:
            activeScenario === "bullish"
              ? "rgba(16, 185, 129, 0.08)"
              : "rgba(239, 68, 68, 0.08)",
          border: `1px solid ${
            activeScenario === "bullish"
              ? "rgba(16, 185, 129, 0.28)"
              : "rgba(239, 68, 68, 0.28)"
          }`,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "0.6rem",
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
        <span style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>
          Click any column header to sort · Click stock to open research
        </span>
      </div>

      {/* Interactive Sortable Table */}
      <div className="ml-perf-table-wrapper" style={{ overflowX: "auto" }}>
        <table className="ml-tactical-table">
          <thead>
            <tr>
              <th
                onClick={() => handleHeaderSort("symbol")}
                className={sortKey === "symbol" ? "sorted" : ""}
                style={{ textAlign: "left" }}
                title="Sort by Instrument Symbol"
              >
                Instrument {renderSortIndicator("symbol")}
              </th>
              <th
                onClick={() => handleHeaderSort("sector")}
                className={sortKey === "sector" ? "sorted" : ""}
                style={{ textAlign: "left" }}
                title="Sort by Sector"
              >
                Sector {renderSortIndicator("sector")}
              </th>
              <th
                onClick={() => handleHeaderSort("score")}
                className={sortKey === "score" ? "sorted" : ""}
                style={{ textAlign: "right" }}
                title="Sort by Research Score"
              >
                Research Score {renderSortIndicator("score")}
              </th>
              <th
                onClick={() => handleHeaderSort("fundamental_score")}
                className={sortKey === "fundamental_score" ? "sorted" : ""}
                style={{ textAlign: "right" }}
                title="Sort by Fundamental Score"
              >
                Fund Score {renderSortIndicator("fundamental_score")}
              </th>
              <th
                onClick={() => handleHeaderSort("distance_from_52w_high_pct")}
                className={sortKey === "distance_from_52w_high_pct" ? "sorted" : ""}
                style={{ textAlign: "center" }}
                title="Sort by Distance from 52W High"
              >
                Stage 2 / 52W High {renderSortIndicator("distance_from_52w_high_pct")}
              </th>
              <th
                onClick={() => handleHeaderSort("ml_forecast_5d_pct")}
                className={sortKey === "ml_forecast_5d_pct" ? "sorted" : ""}
                style={{ textAlign: "right" }}
                title="Sort by 5-Day ML Return Forecast"
              >
                5D ML Forecast % {renderSortIndicator("ml_forecast_5d_pct")}
              </th>
              <th
                onClick={() => handleHeaderSort("tv_signal")}
                className={sortKey === "tv_signal" ? "sorted" : ""}
                style={{ textAlign: "center" }}
                title="Sort by TradingView Momentum Signal"
              >
                TV Signal {renderSortIndicator("tv_signal")}
              </th>
              <th
                onClick={() => handleHeaderSort("day_change_pct")}
                className={sortKey === "day_change_pct" ? "sorted" : ""}
                style={{ textAlign: "right" }}
                title="Sort by 1-Day Price Change %"
              >
                1D % {renderSortIndicator("day_change_pct")}
              </th>
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
                    <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                      <span
                        style={{
                          fontWeight: 700,
                          fontSize: "1.05rem",
                          color: "var(--accent, #3b82f6)",
                          letterSpacing: "0.02em",
                        }}
                      >
                        {stock.symbol}
                      </span>
                      <span
                        style={{
                          fontSize: "0.82rem",
                          color: "var(--text-muted)",
                          maxWidth: "230px",
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
                    <span style={{ fontSize: "0.88rem", color: "var(--text-muted)", fontWeight: 500 }}>
                      {stock.sector ?? "—"}
                    </span>
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <span className="num" style={{ fontWeight: 700, fontSize: "1.02rem", color: scoreCol }}>
                      {stock.score !== null ? stock.score.toFixed(0) : "—"}
                    </span>
                    {stock.band && (
                      <span
                        style={{
                          fontSize: "0.78rem",
                          fontWeight: 600,
                          color: scoreCol,
                          marginLeft: "6px",
                          padding: "1px 5px",
                          borderRadius: "4px",
                          background: `${scoreCol}18`,
                        }}
                      >
                        {stock.band}
                      </span>
                    )}
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <span className="num" style={{ fontWeight: 700, fontSize: "1.02rem", color: fundCol }}>
                      {stock.fundamental_score !== null ? stock.fundamental_score.toFixed(0) : "—"}
                    </span>
                    {stock.fundamental_band && (
                      <span
                        style={{
                          fontSize: "0.75rem",
                          color: fundCol,
                          marginLeft: "4px",
                          opacity: 0.85,
                        }}
                      >
                        ({stock.fundamental_band})
                      </span>
                    )}
                  </td>
                  <td style={{ textAlign: "center" }}>
                    {stock.momentum_pass === true ? (
                      <span
                        style={{
                          padding: "3px 8px",
                          borderRadius: "5px",
                          fontSize: "0.80rem",
                          fontWeight: 700,
                          background: "rgba(16, 185, 129, 0.16)",
                          color: "#10b981",
                          border: "1px solid rgba(16, 185, 129, 0.3)",
                        }}
                      >
                        ✓ Stage 2
                      </span>
                    ) : stock.distance_from_52w_high_pct !== null ? (
                      <span
                        className="num"
                        style={{
                          fontSize: "0.88rem",
                          fontWeight: 600,
                          color: stock.distance_from_52w_high_pct > -15 ? "var(--text-muted)" : "#ef4444",
                        }}
                      >
                        {stock.distance_from_52w_high_pct.toFixed(1)}%
                      </span>
                    ) : (
                      <span style={{ color: "var(--text-muted)" }}>—</span>
                    )}
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <span
                      className={`num ${(stock.ml_forecast_5d_pct ?? 0) >= 0 ? "up" : "down"}`}
                      style={{ fontWeight: 800, fontSize: "1.05rem" }}
                    >
                      {mlSign}
                      {stock.ml_forecast_5d_pct !== null ? stock.ml_forecast_5d_pct.toFixed(2) : "0.00"}%
                    </span>
                  </td>
                  <td style={{ textAlign: "center" }}>
                    {stock.tv_momentum_flag?.startsWith("STRONG_BUY") ? (
                      <span
                        style={{
                          padding: "3px 8px",
                          borderRadius: "4px",
                          background: "rgba(16, 185, 129, 0.14)",
                          color: "#10b981",
                          fontWeight: 700,
                          fontSize: "0.80rem",
                          border: "1px solid rgba(16, 185, 129, 0.3)",
                        }}
                      >
                        🟢 Strong Buy
                      </span>
                    ) : stock.tv_momentum_flag?.startsWith("STRONG_SELL") ? (
                      <span
                        style={{
                          padding: "3px 8px",
                          borderRadius: "4px",
                          background: "rgba(239, 68, 68, 0.14)",
                          color: "#ef4444",
                          fontWeight: 700,
                          fontSize: "0.80rem",
                          border: "1px solid rgba(239, 68, 68, 0.3)",
                        }}
                      >
                        🔴 Strong Sell
                      </span>
                    ) : (
                      <span style={{ color: "var(--text-muted)", fontSize: "0.82rem" }}>
                        {stock.tv_signal_1d ?? "—"}
                      </span>
                    )}
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <span
                      className={`num ${(stock.day_change_pct ?? 0) >= 0 ? "up" : "down"}`}
                      style={{ fontSize: "0.95rem", fontWeight: 600 }}
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

      {/* Pagination / Expand Footer for Bearish Scenario */}
      {activeScenario === "bearish" && bearishBreakdowns.length > 25 && (
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginTop: "1rem",
            paddingTop: "0.75rem",
            borderTop: "1px solid var(--panel-border)",
          }}
        >
          <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>
            Showing <strong>{displayedList.length}</strong> of <strong>{bearishBreakdowns.length}</strong> high-risk breakdown candidates (sorted by {sortKey} {sortOrder.toUpperCase()})
          </span>
          <button
            type="button"
            className="ml-perf-tab-btn"
            onClick={() => setShowAllBearish((prev) => !prev)}
            style={{ fontSize: "0.85rem", padding: "6px 14px", fontWeight: 600 }}
          >
            {showAllBearish ? "Show Top 25 Only" : `View All ${bearishBreakdowns.length} Breakdowns`}
          </button>
        </div>
      )}
    </div>
  );
}
