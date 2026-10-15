"use client";

import { useMemo, useState, type CSSProperties } from "react";
import type { SectorsResponse } from "../lib/types";
import { CHART_PALETTES } from "../lib/theme";
import { useTheme } from "../lib/useTheme";

// Per-sector aggregate (`GET /api/v1/market/sectors`, a single grouped
// DB query - see apps/api/routes/market.py) rendered as a grid of cards
// colored by average day-over-day % price change - a diverging metric
// (negative/positive around a true zero), so this reuses the theme's
// existing green/red --up/--down pair as the diverging poles with a
// neutral surface at/near zero, exactly the dataviz skill's "diverging
// = two hues + a neutral midpoint" rule - never a rainbow, never a new
// palette. Color intensity (not hue) scales with magnitude, clamped to
// a +/-3% band so one outlier sector never washes out the rest.
const CLAMP_PCT = 3;

function hexToRgb(hex: string): string {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `${r}, ${g}, ${b}`;
}

export type SectorSortKey = "pct_desc" | "pct_asc" | "name" | "score";

interface Props {
  data: SectorsResponse | null;
  selectedSector: string | null;
  onSelectSector: (sector: string | null) => void;
}

export default function SectorHeatmap({ data, selectedSector, onSelectSector }: Props) {
  const [theme] = useTheme();
  const palette = CHART_PALETTES[theme];
  const [sortKey, setSortKey] = useState<SectorSortKey>("pct_desc");

  function cellStyle(avgDayChangePct: number | null): CSSProperties {
    if (avgDayChangePct === null) return { background: "var(--surface-alt)" };
    const magnitude = Math.min(Math.abs(avgDayChangePct), CLAMP_PCT) / CLAMP_PCT; // 0..1
    const alpha = 0.08 + magnitude * 0.3; // never fully opaque - text must stay legible
    const color = avgDayChangePct >= 0 ? hexToRgb(palette.up) : hexToRgb(palette.down);
    return { background: `rgba(${color}, ${alpha})` };
  }

  const sortedSectors = useMemo(() => {
    if (!data?.sectors) return [];
    const list = [...data.sectors];
    switch (sortKey) {
      case "pct_desc":
        return list.sort((a, b) => {
          const valA = a.avg_day_change_pct ?? -Infinity;
          const valB = b.avg_day_change_pct ?? -Infinity;
          return valB - valA;
        });
      case "pct_asc":
        return list.sort((a, b) => {
          const valA = a.avg_day_change_pct ?? Infinity;
          const valB = b.avg_day_change_pct ?? Infinity;
          return valA - valB;
        });
      case "score":
        return list.sort((a, b) => {
          const valA = a.avg_score ?? -Infinity;
          const valB = b.avg_score ?? -Infinity;
          return valB - valA;
        });
      case "name":
      default:
        return list.sort((a, b) => a.sector.localeCompare(b.sector));
    }
  }, [data?.sectors, sortKey]);

  if (!data) {
    return (
      <div className="pulse-card">
        <h3>Sector Performance</h3>
        <p className="footnote">Loading…</p>
      </div>
    );
  }

  return (
    <div className="pulse-card sector-heatmap-card">
      <div className="pulse-card-head">
        <div className="sector-head-info">
          <h3>Sector Performance</h3>
          <span className="footnote">Avg Research Score · Avg day change · Stage 2 passes</span>
        </div>
        <div className="sector-sort-controls" role="toolbar" aria-label="Sort sectors">
          <span className="sector-sort-label">Sort:</span>
          <button
            type="button"
            className={`sector-sort-pill ${sortKey === "pct_desc" ? "active" : ""}`}
            onClick={() => setSortKey(sortKey === "pct_desc" ? "pct_asc" : "pct_desc")}
            title="Sort by Day Change % (Highest to Lowest)"
          >
            % ▼
          </button>
          <button
            type="button"
            className={`sector-sort-pill ${sortKey === "pct_asc" ? "active" : ""}`}
            onClick={() => setSortKey("pct_asc")}
            title="Sort by Day Change % (Lowest to Highest)"
          >
            % ▲
          </button>
          <button
            type="button"
            className={`sector-sort-pill ${sortKey === "name" ? "active" : ""}`}
            onClick={() => setSortKey("name")}
            title="Sort Alphabetically (A to Z)"
          >
            A–Z
          </button>
          <button
            type="button"
            className={`sector-sort-pill ${sortKey === "score" ? "active" : ""}`}
            onClick={() => setSortKey("score")}
            title="Sort by Average Research Score (Highest first)"
          >
            Score
          </button>
        </div>
      </div>
      <div className="sector-heatmap-grid" role="group" aria-label="Sector performance - click a sector to filter the table">
        {sortedSectors.map((s) => {
          const active = selectedSector === s.sector;
          return (
            <button
              key={s.sector}
              type="button"
              className={`sector-cell${active ? " active" : ""}`}
              style={cellStyle(s.avg_day_change_pct)}
              onClick={() => onSelectSector(active ? null : s.sector)}
              title={`${s.sector}: ${s.instrument_count} stocks (${s.avg_day_change_pct !== null ? `${s.avg_day_change_pct >= 0 ? "+" : ""}${s.avg_day_change_pct.toFixed(2)}%` : "0%"}) - click to filter table`}
              aria-pressed={active}
            >
              <div className="sector-cell-name">{s.sector}</div>
              <div className="sector-cell-metrics">
                <span className="num">{s.avg_score !== null ? s.avg_score.toFixed(0) : "—"}</span>
                <span className={`num ${s.avg_day_change_pct === null ? "" : s.avg_day_change_pct >= 0 ? "day-change up" : "day-change down"}`}>
                  {s.avg_day_change_pct !== null
                    ? `${s.avg_day_change_pct >= 0 ? "+" : ""}${s.avg_day_change_pct.toFixed(2)}%`
                    : "—"}
                </span>
              </div>
              <div className="sector-cell-footnote">
                {s.instrument_count} stocks · {s.momentum_pass_count} Stage 2
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
