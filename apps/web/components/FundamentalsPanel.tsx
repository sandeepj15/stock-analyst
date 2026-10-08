import { bandColor } from "../lib/bands";
import { changeTone, formatCompact, formatDate, formatNumber, formatPct } from "../lib/format";
import type { FundamentalScore, FundamentalsResponse, QuarterlyPoint } from "../lib/types";

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span className="label">{label}</span>
      <span className="value">{value}</span>
    </div>
  );
}

const pct = (v: number | null) => (v === null ? "—" : formatPct(v * 100, 1));

function shortQuarterLabel(periodEnd: string): string {
  const d = new Date(periodEnd);
  if (Number.isNaN(d.getTime())) return periodEnd;
  // en-US (not en-IN) deliberately - en-IN renders September as "Sept"
  // (4 letters), breaking the 3-letter rhythm of every other month here.
  return d.toLocaleDateString("en-US", { month: "short", year: "2-digit" }).replace(" ", "’");
}

function AthBadge({ value }: { value: boolean | null }) {
  if (value === null) return <span className="ath-badge ath-badge-unknown">—</span>;
  return <span className={`ath-badge ${value ? "ath-badge-yes" : "ath-badge-no"}`}>{value ? "Yes" : "No"}</span>;
}

// Stat-tile-with-sparkline (value + delta + trend) - the standard form for
// "a current value plus its recent trend" rather than a bare bar chart.
// Each bar's color is a status encoding (that quarter's own YoY direction,
// not series identity), and a quarter yfinance has no reported value for
// (a real, observed gap - e.g. RELIANCE's Sep-2025 quarter) renders with
// the same diagonal "unavailable" texture used elsewhere in this panel
// (SubScoreBar) rather than a bar implying a near-zero value.
function QuarterlyStatCard({
  label,
  points,
  field,
  yoyField,
}: {
  label: string;
  points: QuarterlyPoint[];
  field: "revenue" | "pat";
  yoyField: "revenue_growth_yoy" | "pat_growth_yoy";
}) {
  const latest = points[points.length - 1];
  const latestYoy = latest[yoyField];
  const tone = changeTone(latestYoy);
  const arrow = latestYoy === null ? "" : latestYoy > 0 ? "▲" : latestYoy < 0 ? "▼" : "▪";

  const magnitudes = points.map((p) => p[field]).filter((v): v is number => v !== null).map(Math.abs);
  const maxMagnitude = Math.max(1, ...magnitudes);

  return (
    <div className="quarterly-stat-card">
      <div className="quarterly-stat-label">{label}</div>
      <div className="quarterly-stat-head">
        <span className="quarterly-stat-value">{formatCompact(latest[field])}</span>
        {latestYoy !== null && (
          <span className={`quarterly-stat-delta tone-${tone}`}>
            {arrow} {pct(latestYoy)} YoY
          </span>
        )}
      </div>
      <div className="quarterly-trend-bars">
        {points.map((p) => {
          const value = p[field];
          const isMissing = value === null;
          const barTone = changeTone(p[yoyField]);
          const heightPct = isMissing ? 45 : Math.max(10, (Math.abs(value as number) / maxMagnitude) * 100);
          return (
            <div
              key={p.period_end}
              className={`quarterly-bar${isMissing ? " unavailable" : ""}`}
              title={`${formatDate(p.period_end)}: ${isMissing ? "no data reported" : formatCompact(value)}`}
              style={{ height: `${heightPct}%`, background: isMissing ? undefined : `var(--${barTone})` }}
            />
          );
        })}
      </div>
      <div className="quarterly-trend-ticks">
        {points.map((p) => (
          <span key={p.period_end}>{shortQuarterLabel(p.period_end)}</span>
        ))}
      </div>
    </div>
  );
}

const SUBSCORE_LABELS: Record<string, string> = {
  growth: "Growth",
  profitability: "Profitability",
  leverage: "Leverage / Risk",
  efficiency: "Efficiency",
};

// Mirrors ComponentBreakdownPanel's `.component-bar-track`/`.component-bar-fill`
// visual convention so this reads as "the same kind of bar", but uses the
// `.subscore-*` variant (smaller, --purple accent) so it's legible as a
// sub-view nested inside the Fundamentals panel rather than a sibling of
// the main 8-component Research Score breakdown.
function SubScoreBar({ name, value }: { name: string; value: number | null }) {
  const widthPct = value !== null ? Math.max(2, value) : 0;
  return (
    <div className="subscore-row">
      <div className="subscore-row-head">
        <span className="subscore-name">{SUBSCORE_LABELS[name] ?? name}</span>
        <span className="subscore-value">{value !== null ? value.toFixed(0) : "n/a"}</span>
      </div>
      <div className="subscore-bar-track">
        <div
          className={`subscore-bar-fill${value === null ? " unavailable" : ""}`}
          style={{ width: `${value !== null ? widthPct : 100}%` }}
        />
      </div>
    </div>
  );
}

function FundamentalScoreBadge({ score }: { score: FundamentalScore }) {
  const color = score.overall !== null ? bandColor(score.band) : "var(--text-muted)";
  return (
    <div className="fundamental-score-block">
      <div className="score-header-row">
        <span className="score-badge" style={{ color }}>
          <span className="score-value num">{score.overall === null ? "—" : score.overall.toFixed(0)}</span>
          <span className="score-band">{score.band ?? "No fundamental score"}</span>
        </span>
        <span className="footnote">Fundamental Score ({score.methodology_version})</span>
      </div>
      <div className="subscore-grid">
        {(["growth", "profitability", "leverage", "efficiency"] as const).map((name) => (
          <SubScoreBar key={name} name={name} value={score.sub_scores[name]} />
        ))}
      </div>
    </div>
  );
}

export default function FundamentalsPanel({ data }: { data: FundamentalsResponse }) {
  if (!data.has_fundamental_data) {
    return (
      <div className="panel">
        <h2>Fundamentals</h2>
        <div className="notice">{data.message ?? "Fundamentals data unavailable for this stock."}</div>
      </div>
    );
  }

  return (
    <div className="panel">
      <h2>Fundamentals (as of {data.raw.period_end}, {data.raw.data_age_days}d old)</h2>
      {data.valuation.stale && (
        <div className="notice" style={{ marginBottom: "0.75rem" }}>
          Confidence reduced — fundamentals data is {data.raw.data_age_days} days old. Valuation
          numbers below still use this data, with its age clearly marked.
        </div>
      )}
      <FundamentalScoreBadge score={data.fundamental_score} />
      <div className="grid-3" style={{ marginTop: "1rem" }}>
        <div>
          <h3 style={{ fontSize: "0.8rem", color: "var(--text-muted)", margin: "0 0 0.4rem 0" }}>Raw (reported)</h3>
          <Metric label="Revenue" value={formatCompact(data.raw.revenue)} />
          <Metric label="EBITDA" value={formatCompact(data.raw.ebitda)} />
          <Metric label="PAT" value={formatCompact(data.raw.pat)} />
          <Metric label="EPS" value={formatNumber(data.raw.eps, 2)} />
          <Metric label="Free cash flow" value={formatCompact(data.raw.free_cash_flow)} />
          <Metric label="Total debt" value={formatCompact(data.raw.total_debt)} />
          <Metric label="Interest expense" value={formatCompact(data.raw.interest_expense)} />
          <Metric label="Current assets" value={formatCompact(data.raw.current_assets)} />
          <Metric label="Current liabilities" value={formatCompact(data.raw.current_liabilities)} />
          <Metric label="Source" value={data.raw.source ?? "—"} />
        </div>
        <div>
          <h3 style={{ fontSize: "0.8rem", color: "var(--text-muted)", margin: "0 0 0.4rem 0" }}>Derived (growth / quality)</h3>
          <Metric label="Revenue growth YoY" value={pct(data.derived.revenue_growth_yoy)} />
          <Metric label="EBITDA growth YoY" value={pct(data.derived.ebitda_growth_yoy)} />
          <Metric label="PAT growth YoY" value={pct(data.derived.pat_growth_yoy)} />
          <Metric label="EPS growth YoY" value={pct(data.derived.eps_growth_yoy)} />
          <Metric label="ROE" value={pct(data.derived.roe)} />
          <Metric label="ROCE (simplified)" value={pct(data.derived.roce_simplified)} />
          <Metric label="ROA" value={pct(data.derived.roa)} />
          <Metric label="Net profit margin" value={pct(data.derived.net_profit_margin)} />
          <Metric label="Operating margin" value={pct(data.derived.operating_margin)} />
          <Metric label="FCF margin" value={pct(data.derived.fcf_margin)} />
        </div>
        <div>
          <h3 style={{ fontSize: "0.8rem", color: "var(--text-muted)", margin: "0 0 0.4rem 0" }}>Leverage / Efficiency / Valuation</h3>
          <Metric label="Debt / Equity" value={formatNumber(data.derived.debt_to_equity, 2)} />
          <Metric label="Net Debt / EBITDA" value={formatNumber(data.derived.net_debt_to_ebitda, 2)} />
          <Metric label="Interest coverage" value={formatNumber(data.derived.interest_coverage, 2)} />
          <Metric label="Current ratio" value={formatNumber(data.derived.current_ratio, 2)} />
          <Metric label="Asset turnover" value={formatNumber(data.derived.asset_turnover, 2)} />
          <Metric label="Financial leverage" value={formatNumber(data.derived.financial_leverage, 2)} />
          <Metric label="P/E" value={formatNumber(data.valuation.pe, 2)} />
          <Metric label="PEG ratio" value={formatNumber(data.derived.peg_ratio, 2)} />
          {/* dividend_yield is a raw yfinance passthrough already expressed in
              percentage-point units (e.g. 0.51 means 0.51%) - unlike every
              other ratio on this panel, which this codebase computes itself
              as a plain fraction. Do not multiply by 100 here. See SCORING.md. */}
          <Metric label="Dividend yield" value={formatPct(data.valuation.dividend_yield, 2)} />
          <Metric label="Market cap" value={formatCompact(data.valuation.market_cap)} />
        </div>
      </div>
      {data.quarterly && (
        <div className="panel-section quarterly-section" style={{ marginTop: "1rem" }}>
          <h3 style={{ fontSize: "0.8rem", color: "var(--text-muted)", margin: "0 0 0.4rem 0" }}>
            Quarterly Trend ({data.quarterly.source ?? "—"}, as of {formatDate(data.quarterly.latest_period_end)},{" "}
            {data.quarterly.data_age_days}d old)
          </h3>
          <div className="quarterly-kpi-row">
            <div className="quarterly-kpi-tile">
              <span className="quarterly-kpi-label">Quarters available</span>
              <span className="quarterly-kpi-value">{data.quarterly.quarters_available}</span>
            </div>
            <div className="quarterly-kpi-tile">
              <span className="quarterly-kpi-label">Revenue at All-Time High</span>
              <AthBadge value={data.quarterly.revenue_at_all_time_high} />
            </div>
            <div className="quarterly-kpi-tile">
              <span className="quarterly-kpi-label">Profit at All-Time High</span>
              <AthBadge value={data.quarterly.pat_at_all_time_high} />
            </div>
          </div>
          {data.quarterly.points.length > 0 && (
            <>
              <div className="quarterly-stat-grid">
                <QuarterlyStatCard
                  label="Revenue"
                  points={data.quarterly.points}
                  field="revenue"
                  yoyField="revenue_growth_yoy"
                />
                <QuarterlyStatCard
                  label="Profit (PAT)"
                  points={data.quarterly.points}
                  field="pat"
                  yoyField="pat_growth_yoy"
                />
              </div>
              <div className="quarterly-legend">
                <span className="quarterly-legend-item">
                  <i className="legend-dot tone-dot-up" /> Up YoY
                </span>
                <span className="quarterly-legend-item">
                  <i className="legend-dot tone-dot-down" /> Down YoY
                </span>
                <span className="quarterly-legend-item">
                  <i className="legend-dot tone-dot-flat" /> Flat / no YoY data
                </span>
                <span className="quarterly-legend-item">
                  <i className="legend-dot legend-dot-unavailable" /> No data reported
                </span>
              </div>
            </>
          )}
          <p className="footnote">
            Quarterly data is sourced from screener.in where available (falling back to yfinance for
            quarters it doesn&apos;t have) - the ATH flags above mean &quot;highest of the{" "}
            {data.quarterly.quarters_available} quarters we have&quot;, not necessarily true
            since-listing history. YoY growth is null wherever the same quarter one year prior
            isn&apos;t in that window.
          </p>
        </div>
      )}
      <p className="footnote">
        P/E is null (not a negative number) when EPS is non-positive; EV/EBITDA is null when EBITDA
        is non-positive - a loss-making company&apos;s valuation on that metric isn&apos;t
        meaningful. ROCE is simplified as EBIT / (Equity + Total Debt) because current-liability
        granularity isn&apos;t available from this data source. Interest coverage / current ratio
        are null wherever interest expense / current assets+liabilities aren&apos;t available from
        either provider — current ratio in particular is structurally unavailable for banks (no
        current/non-current balance-sheet split). Financial leverage and PEG ratio are shown for
        transparency only and are not part of the Fundamental Score (see SCORING.md).
      </p>
    </div>
  );
}
