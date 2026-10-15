import type { MarketRegimeResponse } from "../lib/types";

// Market breadth: % of the universe above its 50DMA / 200DMA
// (packages/regime/service.py::compute_breadth, already exposed by
// `GET /api/v1/market/regime`). Per the dataviz skill's guidance for a
// single 0-100% metric, this renders as a plain horizontal bar (not a
// gauge/donut) with the value always printed as text alongside the
// fill - color is never the only signal. Reuses --up/--down (>=50% of
// the universe above its DMA reads as constructive breadth, <50% as
// weak breadth) rather than inventing a new palette.
function BreadthBar({ label, pct }: { label: string; pct: number | null }) {
  const tone = pct === null ? "flat" : pct >= 50 ? "up" : "down";
  const width = pct === null ? 0 : Math.max(0, Math.min(100, pct));
  return (
    <div className="breadth-row">
      <span className="breadth-label">{label}</span>
      <div className="breadth-track" role="img" aria-label={`${label}: ${pct === null ? "unavailable" : pct.toFixed(1) + "%"}`}>
        <div className={`breadth-fill breadth-${tone}`} style={{ width: `${width}%` }} />
      </div>
      <span className={`breadth-value num ${tone}`}>{pct === null ? "—" : `${pct.toFixed(1)}%`}</span>
    </div>
  );
}

export default function BreadthGauge({ regime }: { regime: MarketRegimeResponse | null }) {
  return (
    <div className="pulse-card">
      <div className="pulse-card-head">
        <h3>Market Breadth</h3>
      </div>
      <BreadthBar label="Above 50DMA" pct={regime?.breadth_above_50dma_pct ?? null} />
      <BreadthBar label="Above 200DMA" pct={regime?.breadth_above_200dma_pct ?? null} />
      {!regime && <p className="footnote">Market regime not yet computed.</p>}
    </div>
  );
}
