import type { MarketRegimeResponse } from "../lib/types";

const REGIME_TONE: Record<string, string> = {
  BULLISH_TREND: "regime-bullish",
  LOW_VOLATILITY: "regime-bullish",
  BEARISH_TREND: "regime-bearish",
  HIGH_VOLATILITY: "regime-bearish",
  SIDEWAYS: "regime-neutral",
  TRANSITION: "regime-neutral",
};

const REGIME_LABELS: Record<string, string> = {
  BULLISH_TREND: "Bullish Trend",
  BEARISH_TREND: "Bearish Trend",
  SIDEWAYS: "Sideways",
  HIGH_VOLATILITY: "High Volatility",
  LOW_VOLATILITY: "Low Volatility",
  TRANSITION: "Transition",
};

// SPEC.md section 15 - shown near the stock page header per the task's
// UI requirement. breadth_universe is always surfaced so this is never
// mistaken for real market-wide breadth (only the seeded 117-instrument
// dev universe).
export default function MarketRegimeBadge({ regime }: { regime: MarketRegimeResponse | null }) {
  if (!regime) {
    return <span className="badge">Market regime: not yet computed</span>;
  }

  const tone = REGIME_TONE[regime.regime] ?? "regime-neutral";
  const label = REGIME_LABELS[regime.regime] ?? regime.regime;

  return (
    <span
      className={`regime-badge ${tone}`}
      title={`Nifty vs 200DMA: ${regime.nifty_vs_200dma_pct?.toFixed(1) ?? "—"}% · Breadth >50DMA: ${
        regime.breadth_above_50dma_pct?.toFixed(0) ?? "—"
      }% (${regime.breadth_universe}) · as of ${regime.date}`}
    >
      Market regime: {label}
    </span>
  );
}
