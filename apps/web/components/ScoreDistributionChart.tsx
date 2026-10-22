"use client";

import { useMemo } from "react";
import { useRouter } from "next/navigation";
import { bandColor } from "../lib/bands";
import type { InstrumentSummary, ScoreDistributionResponse } from "../lib/types";

interface Props {
  data: ScoreDistributionResponse | null;
  selectedBand: string | null;
  onSelectBand: (band: string | null) => void;
  instruments?: InstrumentSummary[];
}

const BAND_RANGES: Record<string, string> = {
  "Very Weak": "< 30",
  Weak: "30–44",
  Neutral: "45–54",
  Moderate: "55–69",
  Strong: "70–84",
  "Very Strong": "85+",
};

export default function ScoreDistributionChart({
  data,
  selectedBand,
  onSelectBand,
  instruments = [],
}: Props) {
  const router = useRouter();

  // Aggregate universe-wide score metrics & top scoring leaders
  const universeAnalytics = useMemo(() => {
    if (!instruments.length) return null;
    const scored = instruments.filter((i) => i.score !== null);
    if (!scored.length) return null;

    const totalScore = scored.reduce((acc, i) => acc + (i.score ?? 0), 0);
    const avgScore = totalScore / scored.length;
    const bullish = scored.filter((i) => (i.score ?? 0) >= 55);
    const stage2 = scored.filter((i) => i.momentum_pass === true);
    const topLeaders = [...scored]
      .sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
      .slice(0, 4);

    return {
      avgScore,
      bullishCount: bullish.length,
      bullishPct: ((bullish.length / scored.length) * 100).toFixed(1),
      stage2Count: stage2.length,
      topLeaders,
    };
  }, [instruments]);

  // Aggregate specific metrics & top stocks when a band is selected
  const activeBandAnalytics = useMemo(() => {
    if (!selectedBand || !instruments.length) return null;
    const inBand = instruments.filter((i) => i.band === selectedBand);
    if (!inBand.length) return null;

    const stage2 = inBand.filter((i) => i.momentum_pass === true);
    const breakouts = inBand.filter((i) => i.is_52w_breakout === true);
    const withChange = inBand.filter((i) => i.day_change_pct !== null);
    const avgDayChange =
      withChange.length > 0
        ? withChange.reduce((acc, i) => acc + (i.day_change_pct ?? 0), 0) / withChange.length
        : null;

    const topLeaders = [...inBand]
      .sort((a, b) => {
        // Sort primarily by score desc, then by day_change_pct desc
        const sDiff = (b.score ?? 0) - (a.score ?? 0);
        if (sDiff !== 0) return sDiff;
        return (b.day_change_pct ?? 0) - (a.day_change_pct ?? 0);
      })
      .slice(0, 4);

    return {
      count: inBand.length,
      pctOfUniverse: ((inBand.length / instruments.length) * 100).toFixed(1),
      stage2Count: stage2.length,
      stage2Pct: ((stage2.length / inBand.length) * 100).toFixed(1),
      breakoutCount: breakouts.length,
      avgDayChange,
      topLeaders,
    };
  }, [selectedBand, instruments]);

  if (!data) {
    return (
      <div className="pulse-card score-dist-card">
        <h3>Research Score Distribution</h3>
        <p className="footnote">Loading…</p>
      </div>
    );
  }

  const maxCount = Math.max(1, ...data.bands.map((b) => b.count));
  const totalUniverse = data.universe_size || 1;

  // Decide which list of top stock leaders to show (selected band vs overall universe)
  const spotlightLeaders = selectedBand
    ? activeBandAnalytics?.topLeaders ?? []
    : universeAnalytics?.topLeaders ?? [];

  return (
    <div className="pulse-card score-dist-card">
      {/* Top Header */}
      <div className="pulse-card-head score-dist-head">
        <div>
          <h3>Research Score Distribution</h3>
          <span className="footnote">
            {data.universe_size} instruments
            {universeAnalytics?.avgScore !== undefined && (
              <> · Universe Mean: <strong className="num">{universeAnalytics.avgScore.toFixed(1)}</strong>/100</>
            )}
          </span>
        </div>
        <div className="score-dist-head-actions">
          {selectedBand ? (
            <div className="score-dist-active-badge" style={{ borderColor: bandColor(selectedBand) }}>
              <span className="score-dist-dot" style={{ background: bandColor(selectedBand) }} />
              <span className="score-dist-badge-text">
                {selectedBand} ({activeBandAnalytics?.count ?? 0})
              </span>
              <button
                type="button"
                className="score-dist-clear-btn"
                onClick={() => onSelectBand(null)}
                title="Clear band filter"
                aria-label="Clear band filter"
              >
                ×
              </button>
            </div>
          ) : (
            <span className="score-dist-all-badge">All 6 Tiers</span>
          )}
        </div>
      </div>

      {/* Distribution Bars */}
      <div className="score-dist-chart" role="group" aria-label="Research Score band distribution">
        {data.bands.map((b) => {
          const height = Math.round((b.count / maxCount) * 100);
          const pct = ((b.count / totalUniverse) * 100).toFixed(1);
          const color = bandColor(b.band);
          const active = selectedBand === b.band;
          const rangeLabel = BAND_RANGES[b.band] ?? "";

          return (
            <button
              key={b.band}
              type="button"
              className={`score-dist-bar${active ? " active" : ""}`}
              onClick={() => onSelectBand(active ? null : b.band)}
              title={`${b.band} (${rangeLabel}): ${b.count} stocks (${pct}% of universe) - click to filter`}
              aria-pressed={active}
            >
              <div className="score-dist-top-meta">
                <span className="score-dist-count num" style={{ color: active ? color : undefined }}>
                  {b.count}
                </span>
                <span className="score-dist-pct num">{pct}%</span>
              </div>

              <div className="score-dist-track">
                <div
                  className="score-dist-fill"
                  style={{
                    height: `${Math.max(height, 4)}%`,
                    background: color,
                    boxShadow: active ? `0 0 10px ${color}` : undefined,
                  }}
                />
              </div>

              <div className="score-dist-bottom-labels">
                <span className="score-dist-label">{b.band}</span>
                <span className="score-dist-range-pill">{rangeLabel}</span>
              </div>
            </button>
          );
        })}
      </div>

      {/* Dynamic Intelligence Spotlight */}
      <div className="score-dist-spotlight">
        <div className="score-dist-spotlight-head">
          <div className="score-dist-spotlight-title">
            <span className="spotlight-indicator" style={{ background: selectedBand ? bandColor(selectedBand) : "var(--accent)" }} />
            <h4>
              {selectedBand ? `${selectedBand} Band Intelligence` : "Universe Research Leaders"}
            </h4>
          </div>
          <span className="footnote">
            {selectedBand
              ? `${activeBandAnalytics?.pctOfUniverse ?? 0}% of market universe`
              : "Top conviction scores across all sectors"}
          </span>
        </div>

        {/* 3 Key Metrics KPI Strip */}
        <div className="score-dist-kpi-strip">
          {selectedBand ? (
            <>
              <div className="score-dist-kpi-card">
                <span className="kpi-label">Avg 1D Return</span>
                <span
                  className={`kpi-val num ${
                    activeBandAnalytics?.avgDayChange === null
                      ? ""
                      : activeBandAnalytics?.avgDayChange! >= 0
                      ? "day-change up"
                      : "day-change down"
                  }`}
                >
                  {activeBandAnalytics?.avgDayChange !== null && activeBandAnalytics?.avgDayChange !== undefined
                    ? `${activeBandAnalytics.avgDayChange >= 0 ? "+" : ""}${activeBandAnalytics.avgDayChange.toFixed(2)}%`
                    : "—"}
                </span>
              </div>
              <div className="score-dist-kpi-card">
                <span className="kpi-label">Stage 2 Momentum</span>
                <span className="kpi-val num">
                  {activeBandAnalytics?.stage2Count ?? 0}{" "}
                  <span className="kpi-sub">({activeBandAnalytics?.stage2Pct ?? 0}%)</span>
                </span>
              </div>
              <div className="score-dist-kpi-card">
                <span className="kpi-label">52W Breakouts</span>
                <span className="kpi-val num">
                  {activeBandAnalytics?.breakoutCount ?? 0}{" "}
                  <span className="kpi-sub">stocks</span>
                </span>
              </div>
            </>
          ) : (
            <>
              <div className="score-dist-kpi-card">
                <span className="kpi-label">Universe Mean</span>
                <span className="kpi-val num">
                  {universeAnalytics?.avgScore !== undefined ? universeAnalytics.avgScore.toFixed(1) : "—"}
                  <span className="kpi-sub">/100</span>
                </span>
              </div>
              <div className="score-dist-kpi-card">
                <span className="kpi-label">High Conviction (≥55)</span>
                <span className="kpi-val num">
                  {universeAnalytics?.bullishCount ?? 0}{" "}
                  <span className="kpi-sub">({universeAnalytics?.bullishPct ?? 0}%)</span>
                </span>
              </div>
              <div className="score-dist-kpi-card">
                <span className="kpi-label">Stage 2 Universe</span>
                <span className="kpi-val num">
                  {universeAnalytics?.stage2Count ?? 0} <span className="kpi-sub">stocks</span>
                </span>
              </div>
            </>
          )}
        </div>

        {/* Top 4 Stock Leaders List */}
        <div className="score-dist-leaders-grid">
          {spotlightLeaders.length === 0 ? (
            <p className="footnote score-dist-empty">No stocks currently scored in this tier.</p>
          ) : (
            spotlightLeaders.map((stock) => {
              const stockColor = bandColor(stock.band);
              return (
                <div
                  key={stock.symbol}
                  className="score-dist-stock-row"
                  onMouseEnter={() => router.prefetch(`/stocks/${stock.symbol}`)}
                  onClick={() => router.push(`/stocks/${stock.symbol}`)}
                  title={`View ${stock.symbol} (${stock.company_name}) research details`}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      router.push(`/stocks/${stock.symbol}`);
                    }
                  }}
                >
                  <div className="stock-row-left">
                    <span className="stock-row-symbol">{stock.symbol}</span>
                    <span className="stock-row-name" title={stock.company_name}>
                      {stock.company_name}
                    </span>
                    {stock.sector && <span className="stock-row-sector">{stock.sector}</span>}
                  </div>

                  <div className="stock-row-right">
                    {stock.momentum_pass && (
                      <span className="micro-badge stage2" title="Stage 2 Momentum passed">
                        Stage 2
                      </span>
                    )}
                    {stock.is_52w_breakout && (
                      <span className="micro-badge breakout" title="52-Week High Breakout">
                        52W High
                      </span>
                    )}
                    {stock.day_change_pct !== null && (
                      <span
                        className={`stock-row-change num ${
                          stock.day_change_pct >= 0 ? "day-change up" : "day-change down"
                        }`}
                      >
                        {stock.day_change_pct >= 0 ? "+" : ""}
                        {stock.day_change_pct.toFixed(2)}%
                      </span>
                    )}
                    <span
                      className="stock-row-score num"
                      style={{
                        background: `rgba(${
                          stock.score! >= 70
                            ? "34, 197, 94"
                            : stock.score! >= 55
                            ? "59, 130, 246"
                            : "156, 163, 175"
                        }, 0.14)`,
                        color: stockColor,
                        borderColor: `rgba(${
                          stock.score! >= 70
                            ? "34, 197, 94"
                            : stock.score! >= 55
                            ? "59, 130, 246"
                            : "156, 163, 175"
                        }, 0.35)`,
                      }}
                    >
                      {stock.score !== null ? stock.score.toFixed(1) : "—"}
                    </span>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Footer Note */}
        <div className="score-dist-footer">
          {selectedBand ? (
            <span className="footnote">
              Filtering screener table below to <strong>{selectedBand}</strong>.{" "}
              <button
                type="button"
                className="link-button"
                onClick={() => onSelectBand(null)}
              >
                Reset filter
              </button>
            </span>
          ) : (
            <span className="footnote score-dist-hint">
              💡 Tip: Click any vertical score bar above to inspect stocks in that score tier and filter the screener table.
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
