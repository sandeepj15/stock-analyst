"use client";

import { useState } from "react";
import { formatDate, formatNumber } from "../lib/format";
import { COMPONENT_LABELS, type EvidenceItem, type ScoreComponent } from "../lib/types";

const COMPONENT_ORDER = [
  "technical_structure",
  "momentum",
  "fundamentals",
  "valuation",
  "market_regime",
  "risk_quality",
];

const UNAVAILABLE_REASON_LABELS: Record<string, string> = {
  no_fundamental_data: "Fundamentals data unavailable for this stock (yfinance NSE coverage gap).",
  fundamental_data_insufficient: "Fundamentals data too sparse to score.",
  valuation_metrics_unavailable: "Could not compute any valuation metric for this stock.",
  insufficient_peer_universe: "Not enough sector peers in the seeded universe to compare against.",
  insufficient_price_history: "Not enough price history yet.",
  market_regime_not_computed: "Market regime has not been computed yet.",
};

function Bar({ component }: { component: ScoreComponent }) {
  const widthPct = component.available && component.score !== null ? Math.max(2, component.score) : 0;
  return (
    <div className="component-bar-track">
      <div
        className={`component-bar-fill${component.available ? "" : " unavailable"}`}
        style={{ width: `${component.available ? widthPct : 100}%` }}
      />
    </div>
  );
}

export default function ComponentBreakdownPanel({
  components,
  evidenceById,
}: {
  components: ScoreComponent[];
  evidenceById: Map<string, EvidenceItem>;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const ordered = COMPONENT_ORDER.map((name) => components.find((c) => c.name === name)).filter(
    (c): c is ScoreComponent => !!c
  );

  return (
    <div className="panel">
      <h2>Component breakdown</h2>
      <p className="footnote">
        Each component is weighted (SPEC.md section 17); the headline score is a weighted average
        renormalized over only the components with real data (never 0, never a neutral 50 for a
        missing one). Click a component to see its evidence.
      </p>
      {ordered.map((component) => {
        const isOpen = expanded === component.name;
        return (
          <div className="component-row" key={component.name}>
            <div className="component-row-head" onClick={() => setExpanded(isOpen ? null : component.name)}>
              <span className="component-name">{COMPONENT_LABELS[component.name] ?? component.name}</span>
              <span className="component-score">
                {component.available && component.score !== null
                  ? `${component.score.toFixed(0)} / 100 (weight ${(component.weight * 100).toFixed(0)}%, contributes ${component.contribution.toFixed(1)})`
                  : "data unavailable"}
              </span>
            </div>
            <Bar component={component} />
            {!component.available && (
              <div className="component-unavailable-note">
                {UNAVAILABLE_REASON_LABELS[component.reason ?? ""] ?? component.reason ?? "Data unavailable."}
              </div>
            )}
            {isOpen && component.evidence.length > 0 && (
              <div className="component-evidence-list">
                {component.evidence.map((evidenceId) => {
                  const item = evidenceById.get(evidenceId);
                  if (!item) {
                    return (
                      <div className="evidence-row" key={evidenceId}>
                        <span className="footnote">Evidence {evidenceId} (not loaded)</span>
                      </div>
                    );
                  }
                  return (
                    <div className="evidence-row" key={evidenceId}>
                      <span>
                        {item.value_text ?? item.metric_name}
                        {item.value_numeric !== null && (
                          <span className="footnote"> ({formatNumber(item.value_numeric, 2)}{item.unit ?? ""})</span>
                        )}
                      </span>
                      <span className="footnote">
                        {item.source_name} · {formatDate(item.source_timestamp)}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
            {isOpen && component.evidence.length === 0 && (
              <div className="component-evidence-list footnote">No evidence recorded for this component.</div>
            )}
          </div>
        );
      })}
    </div>
  );
}
