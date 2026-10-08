import { bandColor } from "../lib/bands";
import type { ScoreResponse } from "../lib/types";

// SPEC.md section 51's mockup: Research Strength (score + band) and Data
// Confidence are two visually SEPARATE badges, never merged into one
// number (SPEC.md section 22).
export default function ScoreHeader({ score }: { score: ScoreResponse }) {
  const confidencePct = Math.round(score.confidence);
  const color = bandColor(score.band);

  return (
    <div className="score-header-row" style={{ marginTop: "0.75rem" }}>
      <div className="score-badge">
        <span className="score-value" style={{ color }}>
          {score.score === null ? "—" : score.score.toFixed(0)}
        </span>
        <span className="score-band" style={{ color }}>
          {score.band ?? "No score available"} · Research Strength
        </span>
      </div>
      <div className="confidence-badge">
        Data Confidence <span className="confidence-value">{confidencePct}%</span>
      </div>
      <span className="footnote" style={{ margin: 0 }}>
        {score.methodology_version} · as of {score.as_of_date}
      </span>
    </div>
  );
}
