"use client";

import { useMemo } from "react";
import { useRouter } from "next/navigation";
import type { InstrumentSummary } from "../lib/types";

function topDistance(instruments: InstrumentSummary[], n: number): InstrumentSummary[] {
  const withValue = instruments.filter((i) => i.distance_from_52w_high_pct !== null);
  // closest to 0 (highest values, approaching 52W high)
  const sorted = [...withValue].sort((a, b) => b.distance_from_52w_high_pct! - a.distance_from_52w_high_pct!);
  return sorted.slice(0, n);
}

function topGrowth(instruments: InstrumentSummary[], n: number): InstrumentSummary[] {
  // Strictly filter for stocks that have PAT growth available and sort by it
  const withValue = instruments.filter((i) => i.pat_growth_yoy !== null);
  const sorted = [...withValue].sort((a, b) => b.pat_growth_yoy! - a.pat_growth_yoy!);
  return sorted.slice(0, n);
}

function DistanceList({ title, rows }: { title: string; rows: InstrumentSummary[] }) {
  const router = useRouter();
  return (
    <div className="movers-list">
      <h4>{title}</h4>
      {rows.length === 0 && <p className="footnote">No data.</p>}
      <ul>
        {rows.map((row) => (
          <li
            key={row.symbol}
            className="movers-row"
            onMouseEnter={() => router.prefetch(`/stocks/${row.symbol}`)}
            onClick={() => router.push(`/stocks/${row.symbol}`)}
          >
            <span className="movers-symbol">{row.symbol}</span>
            <span className={`num day-change ${row.distance_from_52w_high_pct! >= -5 ? "up" : row.distance_from_52w_high_pct! <= -30 ? "down" : "flat"}`}>
              {row.distance_from_52w_high_pct!.toFixed(2)}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function GrowthList({ title, rows }: { title: string; rows: InstrumentSummary[] }) {
  const router = useRouter();
  return (
    <div className="movers-list">
      <h4>{title}</h4>
      {rows.length === 0 && <p className="footnote">No data.</p>}
      <ul>
        {rows.map((row) => {
          const val = row.pat_growth_yoy;
          const label = "PAT";
          return (
            <li
              key={row.symbol}
              className="movers-row"
              onMouseEnter={() => router.prefetch(`/stocks/${row.symbol}`)}
              onClick={() => router.push(`/stocks/${row.symbol}`)}
            >
              <span className="movers-symbol">{row.symbol}</span>
              <span className={`num day-change ${val! > 20 ? "up" : val! < 0 ? "down" : "flat"}`}>
                 {val! > 0 ? "+" : ""}{val!.toFixed(1)}% <span style={{fontSize: "0.6rem", color: "var(--text-muted)", marginLeft: "2px"}}>{label}</span>
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export default function MarketLeadersWidget({ instruments }: { instruments: InstrumentSummary[] }) {
  const nearHighs = useMemo(() => topDistance(instruments, 5), [instruments]);
  const earningsLeaders = useMemo(() => topGrowth(instruments, 5), [instruments]);

  return (
    <div className="pulse-card movers-card">
      <h3>Market Leaders</h3>
      <div className="movers-columns">
        <DistanceList title="Near 52W High" rows={nearHighs} />
        <GrowthList title="Top Earnings Growth" rows={earningsLeaders} />
      </div>
    </div>
  );
}
