"use client";

import { useMemo, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

interface Props {
  data: Record<string, Record<string, Record<string, string>>> | null;
}

const STAKEHOLDER_COLORS: Record<string, string> = {
  Promoters: "#3b82f6",   // Blue
  FIIs: "#10b981",        // Green
  DIIs: "#f59e0b",        // Amber
  Government: "#8b5cf6",  // Purple
  Public: "#ef4444",      // Red
  Others: "#06b6d4",      // Cyan
};

function ChangeBadge({ change }: { change: number | null }) {
  if (change === null || Number.isNaN(change)) {
    return <span style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>—</span>;
  }

  const isZero = Math.abs(change) < 0.005;
  if (isZero) {
    return (
      <span
        style={{
          color: "var(--text-muted)",
          fontSize: "0.82rem",
          fontFamily: "ui-monospace, monospace",
          fontWeight: 500,
          padding: "2px 6px",
        }}
      >
        0.00%
      </span>
    );
  }

  const isPositive = change > 0;
  const color = isPositive ? "#10b981" : "#ef4444";
  const bg = isPositive ? "rgba(16, 185, 129, 0.12)" : "rgba(239, 68, 68, 0.12)";
  const border = isPositive ? "1px solid rgba(16, 185, 129, 0.28)" : "1px solid rgba(239, 68, 68, 0.28)";
  const icon = isPositive ? "▲" : "▼";
  const sign = isPositive ? "+" : "";

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "4px",
        color,
        backgroundColor: bg,
        border,
        padding: "2px 8px",
        borderRadius: "4px",
        fontSize: "0.82rem",
        fontWeight: 600,
        fontFamily: "ui-monospace, monospace",
        whiteSpace: "nowrap",
      }}
    >
      <span style={{ fontSize: "0.72rem" }}>{icon}</span>
      <span>
        {sign}
        {change.toFixed(2)}%
      </span>
    </span>
  );
}

function QuarterCell({
  valStr,
  prevValStr,
  isLatest,
  isCount = false,
}: {
  valStr: string | undefined;
  prevValStr?: string | undefined;
  isLatest?: boolean;
  isCount?: boolean;
}) {
  if (!valStr || valStr === "—") {
    return (
      <div style={{ textAlign: "right", color: "var(--text-muted)" }}>
        —
      </div>
    );
  }

  let curr: number | null = null;
  let prev: number | null = null;

  if (isCount) {
    curr = parseInt(valStr.replace(/,/g, "").trim(), 10);
    if (Number.isNaN(curr)) curr = null;
    if (prevValStr) {
      prev = parseInt(prevValStr.replace(/,/g, "").trim(), 10);
      if (Number.isNaN(prev)) prev = null;
    }
  } else {
    curr = parseFloat(valStr.replace("%", "").replace(/,/g, "").trim());
    if (Number.isNaN(curr)) curr = null;
    if (prevValStr) {
      prev = parseFloat(prevValStr.replace("%", "").replace(/,/g, "").trim());
      if (Number.isNaN(prev)) prev = null;
    }
  }

  let diff: number | null = null;
  if (curr !== null && prev !== null) {
    if (isCount && prev > 0) {
      diff = ((curr - prev) / prev) * 100;
    } else if (!isCount) {
      diff = curr - prev;
    }
  }

  const isPositive = diff !== null && diff > 0.005;
  const isNegative = diff !== null && diff < -0.005;

  const valueColor = isPositive ? "#10b981" : isNegative ? "#ef4444" : "var(--text)";

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "flex-end",
        gap: "2px",
      }}
    >
      <span
        style={{
          fontFamily: "ui-monospace, monospace",
          fontVariantNumeric: "tabular-nums",
          fontWeight: isLatest ? 700 : 600,
          color: valueColor,
          lineHeight: 1.25,
        }}
      >
        {valStr}
      </span>

      {diff !== null && (
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "2px",
            fontSize: "0.68rem",
            fontWeight: 600,
            fontFamily: "ui-monospace, monospace",
            lineHeight: 1.15,
            padding: "1px 4px",
            borderRadius: "3px",
            color: isPositive ? "#10b981" : isNegative ? "#ef4444" : "var(--text-muted)",
            backgroundColor: isPositive
              ? "rgba(16, 185, 129, 0.12)"
              : isNegative
              ? "rgba(239, 68, 68, 0.12)"
              : "transparent",
            whiteSpace: "nowrap",
          }}
          title={
            prevValStr
              ? `QoQ Change vs ${prevValStr}: ${isPositive ? "+" : ""}${diff.toFixed(2)}%`
              : undefined
          }
        >
          <span style={{ fontSize: "0.6rem" }}>
            {isPositive ? "▲" : isNegative ? "▼" : "▪"}
          </span>
          <span>
            {isPositive
              ? `+${diff.toFixed(2)}%`
              : isNegative
              ? `${diff.toFixed(2)}%`
              : "0.00%"}
          </span>
        </span>
      )}
    </div>
  );
}

export default function ShareholdingChart({ data }: Props) {
  const [viewMode, setViewMode] = useState<"table" | "chart">("table");

  const parsedModel = useMemo(() => {
    if (!data || !data["shareholding"]) return null;

    const sh = data["shareholding"];
    const periodSet = new Set<string>();

    const candidateCategories = [
      "Promoters",
      "FIIs",
      "DIIs",
      "Government",
      "Public",
      "Others",
    ];

    // Collect all periods
    for (const key of Object.keys(sh)) {
      if (key !== "No. of Shareholders") {
        for (const period of Object.keys(sh[key] || {})) {
          periodSet.add(period);
        }
      }
    }

    if (periodSet.size === 0) return null;

    // Sort periods chronologically
    const parseDate = (d: string) => {
      const parts = d.trim().split(" ");
      if (parts.length < 2) return 0;
      const [month, year] = parts;
      const months: Record<string, number> = {
        Jan: 0, Feb: 1, Mar: 2, Apr: 3, May: 4, Jun: 5,
        Jul: 6, Aug: 7, Sep: 8, Oct: 9, Nov: 10, Dec: 11,
      };
      return new Date(parseInt(year, 10), months[month] ?? 0).getTime();
    };

    const periods = Array.from(periodSet).sort((a, b) => parseDate(a) - parseDate(b));

    const parseNum = (valStr: string | undefined): number | null => {
      if (!valStr) return null;
      const clean = valStr.replace("%", "").trim();
      const n = parseFloat(clean);
      return Number.isNaN(n) ? null : n;
    };

    // Filter stakeholders that actually have data
    const activeStakeholders = candidateCategories.filter((key) => {
      if (!sh[key]) return false;
      return periods.some((p) => {
        const val = parseNum(sh[key][p]);
        return typeof val === "number" && val > 0;
      });
    });

    if (activeStakeholders.length === 0) return null;

    // Calculate QoQ changes (latest quarter vs previous quarter) for KPI summary cards
    const quarterlyChanges: Record<string, number | null> = {};
    for (const key of activeStakeholders) {
      if (periods.length < 2) {
        quarterlyChanges[key] = null;
        continue;
      }

      let lastValidIdx = periods.length - 1;
      while (lastValidIdx >= 0 && parseNum(sh[key]?.[periods[lastValidIdx]]) === null) {
        lastValidIdx--;
      }

      if (lastValidIdx <= 0) {
        quarterlyChanges[key] = null;
        continue;
      }

      let prevValidIdx = lastValidIdx - 1;
      while (prevValidIdx >= 0 && parseNum(sh[key]?.[periods[prevValidIdx]]) === null) {
        prevValidIdx--;
      }

      if (prevValidIdx < 0) {
        quarterlyChanges[key] = null;
        continue;
      }

      const curr = parseNum(sh[key][periods[lastValidIdx]])!;
      const prev = parseNum(sh[key][periods[prevValidIdx]])!;
      quarterlyChanges[key] = curr - prev;
    }

    // Chart series for Recharts
    const chartSeries = periods.map((period) => {
      const entry: Record<string, any> = { period };
      for (const key of activeStakeholders) {
        entry[key] = parseNum(sh[key]?.[period]);
      }
      return entry;
    });

    // Check for retail shareholder count
    const shareholderCounts = sh["No. of Shareholders"] || null;

    return {
      periods,
      activeStakeholders,
      quarterlyChanges,
      chartSeries,
      rawShareholding: sh,
      shareholderCounts,
    };
  }, [data]);

  if (!parsedModel) {
    return null;
  }

  const {
    periods,
    activeStakeholders,
    quarterlyChanges,
    chartSeries,
    rawShareholding,
    shareholderCounts,
  } = parsedModel;

  const latestPeriod = periods[periods.length - 1];

  return (
    <div className="panel" style={{ marginTop: "1rem" }}>
      {/* Panel Header with View Toggle */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          flexWrap: "wrap",
          gap: "1rem",
          marginBottom: "0.85rem",
        }}
      >
        <div>
          <h2 style={{ margin: 0, fontSize: "1.15rem", fontWeight: 700 }}>
            Shareholding Pattern Trend
          </h2>
          <p
            style={{
              color: "var(--text-secondary)",
              margin: "0.3rem 0 0 0",
              fontSize: "0.82rem",
              lineHeight: 1.4,
            }}
          >
            Quarterly ownership distribution with QoQ changes highlighted (▲ green for accumulation, ▼ red for distribution).
          </p>
        </div>

        <div className="filter-tabs" style={{ margin: 0 }}>
          <button
            type="button"
            className={viewMode === "table" ? "active" : ""}
            onClick={() => setViewMode("table")}
          >
            Tabular View
          </button>
          <button
            type="button"
            className={viewMode === "chart" ? "active" : ""}
            onClick={() => setViewMode("chart")}
          >
            Trend Charts
          </button>
        </div>
      </div>

      {/* KPI Metric Strip */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
          gap: "0.6rem",
          marginBottom: "1rem",
        }}
      >
        {activeStakeholders.map((key) => {
          const color = STAKEHOLDER_COLORS[key] || "var(--accent)";
          const latestVal = rawShareholding[key]?.[latestPeriod] || "—";
          const diff = quarterlyChanges[key];

          return (
            <div
              key={key}
              style={{
                background: "var(--surface-sunken)",
                border: "1px solid var(--panel-border)",
                borderRadius: "6px",
                padding: "0.6rem 0.8rem",
                display: "flex",
                flexDirection: "column",
                gap: "0.25rem",
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  fontSize: "0.78rem",
                  color: "var(--text-muted)",
                  fontWeight: 600,
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                  <span
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: "50%",
                      backgroundColor: color,
                      display: "inline-block",
                    }}
                  />
                  <span>{key}</span>
                </div>
                {diff !== null && (
                  <span
                    style={{
                      fontSize: "0.75rem",
                      fontWeight: 600,
                      color: diff > 0 ? "#10b981" : diff < 0 ? "#ef4444" : "var(--text-muted)",
                    }}
                  >
                    {diff > 0 ? "▲" : diff < 0 ? "▼" : "▪"} {Math.abs(diff).toFixed(2)}%
                  </span>
                )}
              </div>
              <div
                style={{
                  fontSize: "1.15rem",
                  fontWeight: 700,
                  fontFamily: "ui-monospace, monospace",
                  color: "var(--text)",
                }}
              >
                {latestVal}
              </div>
            </div>
          );
        })}
      </div>

      {/* TABULAR VIEW */}
      {viewMode === "table" && (
        <div
          style={{
            overflowX: "auto",
            borderRadius: "8px",
            border: "1px solid var(--panel-border)",
            background: "var(--panel)",
          }}
        >
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              fontSize: "0.85rem",
              textAlign: "left",
            }}
          >
            <thead>
              <tr style={{ background: "var(--surface-sunken)" }}>
                <th
                  style={{
                    position: "sticky",
                    left: 0,
                    background: "var(--surface-sunken)",
                    zIndex: 2,
                    padding: "0.7rem 1rem",
                    borderBottom: "2px solid var(--panel-border)",
                    color: "var(--text-muted)",
                    fontSize: "0.75rem",
                    fontWeight: 700,
                    textTransform: "uppercase",
                    letterSpacing: "0.05em",
                    whiteSpace: "nowrap",
                    minWidth: "150px",
                  }}
                >
                  Shareholder
                </th>
                {periods.map((period, idx) => {
                  const isLatest = idx === periods.length - 1;
                  return (
                    <th
                      key={period}
                      style={{
                        padding: "0.7rem 0.85rem",
                        textAlign: "right",
                        borderBottom: "2px solid var(--panel-border)",
                        color: isLatest ? "var(--text)" : "var(--text-muted)",
                        fontSize: "0.75rem",
                        fontWeight: isLatest ? 700 : 600,
                        textTransform: "uppercase",
                        letterSpacing: "0.05em",
                        whiteSpace: "nowrap",
                        backgroundColor: isLatest ? "rgba(242, 169, 59, 0.08)" : undefined,
                      }}
                    >
                      {period}
                      {isLatest && (
                        <span
                          style={{
                            display: "block",
                            fontSize: "0.62rem",
                            color: "var(--accent)",
                            fontWeight: 700,
                            letterSpacing: "0.02em",
                            marginTop: "1px",
                          }}
                        >
                          Latest
                        </span>
                      )}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {activeStakeholders.map((key) => {
                const color = STAKEHOLDER_COLORS[key] || "var(--text-muted)";

                return (
                  <tr
                    key={key}
                    style={{
                      borderBottom: "1px solid var(--surface-alt)",
                      transition: "background-color 0.1s ease",
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "var(--surface-raised)")}
                    onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
                  >
                    {/* Sticky category title */}
                    <td
                      style={{
                        position: "sticky",
                        left: 0,
                        background: "inherit",
                        zIndex: 1,
                        padding: "0.65rem 1rem",
                        fontWeight: 600,
                        color: "var(--text)",
                        display: "flex",
                        alignItems: "center",
                        gap: "8px",
                        whiteSpace: "nowrap",
                      }}
                    >
                      <span
                        style={{
                          width: 9,
                          height: 9,
                          borderRadius: "50%",
                          backgroundColor: color,
                          display: "inline-block",
                          flexShrink: 0,
                        }}
                      />
                      <span>{key}</span>
                    </td>

                    {/* Quarter columns with embedded QoQ change */}
                    {periods.map((period, idx) => {
                      const isLatest = idx === periods.length - 1;
                      const valStr = rawShareholding[key]?.[period];
                      const prevValStr = idx > 0 ? rawShareholding[key]?.[periods[idx - 1]] : undefined;

                      return (
                        <td
                          key={period}
                          style={{
                            padding: "0.55rem 0.85rem",
                            textAlign: "right",
                            backgroundColor: isLatest ? "rgba(242, 169, 59, 0.04)" : undefined,
                            whiteSpace: "nowrap",
                          }}
                        >
                          <QuarterCell
                            valStr={valStr}
                            prevValStr={prevValStr}
                            isLatest={isLatest}
                            isCount={false}
                          />
                        </td>
                      );
                    })}
                  </tr>
                );
              })}

              {/* Total Row */}
              <tr
                style={{
                  borderTop: "2px solid var(--panel-border)",
                  borderBottom: "1px solid var(--panel-border)",
                  background: "var(--surface-sunken)",
                  fontWeight: 700,
                }}
              >
                <td
                  style={{
                    position: "sticky",
                    left: 0,
                    background: "var(--surface-sunken)",
                    zIndex: 1,
                    padding: "0.7rem 1rem",
                    color: "var(--text)",
                    whiteSpace: "nowrap",
                  }}
                >
                  Total
                </td>
                {periods.map((period, idx) => {
                  const isLatest = idx === periods.length - 1;
                  const total = activeStakeholders.reduce((sum, key) => {
                    const raw = rawShareholding[key]?.[period];
                    if (!raw) return sum;
                    const num = parseFloat(raw.replace("%", "").trim());
                    return sum + (Number.isNaN(num) ? 0 : num);
                  }, 0);

                  return (
                    <td
                      key={period}
                      style={{
                        padding: "0.7rem 0.85rem",
                        textAlign: "right",
                        fontFamily: "ui-monospace, monospace",
                        fontVariantNumeric: "tabular-nums",
                        color: "var(--text)",
                        backgroundColor: isLatest ? "rgba(242, 169, 59, 0.08)" : undefined,
                        whiteSpace: "nowrap",
                      }}
                    >
                      {total > 0 ? `${total.toFixed(2)}%` : "—"}
                    </td>
                  );
                })}
              </tr>

              {/* Optional No. of Shareholders row */}
              {shareholderCounts && (
                <tr
                  style={{
                    borderBottom: "1px solid var(--surface-alt)",
                    color: "var(--text-secondary)",
                    fontSize: "0.82rem",
                  }}
                >
                  <td
                    style={{
                      position: "sticky",
                      left: 0,
                      background: "inherit",
                      zIndex: 1,
                      padding: "0.6rem 1rem",
                      fontWeight: 500,
                      whiteSpace: "nowrap",
                    }}
                  >
                    No. of Shareholders
                  </td>
                  {periods.map((period, idx) => {
                    const isLatest = idx === periods.length - 1;
                    const countStr = shareholderCounts[period] || "—";
                    const prevCountStr = idx > 0 ? shareholderCounts[periods[idx - 1]] : undefined;

                    return (
                      <td
                        key={period}
                        style={{
                          padding: "0.55rem 0.85rem",
                          textAlign: "right",
                          backgroundColor: isLatest ? "rgba(242, 169, 59, 0.04)" : undefined,
                          whiteSpace: "nowrap",
                        }}
                      >
                        <QuarterCell
                          valStr={countStr}
                          prevValStr={prevCountStr}
                          isLatest={isLatest}
                          isCount={true}
                        />
                      </td>
                    );
                  })}
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* CHART VIEW */}
      {viewMode === "chart" && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))",
            gap: "1.5rem",
            marginTop: "1rem",
          }}
        >
          {activeStakeholders.map((key) => (
            <div
              key={key}
              style={{
                display: "flex",
                flexDirection: "column",
                gap: "0.5rem",
                background: "var(--surface-sunken)",
                border: "1px solid var(--panel-border)",
                borderRadius: "8px",
                padding: "0.85rem",
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                  <span
                    style={{
                      width: 10,
                      height: 10,
                      borderRadius: "50%",
                      backgroundColor: STAKEHOLDER_COLORS[key],
                    }}
                  />
                  <span style={{ fontWeight: 600, color: "var(--text)" }}>{key}</span>
                </div>
                <ChangeBadge change={quarterlyChanges[key]} />
              </div>
              <div style={{ width: "100%", height: 180 }}>
                <ResponsiveContainer>
                  <LineChart
                    data={chartSeries}
                    margin={{ top: 5, right: 10, left: -20, bottom: 0 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" vertical={false} />
                    <XAxis dataKey="period" stroke="var(--text-secondary)" tick={{ fontSize: 10 }} />
                    <YAxis
                      stroke="var(--text-secondary)"
                      tick={{ fontSize: 10 }}
                      tickFormatter={(val) => `${val}%`}
                      domain={["auto", "auto"]}
                    />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "var(--panel)",
                        borderColor: "var(--panel-border)",
                        borderRadius: 4,
                        color: "var(--text)",
                      }}
                      formatter={(value: any, name: any) => [
                        typeof value === "number" ? `${value.toFixed(2)}%` : value,
                        name,
                      ]}
                    />
                    <Line
                      type="monotone"
                      dataKey={key}
                      stroke={STAKEHOLDER_COLORS[key]}
                      strokeWidth={2.5}
                      dot={{ r: 2 }}
                      activeDot={{ r: 5 }}
                      connectNulls
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
