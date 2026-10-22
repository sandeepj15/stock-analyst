"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getAiAlphaPicks } from "../lib/api";
import type { AiAlphaPickItem, AiAlphaPicksResponse } from "../lib/types";

function toNum(v: any): number | null {
  if (typeof v === "number" && !isNaN(v)) return v;
  if (typeof v === "string") {
    const clean = parseFloat(v.replace(/[^0-9.-]/g, ""));
    return isNaN(clean) ? null : clean;
  }
  return null;
}

export default function AiAlphaPicksTab() {
  const [data, setData] = useState<AiAlphaPicksResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedFilter, setSelectedFilter] = useState<string>("ALL");
  const [expandedCard, setExpandedCard] = useState<string | null>(null);

  const fetchData = async () => {
    try {
      setLoading(true);
      setError(null);

      const result = await getAiAlphaPicks();
      setData(result);
      if (result.picks && result.picks.length > 0) {
        setExpandedCard(result.picks[0].symbol);
      }
    } catch (err: any) {
      setError(err?.message || "Failed to load AI Alpha Picks");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const filteredPicks = (data?.picks ?? []).filter((pick) => {
    if (selectedFilter === "ALL") return true;
    if (selectedFilter === "EXCEPTIONAL") return pick.conviction_tier === "EXCEPTIONAL";
    if (selectedFilter === "HIGH") return pick.conviction_tier === "HIGH";
    return true;
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
      {/* Top Banner / Macro Context */}
      <div className="ai-alpha-banner">
        <div className="ai-alpha-banner-header">
          <div>
            <div className="ai-banner-meta-pills">
              <span className="ai-meta-pill primary">Multi-Factor Alpha Engine</span>
              <span className="ai-meta-pill model">
                ⚡ {data?.model_name ? data.model_name.replace("gemini-", "Gemini ").replace("-", " ") : "Gemini 3.5 Flash"}
              </span>
              {data?.generated_date && (
                <span className="ai-meta-pill">
                  Updated: <strong>{data.generated_date}</strong> (Daily Sync)
                </span>
              )}
            </div>

            <h2 className="ai-banner-heading">Institutional AI Alpha Picks</h2>
            <p className="ai-banner-desc">
              Systematic quantitative evaluation predicting future returns by synthesizing{" "}
              <strong>12-1 Momentum</strong> (Jegadeesh-Titman), <strong>Value (E/P Yield)</strong>,{" "}
              <strong>Quality (ROE &amp; Low Debt)</strong>, and <strong>Earnings Revisions</strong>.
            </p>
          </div>
        </div>

        {/* Macro Regime Commentary */}
        {data?.market_regime_context && (
          <div className="ai-macro-box">
            <span className="ai-macro-label">📊 Macro &amp; Factor Regime Assessment:</span>
            <span>{data.market_regime_context}</span>
          </div>
        )}
      </div>

      {/* 4 Factor Pillar Explainer Cards */}
      <div className="ai-pillars-grid">
        <div className="ai-pillar-card">
          <div className="ai-pillar-title momentum">
            <span>🚀 12-1 Momentum</span>
          </div>
          <p className="ai-pillar-desc">
            12M return minus 1M return. Filters short-term mean-reversion pullbacks while capturing persistent
            institutional accumulation and Stage 2 trend health.
          </p>
        </div>

        <div className="ai-pillar-card">
          <div className="ai-pillar-title value">
            <span>💎 Value (E/P Yield)</span>
          </div>
          <p className="ai-pillar-desc">
            Earnings Yield (100 / P/E). Measures cash generation power per rupee of price, protecting against multiple
            contraction and speculative bubbles.
          </p>
        </div>

        <div className="ai-pillar-card">
          <div className="ai-pillar-title quality">
            <span>🏆 Quality (ROE &amp; Balance)</span>
          </div>
          <p className="ai-pillar-desc">
            ROE &ge; 14%, ROCE &ge; 14%, Debt/Equity &le; 0.85. Sustained high return on invested capital with
            conservative leverage and financial resilience.
          </p>
        </div>

        <div className="ai-pillar-card">
          <div className="ai-pillar-title revisions">
            <span>📈 Earnings Revisions</span>
          </div>
          <p className="ai-pillar-desc">
            Analyst consensus price target upside and quarterly YoY PAT &amp; revenue acceleration, driving forward
            institutional upgrades and re-ratings.
          </p>
        </div>
      </div>

      {/* Filter and Count Bar */}
      <div className="ai-filter-toolbar">
        <div className="ai-filter-pills-group">
          <span className="ai-filter-label">Conviction Filter:</span>
          {(["ALL", "EXCEPTIONAL", "HIGH"] as const).map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setSelectedFilter(f)}
              className={`ai-filter-btn ${selectedFilter === f ? "active" : ""}`}
            >
              {f === "ALL" ? "All Top Picks" : f === "EXCEPTIONAL" ? "🌟 Exceptional" : "⚡ High Conviction"}
            </button>
          ))}
        </div>

        <div className="ai-count-indicator">
          Showing <strong>{filteredPicks.length}</strong> of <strong>{data?.picks_count ?? 0}</strong> picks
          (evaluated from {data?.total_candidates_analyzed ?? 0} pre-screened candidates)
        </div>
      </div>

      {/* Loading Skeleton */}
      {loading && (
        <div className="ai-picks-stack">
          {[1, 2, 3].map((n) => (
            <div key={n} className="ai-skeleton-card" />
          ))}
        </div>
      )}

      {/* Error state */}
      {error && !loading && (
        <div
          style={{
            background: "var(--notice-error-bg)",
            border: "1px solid var(--notice-error-border)",
            borderRadius: "10px",
            padding: "1.5rem",
            textAlign: "center",
          }}
        >
          <p style={{ margin: "0 0 1rem", color: "var(--notice-error-text)", fontWeight: 600 }}>{error}</p>
          <button type="button" onClick={() => fetchData()} className="btn-link-stock">
            Retry Loading
          </button>
        </div>
      )}

      {/* Empty State */}
      {!loading && !error && filteredPicks.length === 0 && (
        <div
          style={{
            padding: "3rem",
            textAlign: "center",
            background: "var(--panel)",
            border: "1px solid var(--panel-border)",
            borderRadius: "10px",
            color: "var(--text-muted)",
          }}
        >
          No stocks matched the selected filter. Try selecting &quot;All Top Picks&quot;.
        </div>
      )}

      {/* Picks List */}
      {!loading && !error && filteredPicks.length > 0 && (
        <div className="ai-picks-stack">
          {filteredPicks.map((pick: AiAlphaPickItem) => {
            const isExpanded = expandedCard === pick.symbol;
            const rankClass =
              pick.rank === 1
                ? "rank-1"
                : pick.rank === 2
                ? "rank-2"
                : pick.rank === 3
                ? "rank-3"
                : "rank-other";

            return (
              <div
                key={pick.symbol}
                className={`ai-pick-card ${pick.conviction_tier === "EXCEPTIONAL" ? "exceptional" : "high"}`}
              >
                {/* Card Header (clickable to expand) */}
                <div
                  className="ai-pick-card-header"
                  onClick={() => setExpandedCard(isExpanded ? null : pick.symbol)}
                >
                  <div className="ai-pick-identity">
                    {/* Rank Badge */}
                    <div className={`ai-rank-badge ${rankClass}`}>
                      #{pick.rank}
                    </div>

                    {/* Stock Symbol, Sector, Conviction */}
                    <div className="ai-stock-naming">
                      <div className="ai-symbol-row">
                        <Link
                          href={`/stocks/${pick.symbol}`}
                          onClick={(e) => e.stopPropagation()}
                          className="ai-stock-symbol-link"
                        >
                          {pick.symbol}
                        </Link>
                        <span className="ai-sector-tag">{pick.sector}</span>
                        <span
                          className={`ai-conviction-badge ${
                            pick.conviction_tier === "EXCEPTIONAL" ? "exceptional" : "high"
                          }`}
                        >
                          {pick.conviction_tier === "EXCEPTIONAL" ? "🌟 Exceptional Conviction" : "⚡ High Conviction"}
                        </span>
                      </div>
                      <div className="ai-company-fullname">{pick.company_name}</div>
                    </div>
                  </div>

                  {/* Price & Composite Score */}
                  <div className="ai-pick-metrics">
                    <div className="ai-metric-group">
                      <span className="ai-metric-caption">Current Price</span>
                      <span className="ai-price-display">
                        ₹{(toNum(pick.current_price) ?? 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                      </span>
                    </div>

                    <div className="ai-metric-group">
                      <span className="ai-metric-caption">Composite Alpha</span>
                      <span className="ai-score-display">
                        {(toNum(pick.composite_alpha_score) ?? 0).toFixed(1)}
                        <span className="ai-score-max">/100</span>
                      </span>
                    </div>

                    <div className={`ai-expand-icon ${isExpanded ? "expanded" : ""}`}>
                      ▼
                    </div>
                  </div>
                </div>

                {/* Alpha Thesis Summary */}
                <div className="ai-thesis-bar">
                  <span className="ai-thesis-highlight">💡 Alpha Thesis:</span>
                  <span>{pick.alpha_thesis}</span>
                </div>

                {/* Expanded Factor Breakdown */}
                {isExpanded && (
                  <div className="ai-expanded-body">
                    {/* 4 Factor Pills Grid */}
                    <div className="ai-factors-grid">
                      {/* Momentum Pillar */}
                      <div className="ai-factor-detail-card momentum">
                        <div className="ai-factor-card-head">
                          <span className="ai-factor-card-title">🚀 12-1 Momentum</span>
                          <span className="ai-factor-card-val momentum">
                            +{toNum(pick.signals?.momentum?.value_12_1_pct)?.toFixed(1) ?? "0.0"}%
                          </span>
                        </div>
                        <div className="ai-factor-subvalues">
                          <span>Stage 2 Status:</span>
                          <strong
                            style={{
                              color: pick.signals?.momentum?.stage2_passed ? "var(--up)" : "var(--text-muted)",
                            }}
                          >
                            {pick.signals?.momentum?.stage2_passed ? "✓ Passed" : "In Progress"}
                          </strong>
                        </div>
                        <p className="ai-factor-card-reasoning">
                          {pick.signals?.momentum?.reasoning}
                        </p>
                      </div>

                      {/* Value Pillar */}
                      <div className="ai-factor-detail-card value">
                        <div className="ai-factor-card-head">
                          <span className="ai-factor-card-title">💎 Value (E/P Yield)</span>
                          <span className="ai-factor-card-val value">
                            {toNum(pick.signals?.value_ep?.earnings_yield_pct)?.toFixed(2) ?? "0.00"}%
                          </span>
                        </div>
                        <div className="ai-factor-subvalues">
                          <span>P/E Valuation:</span>
                          <strong>{toNum(pick.signals?.value_ep?.pe_ratio)?.toFixed(1) ?? "—"}x</strong>
                        </div>
                        <p className="ai-factor-card-reasoning">
                          {pick.signals?.value_ep?.reasoning}
                        </p>
                      </div>

                      {/* Quality Pillar */}
                      <div className="ai-factor-detail-card quality">
                        <div className="ai-factor-card-head">
                          <span className="ai-factor-card-title">🏆 Quality (ROE &amp; Debt)</span>
                          <span className="ai-factor-card-val quality">
                            {toNum(pick.signals?.quality?.roe_pct)?.toFixed(1) ?? "0.0"}% ROE
                          </span>
                        </div>
                        <div className="ai-factor-subvalues">
                          {toNum(pick.signals?.quality?.roce_pct) != null && (
                            <span>
                              ROCE: <strong>{toNum(pick.signals?.quality?.roce_pct)?.toFixed(1)}%</strong>
                            </span>
                          )}
                          <span>
                            D/E: <strong>{toNum(pick.signals?.quality?.debt_to_equity)?.toFixed(2) ?? "0.00"}</strong>
                          </span>
                        </div>
                        <p className="ai-factor-card-reasoning">
                          {pick.signals?.quality?.reasoning}
                        </p>
                      </div>

                      {/* Earnings Revisions Pillar */}
                      <div className="ai-factor-detail-card revisions">
                        <div className="ai-factor-card-head">
                          <span className="ai-factor-card-title">📈 Earnings Revisions</span>
                          <span className="ai-factor-card-val revisions">
                            {toNum(pick.signals?.earnings_revisions?.pat_growth_yoy_pct) != null
                              ? `${(toNum(pick.signals?.earnings_revisions?.pat_growth_yoy_pct) ?? 0) > 0 ? "+" : ""}${toNum(pick.signals?.earnings_revisions?.pat_growth_yoy_pct)?.toFixed(0)}% PAT`
                              : "Accelerating"}
                          </span>
                        </div>
                        <div className="ai-factor-subvalues">
                          {toNum(pick.signals?.earnings_revisions?.analyst_upside_pct) != null && (
                            <span>
                              Upside:{" "}
                              <strong style={{ color: "var(--up)" }}>
                                +{toNum(pick.signals?.earnings_revisions?.analyst_upside_pct)?.toFixed(1)}%
                              </strong>
                            </span>
                          )}
                          {toNum(pick.signals?.earnings_revisions?.rev_growth_yoy_pct) != null && (
                            <span>
                              Rev YoY: <strong>+{toNum(pick.signals?.earnings_revisions?.rev_growth_yoy_pct)?.toFixed(1)}%</strong>
                            </span>
                          )}
                        </div>
                        <p className="ai-factor-card-reasoning">
                          {pick.signals?.earnings_revisions?.reasoning}
                        </p>
                      </div>
                    </div>

                    {/* Catalysts, Risks & Invalidation Controls Grid */}
                    <div className="ai-controls-grid">
                      <div className="ai-control-col">
                        <span className="ai-control-heading catalysts">Key Catalysts</span>
                        <ul className="ai-bullet-list">
                          {pick.catalysts?.map((c, i) => (
                            <li key={i} className="ai-bullet-item">
                              <span className="icon-good">✓</span>
                              <span>{c}</span>
                            </li>
                          ))}
                        </ul>
                      </div>

                      <div className="ai-control-col">
                        <span className="ai-control-heading risks">Key Risks to Monitor</span>
                        <ul className="ai-bullet-list">
                          {pick.key_risks?.map((r, i) => (
                            <li key={i} className="ai-bullet-item">
                              <span className="icon-warn">⚠</span>
                              <span>{r}</span>
                            </li>
                          ))}
                        </ul>
                      </div>

                      <div className="ai-invalidation-card">
                        <div>
                          <div className="ai-control-heading invalidation">Technical Invalidation Level</div>
                          <div className="ai-inval-price">
                            {toNum(pick.invalidation_level) && (toNum(pick.invalidation_level) ?? 0) > 0
                              ? `₹${(toNum(pick.invalidation_level) ?? 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`
                              : `₹${((toNum(pick.current_price) || 0) * 0.90).toFixed(2)} (-10% Stop)`}
                          </div>
                          <div className="ai-inval-sub">
                            Structural multi-factor thesis breaks below this level
                          </div>
                        </div>

                        <Link href={`/stocks/${pick.symbol}`} className="btn-open-stock-full">
                          View Full Stock Analytics →
                        </Link>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
