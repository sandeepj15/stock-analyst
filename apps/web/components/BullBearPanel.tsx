import type { BullBearEntry, BullBearStrength } from "../lib/types";

// SPEC.md section 24, scoped down: deterministic, evidence-linked bullet
// lists - NOT the full AI bull/bear case (no LLM, no narrative text).
// Explicitly labeled as such so it's never mistaken for the later
// AI-generated version.

const STRENGTH_LABEL: Record<BullBearStrength, string> = {
  strong: "Strong",
  moderate: "Moderate",
  mild: "Mild",
};

// Reuses the existing `--up`/`--down` theme variables and the Stage 2
// pass/fail badge's pill convention (app/globals.css) rather than
// inventing a new visual language - see `.strength-badge` there. `tone`
// picks which hue family (bull=up, bear=down); `strength` (derived from
// the same `classify_strength` thresholds signals.py uses for the
// score itself, see SCORING.md) picks the saturation/weight within that
// family.
function StrengthBadge({ strength, tone }: { strength: BullBearStrength; tone: "up" | "down" }) {
  return <span className={`strength-badge tone-${tone} strength-${strength}`}>{STRENGTH_LABEL[strength]}</span>;
}

function List({ entries, tone }: { entries: BullBearEntry[]; tone: "up" | "down" }) {
  if (entries.length === 0) {
    return <p className="footnote">No supporting evidence in this bucket.</p>;
  }
  return (
    <ul>
      {entries.map((entry) => (
        <li key={entry.evidence_id} className={`strength-row strength-row-${entry.strength}`}>
          <StrengthBadge strength={entry.strength} tone={tone} />
          <span>{entry.interpretation}</span>
        </li>
      ))}
    </ul>
  );
}

export default function BullBearPanel({ bullCase, bearCase }: { bullCase: BullBearEntry[]; bearCase: BullBearEntry[] }) {
  return (
    <div className="panel">
      <h2>Bull case / Bear case</h2>
      <p className="footnote">
        Key positive and negative drivers deterministically derived from the stock's signals. 
        Each point's strength directly reflects its impact on the final Research Score.
      </p>
      <div className="bull-bear-grid" style={{ marginTop: "0.75rem" }}>
        <div>
          <h3 className="bull-title">Bull case</h3>
          <List entries={bullCase} tone="up" />
        </div>
        <div>
          <h3 className="bear-title">Bear case</h3>
          <List entries={bearCase} tone="down" />
        </div>
      </div>
    </div>
  );
}
