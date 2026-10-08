"use client";

import type { CSSProperties } from "react";
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
//
// `"use client"` + `useTheme()` (rather than a plain CSS `var(--up)`
// background) because this needs the *rgb components* of --up/--down to
// build a translucent `rgba(...)` fill at a magnitude-scaled alpha - a
// CSS variable alone can't be alpha-blended in an inline style. Reads
// `CHART_PALETTES` (lib/theme.ts), the same hex values already used by
// lightweight-charts, so dark vs. light mode each get their own correct
// hue (dataviz skill: dark mode is a selected step, never an automatic
// flip), not the dark palette's RGB baked in regardless of theme.
const CLAMP_PCT = 3;

function hexToRgb(hex: string): string {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `${r}, ${g}, ${b}`;
}

interface Props {
  data: SectorsResponse | null;
  selectedSector: string | null;
  onSelectSector: (sector: string | null) => void;
}

export default function SectorHeatmap({ data, selectedSector, onSelectSector }: Props) {
  const [theme] = useTheme();
  const palette = CHART_PALETTES[theme];

  function cellStyle(avgDayChangePct: number | null): CSSProperties {
    if (avgDayChangePct === null) return { background: "var(--surface-alt)" };
    const magnitude = Math.min(Math.abs(avgDayChangePct), CLAMP_PCT) / CLAMP_PCT; // 0..1
    const alpha = 0.08 + magnitude * 0.3; // never fully opaque - text must stay legible
    const color = avgDayChangePct >= 0 ? hexToRgb(palette.up) : hexToRgb(palette.down);
    return { background: `rgba(${color}, ${alpha})` };
  }

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
        <h3>Sector Performance</h3>
        <span className="footnote">Avg Research Score · Avg day change · Stage 2 passes</span>
      </div>
      <div className="sector-heatmap-grid" role="group" aria-label="Sector performance - click a sector to filter the table">
        {data.sectors.map((s) => {
          const active = selectedSector === s.sector;
          return (
            <button
              key={s.sector}
              type="button"
              className={`sector-cell${active ? " active" : ""}`}
              style={cellStyle(s.avg_day_change_pct)}
              onClick={() => onSelectSector(active ? null : s.sector)}
              title={`${s.sector}: ${s.instrument_count} stocks - click to filter the table`}
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
