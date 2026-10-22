"use client";

import { useMemo } from "react";
import { useRouter } from "next/navigation";
import type { InstrumentSummary } from "../lib/types";

// Top 5 gainers / losers by day-over-day % price change
// (`InstrumentSummary.day_change_pct`, apps/api/routes/instruments.py's
// window-function query). Computed client-side from the already-loaded
// full-universe listing (`initialInstruments`) rather than a second API
// round trip - the data this needs is already on the page.
function topN(instruments: InstrumentSummary[], n: number, direction: "desc" | "asc"): InstrumentSummary[] {
  const withChange = instruments.filter((i) => i.day_change_pct !== null);
  const sorted = [...withChange].sort((a, b) => (direction === "desc" ? b.day_change_pct! - a.day_change_pct! : a.day_change_pct! - b.day_change_pct!));
  return sorted.slice(0, n);
}

function MoversList({ title, rows }: { title: string; rows: InstrumentSummary[] }) {
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
            <span className={`num day-change ${row.day_change_pct! >= 0 ? "up" : "down"}`}>
              {row.day_change_pct! >= 0 ? "+" : ""}
              {row.day_change_pct!.toFixed(2)}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function TopMovers({ instruments }: { instruments: InstrumentSummary[] }) {
  const gainers = useMemo(() => topN(instruments, 5, "desc"), [instruments]);
  const losers = useMemo(() => topN(instruments, 5, "asc"), [instruments]);

  return (
    <div className="pulse-card movers-card">
      <h3>Top Movers (Day %)</h3>
      <div className="movers-columns">
        <MoversList title="Gainers" rows={gainers} />
        <MoversList title="Losers" rows={losers} />
      </div>
    </div>
  );
}
