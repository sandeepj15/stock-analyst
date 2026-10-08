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
  price: number | null;
  change: number | null;
  changePct: number | null;
  score: ScoreResponse | null;
  regime: MarketRegimeResponse | null;
  momentum: MomentumScanResponse | null;
  analystRating: AnalystRatingResponse | null;
}

// 1-year analyst consensus price target badge (packages/analyst_estimates/,
// apps/api/routes/analyst.py) - green/red reuse the exact same --up/--down
// convention as Stage2Badge above, never a parallel color system. "No
// coverage" is a genuine, common outcome (many mid/small-cap NSE names
// have zero analyst coverage) and renders the same neutral "n/a" tone
// Stage2Badge already uses for its own "not evaluable" case.
export function AnalystTargetBadge({ rating }: { rating: AnalystRatingResponse | null }) {
  if (!rating) {
    return <span className="analyst-badge analyst-na">Analyst target: loading…</span>;
  }
  if (!rating.has_coverage || rating.target_mean_price === null || rating.upside_pct === null) {
    return (
      <span className="analyst-badge analyst-na" title="No analyst coverage for this instrument">
        Analyst target: no coverage
      </span>
    );
  }
  const tone = rating.upside_pct > 0 ? "analyst-up" : rating.upside_pct < 0 ? "analyst-down" : "analyst-na";
  const sign = rating.upside_pct > 0 ? "+" : "";
  return (
    <span
      className={`analyst-badge ${tone}`}
      title={`${rating.number_of_analyst_opinions ?? "—"} analyst(s) · source: ${rating.source ?? "—"} · ${
        rating.data_age_days ?? "—"
      } day(s) old`}
    >
      Target {formatInr(rating.target_mean_price)}
      <span className="num">
        ({sign}
        {rating.upside_pct.toFixed(1)}%)
      </span>
    </span>
  );
}

export function Stage2Badge({ momentum }: { momentum: MomentumScanResponse | null }) {
  if (!momentum) {
    return <span className="stage2-badge stage2-na">Stage 2: loading…</span>;
  }
  if (!momentum.evaluable) {
    return (
      <span className="stage2-badge stage2-na" title={momentum.reason ?? "Not enough price history to evaluate."}>
        Stage 2: n/a
      </span>
    );
  }
  if (momentum.passed) {
    const distance = momentum.distance_from_52w_high_pct;
    return (
      <span className="stage2-badge stage2-pass" title="Passes all 8 Stage 2 Trend Template conditions">
        ✓ Stage 2{distance !== null && <span className="num"> ({distance.toFixed(1)}% off high)</span>}
      </span>
    );
  }
  const failedCount = momentum.conditions.filter((c) => !c.passed).length;
  return (
    <span className="stage2-badge stage2-fail" title={`Fails ${failedCount} of 8 Stage 2 Trend Template conditions`}>
      ✗ Stage 2
    </span>
  );
}

export default function TickerHeader({
  symbol,
  price,
  change,
  changePct,
  score,
  regime,
  momentum,
  analystRating,
}: Props) {
  const tone = changeTone(change);
  const color = score ? bandColor(score.band) : "var(--text-muted)";

  return (
    <div className="ticker-bar">
      <span className="ticker-symbol">{symbol}</span>
      {price !== null && <span className="ticker-price num">{formatInr(price)}</span>}
      {change !== null && (
        <span className={`ticker-change-badge tone-${tone}`}>
          {change >= 0 ? "+" : ""}
          {change.toFixed(2)} ({formatPct(changePct)})
        </span>
      )}
      {score && (
        <span className="score-badge" style={{ color }}>
          <span className="score-value num">{score.score === null ? "—" : score.score.toFixed(0)}</span>
          <span className="score-band">{score.band ?? "No score"}</span>
        </span>
      )}
      {score && (
        <span className="confidence-badge">
          Confidence <span className="confidence-value num">{Math.round(score.confidence)}%</span>
        </span>
      )}
      <MarketRegimeBadge regime={regime} />
      <Stage2Badge momentum={momentum} />
      <AnalystTargetBadge rating={analystRating} />
    </div>
  );
}
