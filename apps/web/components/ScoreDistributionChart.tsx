import { bandColor } from "../lib/bands";
import type { ScoreDistributionResponse } from "../lib/types";

// Research Score band distribution across the universe
// (`GET /api/v1/market/score-distribution`, a single grouped DB query -
// see apps/api/routes/market.py). Rendered as a vertical bar chart with
// a fixed categorical order (Very Weak -> Very Strong) colored by the
// existing --band-* CSS variables (never a new palette - identity
// already has a well-established color in this codebase, see
// lib/bands.ts::bandColor). Bars are real <button>s (native keyboard/
// focus support) so clicking one can filter the table below to that
// band - clicking the active band again clears the filter.
interface Props {
  data: ScoreDistributionResponse | null;
  selectedBand: string | null;
  onSelectBand: (band: string | null) => void;
}

export default function ScoreDistributionChart({ data, selectedBand, onSelectBand }: Props) {
  if (!data) {
    return (
      <div className="pulse-card score-dist-card">
        <h3>Research Score Distribution</h3>
        <p className="footnote">Loading…</p>
      </div>
    );
  }

  const maxCount = Math.max(1, ...data.bands.map((b) => b.count));

  return (
    <div className="pulse-card score-dist-card">
      <div className="pulse-card-head">
        <h3>Research Score Distribution</h3>
        <span className="footnote">
          {data.universe_size} instruments{data.unscored_count > 0 ? ` · ${data.unscored_count} not yet scored` : ""}
        </span>
      </div>
      <div className="score-dist-chart" role="group" aria-label="Research Score band distribution">
        {data.bands.map((b) => {
          const height = Math.round((b.count / maxCount) * 100);
          const color = bandColor(b.band);
          const active = selectedBand === b.band;
          return (
            <button
              key={b.band}
              type="button"
              className={`score-dist-bar${active ? " active" : ""}`}
              onClick={() => onSelectBand(active ? null : b.band)}
              title={`${b.band}: ${b.count} instruments - click to filter the table`}
              aria-pressed={active}
            >
              <span className="score-dist-count num" style={{ color }}>
                {b.count}
              </span>
              <span className="score-dist-fill" style={{ height: `${Math.max(height, 2)}%`, background: color }} />
              <span className="score-dist-label">{b.band}</span>
            </button>
          );
        })}
      </div>
      {selectedBand && (
        <p className="footnote">
          Filtering table below to <strong>{selectedBand}</strong>.{" "}
          <button type="button" className="link-button" onClick={() => onSelectBand(null)}>
            Clear
          </button>
        </p>
      )}
    </div>
  );
}
