import { formatCompact, formatNumber, formatPct } from "../lib/format";
import type { IndicatorSnapshot } from "../lib/types";

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span className="label">{label}</span>
      <span className="value">{value}</span>
    </div>
  );
}

function Flag({ label, active }: { label: string; active: boolean }) {
  return (
    <div className="metric">
      <span className="label">{label}</span>
      <span className={`flag ${active ? "yes" : "no"}`}>{active ? "YES" : "no"}</span>
    </div>
  );
}

export default function TechnicalSummaryPanel({ snapshot }: { snapshot: IndicatorSnapshot }) {
  return (
    <div className="panel">
      <h2>Technical summary (as of {snapshot.as_of_date})</h2>
      <div className="grid-3">
        <div>
          <Metric label="RSI (14)" value={formatNumber(snapshot.rsi_14, 1)} />
          <Metric label="ADX (14)" value={formatNumber(snapshot.adx_14, 1)} />
          <Metric label="ATR (14)" value={formatNumber(snapshot.atr_14, 2)} />
          <Metric label="Stochastic %K / %D" value={`${formatNumber(snapshot.stochastic_k, 1)} / ${formatNumber(snapshot.stochastic_d, 1)}`} />
          <Metric label="ROC (12)" value={formatPct(snapshot.roc_12, 2)} />
        </div>
        <div>
          <Metric label="Bollinger upper" value={formatNumber(snapshot.bollinger_upper, 2)} />
          <Metric label="Bollinger mid (SMA20)" value={formatNumber(snapshot.bollinger_mid, 2)} />
          <Metric label="Bollinger lower" value={formatNumber(snapshot.bollinger_lower, 2)} />
          <Metric label="Rolling volatility (20d, ann.)" value={formatPct((snapshot.rolling_volatility_20 ?? 0) * 100, 1)} />
          <Metric label="Relative volume (20d)" value={`${formatNumber(snapshot.relative_volume_20, 2)}x`} />
        </div>
        <div>
          <Metric label="52w high" value={formatNumber(snapshot.fifty_two_week_high, 2)} />
          <Metric label="52w low" value={formatNumber(snapshot.fifty_two_week_low, 2)} />
          <Metric label="Distance from 52w high" value={formatPct(snapshot.distance_from_52w_high_pct, 1)} />
          <Metric label="Distance from 52w low" value={formatPct(snapshot.distance_from_52w_low_pct, 1)} />
          <Metric label="OBV" value={formatCompact(snapshot.obv)} />
        </div>
      </div>
      <div className="grid-2" style={{ marginTop: "0.5rem" }}>
        <Flag label="20d breakout" active={snapshot.breakout_20d} />
        <Flag label="20d breakdown" active={snapshot.breakdown_20d} />
      </div>
    </div>
  );
}
