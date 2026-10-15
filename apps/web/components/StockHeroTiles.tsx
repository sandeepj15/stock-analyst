import React from "react";
import { bandColor } from "../lib/bands";
import { formatInr, formatPct } from "../lib/format";
import type { AnalystRatingResponse, MomentumScanResponse, ScoreResponse } from "../lib/types";

interface Props {
  score: ScoreResponse | null;
  momentum: MomentumScanResponse | null;
  analystRating: AnalystRatingResponse | null;
  price: number | null;
}

export default function StockHeroTiles({ score, momentum, analystRating, price }: Props) {
  // 1. Research Score calculations
  const scoreVal = score?.score !== null && score?.score !== undefined ? Math.round(score.score) : null;
  const scoreColor = score ? bandColor(score.band) : "var(--text-muted)";
  const confidence = score ? Math.round(score.confidence) : null;
  const bullCount = score?.bull_case?.length ?? 0;
  const bearCount = score?.bear_case?.length ?? 0;

  // 2. Stage 2 Momentum calculations
  const isStage2Pass = momentum?.passed === true;
  const isEvaluated = momentum?.evaluable === true;
  const conditionsMet = momentum?.conditions?.filter((c) => c.passed).length ?? 0;
  const totalConditions = momentum?.conditions?.length ?? 8;
  const rsRank = momentum?.rs_rank !== null && momentum?.rs_rank !== undefined ? Math.round(momentum.rs_rank) : null;
  const distFromHigh = momentum?.distance_from_52w_high_pct;

  // 3. Analyst Coverage calculations
  const hasAnalystCoverage = analystRating?.has_coverage === true && analystRating.target_mean_price !== null;
  const targetPrice = analystRating?.target_mean_price;
  const upsidePct = analystRating?.upside_pct;
  const analystCount = analystRating?.number_of_analyst_opinions;
  const recommendation = analystRating?.recommendation_key
    ? analystRating.recommendation_key.replace(/_/g, " ").toUpperCase()
    : null;

  return (
    <div className="stock-hero-tiles-grid">
      {/* TILE 1: RESEARCH SCORE */}
      <div className="stock-hero-tile">
        <div className="hero-tile-header">
          <span className="hero-tile-title">
            <span className="hero-tile-icon">🎯</span> Research Strength
          </span>
          {score?.band && (
            <span
              className="hero-tile-badge"
              style={{
                backgroundColor: `color-mix(in srgb, ${scoreColor} 18%, transparent)`,
                color: scoreColor,
                borderColor: `color-mix(in srgb, ${scoreColor} 40%, transparent)`,
              }}
            >
              {score.band}
            </span>
          )}
        </div>

        <div className="hero-tile-body">
          <div className="hero-tile-metric">
            <span className="hero-tile-value num" style={{ color: scoreColor }}>
              {scoreVal !== null ? scoreVal : "—"}
            </span>
            <span className="hero-tile-subtext">/ 100</span>
          </div>
        </div>

        <div className="hero-tile-footer">
          {confidence !== null && (
            <span className="hero-tile-pill">
              <strong>{confidence}%</strong> Confidence
            </span>
          )}
          <span className="hero-tile-detail">
            {bullCount > 0 || bearCount > 0 ? (
              <>
                <span style={{ color: "var(--up)" }}>{bullCount} Bull</span> ·{" "}
                <span style={{ color: "var(--down)" }}>{bearCount} Bear</span>
              </>
            ) : (
              "Methodology v2"
            )}
          </span>
        </div>
      </div>

      {/* TILE 2: STAGE 2 MOMENTUM */}
      <div className="stock-hero-tile">
        <div className="hero-tile-header">
          <span className="hero-tile-title">
            <span className="hero-tile-icon">⚡</span> Stage 2 Momentum
          </span>
          {isEvaluated ? (
            <span
              className={`hero-tile-badge ${isStage2Pass ? "badge-pass" : "badge-neutral"}`}
            >
              {isStage2Pass ? "✓ Confirmed Uptrend" : "Consolidating"}
            </span>
          ) : (
            <span className="hero-tile-badge badge-neutral">Pending Bars</span>
          )}
        </div>

        <div className="hero-tile-body">
          <div className="hero-tile-metric">
            <span
              className={`hero-tile-status ${isStage2Pass ? "status-pass" : "status-fail"}`}
            >
              {isStage2Pass ? "STAGE 2 PASS" : "STAGE 2 FAIL"}
            </span>
          </div>
        </div>

        <div className="hero-tile-footer">
          <span className="hero-tile-pill">
            <strong>{conditionsMet}/{totalConditions}</strong> Conditions Met
          </span>
          {rsRank !== null ? (
            <span className="hero-tile-detail">
              RS Rank: <strong className="num">{rsRank}</strong>/100
              {typeof distFromHigh === "number" && (
                <span style={{ opacity: 0.85 }}> ({distFromHigh >= 0 ? "+" : ""}{distFromHigh.toFixed(1)}% off 52wH)</span>
              )}
            </span>
          ) : typeof distFromHigh === "number" ? (
            <span className="hero-tile-detail">
              {distFromHigh >= 0 ? "+" : ""}{distFromHigh.toFixed(1)}% off 52w High
            </span>
          ) : (
            <span className="hero-tile-detail">Minervini Trend Template</span>
          )}
        </div>
      </div>

      {/* TILE 3: ANALYST COVERAGE */}
      <div className="stock-hero-tile">
        <div className="hero-tile-header">
          <span className="hero-tile-title">
            <span className="hero-tile-icon">📊</span> 1-Yr Analyst Target
          </span>
          {recommendation && (
            <span className="hero-tile-badge badge-rec">
              {recommendation}
            </span>
          )}
        </div>

        <div className="hero-tile-body">
          {hasAnalystCoverage && targetPrice !== null ? (
            <div className="hero-tile-metric" style={{ alignItems: "baseline", gap: "0.5rem" }}>
              <span className="hero-tile-value num">
                {formatInr(targetPrice)}
              </span>
              {upsidePct !== null && upsidePct !== undefined && (
                <span
                  className={`hero-upside-badge num ${upsidePct >= 0 ? "upside-up" : "upside-down"}`}
                >
                  {upsidePct >= 0 ? "▲ +" : "▼ "}
                  {upsidePct.toFixed(1)}%
                </span>
              )}
            </div>
          ) : (
            <div className="hero-tile-metric">
              <span className="hero-tile-muted">No Analyst Coverage</span>
            </div>
          )}
        </div>

        <div className="hero-tile-footer">
          {hasAnalystCoverage && analystCount ? (
            <span className="hero-tile-pill">
              <strong>{analystCount}</strong> Analyst{analystCount > 1 ? "s" : ""}
            </span>
          ) : hasAnalystCoverage ? (
            <span className="hero-tile-pill">
              Consensus Target
            </span>
          ) : (
            <span className="hero-tile-pill" style={{ opacity: 0.7 }}>
              Coverage Gap
            </span>
          )}
          <span className="hero-tile-detail">
            {hasAnalystCoverage
              ? `Source: ${analystRating?.source ?? "TradingView"} consensus`
              : "No institutional consensus target"}
          </span>
        </div>
      </div>
    </div>
  );
}
