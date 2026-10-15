import { bandColor } from "../lib/bands";
import { changeTone, formatInr, formatPct } from "../lib/format";
import type { AnalystRatingResponse, MarketRegimeResponse, MomentumScanResponse, ScoreResponse } from "../lib/types";
import MarketRegimeBadge from "./MarketRegimeBadge";

// Compact, exchange-ticker-style header strip (SPEC.md section 51,
// restyled per the Binance-inspired redesign task): symbol, price,
// change, Research Score, Confidence, Market Regime, and Stage 2 all
// in one dense horizontal row, instead of being split across two
// separately-stacked blocks. Pure presentation - every value here is
// still sourced from the same API responses StockPageClient already
// fetches (ScoreHeader.tsx's old layout is superseded by this, not its
// data).
interface Props {
  symbol: string;
  companyName?: string | null;
  price: number | null;
  change: number | null;
  changePct: number | null;
  regime: MarketRegimeResponse | null;
}

export default function TickerHeader({
  symbol,
  companyName,
  price,
  change,
  changePct,
  regime,
}: Props) {
  const tone = changeTone(change);

  return (
    <div className="ticker-bar">
      <div style={{ display: "inline-flex", alignItems: "baseline", gap: "0.5rem", flexWrap: "wrap" }}>
        <span className="ticker-symbol">{symbol}</span>
        {companyName && (
          <span style={{ color: "var(--text-muted)", fontSize: "0.95rem", fontWeight: 500 }}>
            {companyName}
          </span>
        )}
      </div>

      {price !== null && <span className="ticker-price num">{formatInr(price)}</span>}

      {change !== null && (
        <span className={`ticker-change-badge tone-${tone}`}>
          {change >= 0 ? "+" : ""}
          {change.toFixed(2)} ({formatPct(changePct)})
        </span>
      )}

      <MarketRegimeBadge regime={regime} />
    </div>
  );
}
