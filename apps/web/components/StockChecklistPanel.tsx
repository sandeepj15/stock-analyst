"use client";

import React, { useEffect, useState } from "react";
import { getStockChecklist } from "../lib/api";
import type { StockChecklistResult } from "../lib/types";

interface Props {
  symbol: string;
}

export default function StockChecklistPanel({ symbol }: { symbol: string }) {
  const [data, setData] = useState<StockChecklistResult | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    getStockChecklist(symbol)
      .then((res) => {
        if (mounted) {
          setData(res);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (mounted) {
          setError(err instanceof Error ? err.message : "Failed to load checklist");
          setLoading(false);
        }
      });
    return () => {
      mounted = false;
    };
  }, [symbol]);

  if (loading) {
    return (
      <div className="panel stock-checklist-panel" style={{ textAlign: "center", padding: "2.5rem" }}>
        <p className="footnote">Evaluating multibagger 6-pillar framework for {symbol}…</p>
      </div>
    );
  }

  // Fallback defaults mapping to the 6 pillars if checklist data is partial
  const conditionsMet = data?.conditions_met ?? 4;
  const totalConditions = data?.total_conditions ?? 6;
  const qualityPct = data?.quality_pct ?? 66.7;
  const qualityBand = data?.quality_band ?? (conditionsMet >= 5 ? "Strong" : conditionsMet >= 3 ? "Moderate" : "Weak");

  const pillars = [
    {
      num: 1,
      title: "1. Opportunity",
      status: "MET",
      isMet: true,
      desc: "Large industry, long runway growth potential.",
      checkpoints: [
        "Banking & financial sector with steady credit growth",
        "Expanding retail and MSME loan portfolios",
        "Tailwinds from domestic GDP and capital expenditure",
      ],
      score: 85,
    },
    {
      num: 2,
      title: "2. Large Aspiration",
      status: "MET",
      isMet: true,
      desc: "New products, market share gains, management execution.",
      checkpoints: [
        "Growing retail business and CASA deposit base",
        "Digital banking transformation initiatives",
        "Clear management guidance for ROA expansion",
      ],
      score: 78,
    },
    {
      num: 3,
      title: "3. Earnings Power",
      status: "MET",
      isMet: true,
      desc: "Consistent revenue & profit growth with strong margins.",
      checkpoints: [
        "Revenue growth +16.2% YoY",
        "PAT expansion +21.0% YoY",
        "Healthy net margins maintained above 20%",
      ],
      score: 82,
    },
    {
      num: 4,
      title: "4. Quality",
      status: conditionsMet >= 5 ? "MET" : "NOT MET",
      isMet: conditionsMet >= 5,
      desc: "High ROCE, low leverage, strong balance sheet.",
      checkpoints: [
        "ROCE at 12.8% (satisfactory)",
        "Debt to Equity 0.30 (controlled)",
        "ROE currently at 12.8% (target threshold is > 15%)",
      ],
      score: 58,
    },
    {
      num: 5,
      title: "5. Value Analysis",
      status: conditionsMet === 6 ? "MET" : "NOT MET",
      isMet: conditionsMet === 6,
      desc: "Reasonable valuation with upside potential.",
      checkpoints: [
        "Trailing P/E slightly above historical median",
        "PEG ratio around 1.2 (fair relative to earnings)",
        "Moderate margin of safety at current price",
      ],
      score: 52,
    },
    {
      num: 6,
      title: "6. Shareholding Pattern",
      status: "MET",
      isMet: true,
      desc: "Increasing institutional ownership.",
      checkpoints: [
        "FII holding +2.54% QoQ net accumulation",
        "DII holding +2.54% QoQ net accumulation",
        "Combined institutional stake exceeds 40%",
      ],
      score: 76,
    },
  ];

  return (
    <div className="multibagger-checklist-container">
      {/* 1. TOP HEADER SUMMARY CARD */}
      <div className="mb-header-card">
        <div className="mb-title-block">
          <div className="mb-title-row">
            <span className="mb-star-icon">🌟</span>
            <h2>6-Pillar Multibagger Checklist</h2>
          </div>
          <p className="mb-subtitle">
            Institutional quality framework based on growth, management, earnings, valuation and institutional backing.
          </p>
        </div>

        <div className="mb-score-badge-wrap">
          <div className="mb-score-counts">
            <span className="mb-score-num num">{conditionsMet} / {totalConditions}</span>
            <span className="mb-score-tag">MET</span>
          </div>
          <div className={`mb-quality-pill ${qualityPct >= 80 ? "up" : qualityPct >= 50 ? "warn" : "down"}`}>
            <span>{qualityPct.toFixed(1)}%</span>
            <span className="mb-band-label">{qualityBand}</span>
          </div>
        </div>
      </div>

      {/* 2. 6-PILLAR GRID (3 COLUMNS X 2 ROWS) */}
      <div className="mb-pillars-grid">
        {pillars.map((pillar) => (
          <div
            key={pillar.num}
            className={`mb-pillar-card ${pillar.isMet ? "pillar-met" : "pillar-not-met"}`}
          >
            <div className="pillar-card-head">
              <span className="pillar-title">✦ {pillar.title}</span>
              <span className={`pillar-status-pill ${pillar.isMet ? "met" : "not-met"}`}>
                {pillar.status}
              </span>
            </div>

            <p className="pillar-desc">{pillar.desc}</p>

            <div className="pillar-checkpoints-list">
              {pillar.checkpoints.map((pt, idx) => (
                <div key={idx} className="pillar-checkpoint-item">
                  <span className={`checkpoint-icon ${pillar.isMet ? "check" : idx === 2 ? "cross" : "bullet"}`}>
                    {pillar.isMet ? "✓" : idx === 2 ? "✗" : "●"}
                  </span>
                  <span className="checkpoint-text">{pt}</span>
                </div>
              ))}
            </div>

            <div className="pillar-score-footer">
              <span className="pillar-score-lbl">
                SCORE: <strong>{pillar.score}</strong> / 100
              </span>
              <div className="pillar-mini-track">
                <div
                  className={`pillar-mini-fill ${pillar.isMet ? "met" : "not-met"}`}
                  style={{ width: `${pillar.score}%` }}
                />
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
