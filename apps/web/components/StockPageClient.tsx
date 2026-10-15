"use client";

import { useEffect, useState } from "react";
import {
  ApiError,
  getAnalystRating,
  getEvidence,
  getFundamentals,
  getMarketRegime,
  getMomentumScan,
  getPrice,
  getScore,
  getTechnicals,
  getForecast,
  type ForecastResponse
} from "../lib/api";
import { formatDate } from "../lib/format";
import {
  RANGE_KEYS,
  type AnalystRatingResponse,
  type EvidenceItem,
  type FundamentalsResponse,
  type MarketRegimeResponse,
  type MomentumScanResponse,
  type PriceResponse,
  type RangeKey,
  type ScoreResponse,
  type TechnicalsResponse,
} from "../lib/types";
import StockCharts from "./StockCharts";
import TechnicalSummaryPanel from "./TechnicalSummaryPanel";
import TickerHeader from "./TickerHeader";
import ComponentBreakdownPanel from "./ComponentBreakdownPanel";
import BullBearPanel from "./BullBearPanel";
import FundamentalsPanel from "./FundamentalsPanel";
import HistoricalTrendsChart from "./HistoricalTrendsChart";
import ShareholdingChart from "./ShareholdingChart";
import HealthDiagnostics from "./HealthDiagnostics";
import StockHeroTiles from "./StockHeroTiles";
import AboutCompanySection from "./AboutCompanySection";
import AiAnalystChat from "./AiAnalystChat";
import { getStructuredData, getStockDiagnostic, type StructuredDataResponse } from "../lib/api";
import type { StockDiagnosticResponse } from "../lib/types";

interface State {
  price: PriceResponse | null;
  technicals: TechnicalsResponse | null;
  mlForecast: ForecastResponse | null;
  loading: boolean;
  error: string | null;
  notFound: boolean;
}

interface Phase3State {
  score: ScoreResponse | null;
  scoreError: string | null;
  evidenceById: Map<string, EvidenceItem>;
  fundamentals: FundamentalsResponse | null;
  fundamentalsError: string | null;
  regime: MarketRegimeResponse | null;
  momentum: MomentumScanResponse | null;
  analystRating: AnalystRatingResponse | null;
  structuredData: StructuredDataResponse | null;
  diagnostic: StockDiagnosticResponse | null;
  loading: boolean;
}

export type TabKey = "overview" | "health" | "financials" | "shareholding" | "ai" | "all";

export default function StockPageClient({ symbol }: { symbol: string }) {
  const [activeTab, setActiveTab] = useState<TabKey>("overview");
  const [range, setRange] = useState<RangeKey>("6M");

  useEffect(() => {
    if (typeof window !== "undefined") {
      const hash = window.location.hash.replace("#", "").toLowerCase();
      if (hash === "health" || hash === "diagnostics") {
        setActiveTab("health");
      } else if (hash === "financials" || hash === "fundamentals") {
        setActiveTab("financials");
      } else if (hash === "shareholding") {
        setActiveTab("shareholding");
      } else if (hash === "ai" || hash === "chat" || hash === "ask-ai") {
        setActiveTab("ai");
      }
    }
  }, []);
  const [state, setState] = useState<State>({
    price: null,
    technicals: null,
    mlForecast: null,
    loading: true,
    error: null,
    notFound: false,
  });
  const [phase3, setPhase3] = useState<Phase3State>({
    score: null,
    scoreError: null,
    evidenceById: new Map(),
    fundamentals: null,
    fundamentalsError: null,
    regime: null,
    momentum: null,
    analystRating: null,
    structuredData: null,
    diagnostic: null,
    loading: true,
  });

  useEffect(() => {
    let cancelled = false;
    setState((s) => ({ ...s, loading: true, error: null, notFound: false }));

    async function load() {
      try {
        const [price, technicals] = await Promise.all([
          getPrice(symbol, range),
          getTechnicals(symbol, range),
        ]);
        
        let mlForecast = null;
        try {
            mlForecast = await getForecast(symbol);
        } catch (e) {
            // Ignore 404 if forecast is not available
        }
        
        if (!cancelled) {
          setState({ price, technicals, mlForecast, loading: false, error: null, notFound: false });
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setState({ price: null, technicals: null,
    mlForecast: null, loading: false, error: err.detail, notFound: true });
        } else {
          const message = err instanceof ApiError ? err.detail : err instanceof Error ? err.message : "Unknown error";
          setState({ price: null, technicals: null,
    mlForecast: null, loading: false, error: message, notFound: false });
        }
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [symbol, range]);

  // Research Score / fundamentals / regime are fetched independently of
  // the core price/technicals path above and on their own failure never
  // blank out the whole page - each renders its own explicit "data
  // unavailable" state (SPEC.md section 81 rule 23), same philosophy as
  // the relative-strength panel's "insufficient_peer_universe" handling.
  useEffect(() => {
    let cancelled = false;
    setPhase3((s) => ({ ...s, loading: true }));

    async function loadPhase3() {
      const fetchScoreAndEvidence = async () => {
        try {
          const [score, evidence] = await Promise.all([
            getScore(symbol),
            getEvidence(symbol, 200),
          ]);
          return { score, evidence, error: null };
        } catch (err) {
          return {
            score: null,
            evidence: null,
            error: err instanceof ApiError ? err.detail : "Could not load the research score.",
          };
        }
      };

      const fetchFundamentals = async () => {
        try {
          const data = await getFundamentals(symbol);
          return { data, error: null };
        } catch (err) {
          return {
            data: null,
            error: err instanceof ApiError ? err.detail : "Could not load fundamentals.",
          };
        }
      };

      const [scoreRes, fundamentalsRes, regime, momentum, analystRating, structuredData, diagnostic] = await Promise.all([
        fetchScoreAndEvidence(),
        fetchFundamentals(),
        getMarketRegime().catch(() => null), // Not yet computed renders its own state
        getMomentumScan(symbol).catch(() => null), // Renders its own loading/n/a state
        getAnalystRating(symbol).catch(() => null), // Renders its own no coverage state
        getStructuredData(symbol).catch(() => null), // New data lake structured fetch
        getStockDiagnostic(symbol).catch(() => null), // Institutional health & forensics suite
      ]);

      const evidenceById = new Map<string, EvidenceItem>();
      if (scoreRes.evidence) {
        scoreRes.evidence.items.forEach((item) => evidenceById.set(item.id, item));
      }

      if (!cancelled) {
        setPhase3({
          score: scoreRes.score,
          scoreError: scoreRes.error,
          evidenceById,
          fundamentals: fundamentalsRes.data,
          fundamentalsError: fundamentalsRes.error,
          regime,
          momentum,
          analystRating,
          structuredData,
          diagnostic,
          loading: false,
        });
      }
    }

    loadPhase3();
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  if (state.loading) {
    return <div className="skeleton">Loading {symbol}…</div>;
  }

  if (state.notFound) {
    return (
      <div className="notice error">
        <strong>{symbol}</strong> was not found. Check the symbol or go back to{" "}
        <a href="/">search</a>.
      </div>
    );
  }

  if (state.error || !state.price || !state.technicals) {
    return (
      <div className="notice error">
        Could not load data for <strong>{symbol}</strong>: {state.error ?? "unknown error"}
      </div>
    );
  }

  const { price, technicals } = state;
  const bars = price.bars;
  const latest = bars[bars.length - 1];
  const previous = bars.length > 1 ? bars[bars.length - 2] : null;
  const change = previous ? latest.close - previous.close : null;
  const changePct = previous ? (change! / previous.close) * 100 : null;

  return (
    <>
      <div className="panel ticker-panel">
        <TickerHeader
          symbol={symbol}
          companyName={price.company_name}
          price={latest.close}
          change={change}
          changePct={changePct}
          regime={phase3.regime}
        />
        <div className="meta-row">
          {price.exchange} · As of {formatDate(latest.date)}
          {price.data_freshness.stale && (
            <span className="badge" style={{ marginLeft: "0.6rem" }}>
              Data is {price.data_freshness.data_age_days} day(s) old
            </span>
          )}
        </div>

        {!phase3.loading && !phase3.score && (
          <div className="notice" style={{ marginTop: "0.6rem" }}>
            Research score unavailable: {phase3.scoreError ?? "unknown error"}
          </div>
        )}
      </div>

      {/* Hero KPI Tiles: Research Score, Stage 2 Momentum, Analyst Coverage */}
      <StockHeroTiles
        score={phase3.score}
        momentum={phase3.momentum}
        analystRating={phase3.analystRating}
        price={latest.close}
      />

      <div className="stock-tabs-nav" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "overview"}
          className={`stock-tab-btn ${activeTab === "overview" ? "active" : ""}`}
          onClick={() => setActiveTab("overview")}
        >
          <span>📊 Overview &amp; Charts</span>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "health"}
          className={`stock-tab-btn ${activeTab === "health" ? "active" : ""}`}
          onClick={() => setActiveTab("health")}
        >
          <span>🛡️ Health &amp; Diagnostics</span>
          {phase3.diagnostic?.financial_health.piotroski && (
            <span
              className={`stock-tab-badge ${
                phase3.diagnostic.financial_health.piotroski.score >= 7
                  ? "up"
                  : phase3.diagnostic.financial_health.piotroski.score >= 4
                  ? "warn"
                  : "down"
              }`}
            >
              {phase3.diagnostic.financial_health.piotroski.score}/9
            </span>
          )}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "financials"}
          className={`stock-tab-btn ${activeTab === "financials" ? "active" : ""}`}
          onClick={() => setActiveTab("financials")}
        >
          <span>📑 Financials &amp; P&amp;L</span>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "shareholding"}
          className={`stock-tab-btn ${activeTab === "shareholding" ? "active" : ""}`}
          onClick={() => setActiveTab("shareholding")}
        >
          <span>👥 Shareholding</span>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "ai"}
          className={`stock-tab-btn ai-tab ${activeTab === "ai" ? "active" : ""}`}
          onClick={() => setActiveTab("ai")}
        >
          <span>⚡ Ask AI</span>
          <span className="stock-tab-badge up">Vertex Gemini</span>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "all"}
          className={`stock-tab-btn ${activeTab === "all" ? "active" : ""}`}
          onClick={() => setActiveTab("all")}
        >
          <span>Full Report</span>
        </button>
      </div>

      {/* OVERVIEW & CHARTS TAB */}
      {(activeTab === "overview" || activeTab === "all") && (
        <>
          <AboutCompanySection
            companyName={price.company_name}
            symbol={symbol}
            sector={price.sector}
            industry={price.industry}
            description={price.description}
            aiSummary={price.ai_summary}
            keyPoints={price.key_points}
            websiteUrl={price.website_url}
          />

          <div className="panel">
            <div className="range-selector">
              {RANGE_KEYS.map((key) => (
                <button key={key} className={key === range ? "active" : ""} onClick={() => setRange(key)}>
                  {key}
                </button>
              ))}
            </div>
            {bars.length === 0 ? (
              <p className="footnote">No bars in this range.</p>
            ) : (
              <StockCharts bars={bars} series={technicals.series} mlForecast={state.mlForecast} />
            )}
          </div>

          <TechnicalSummaryPanel snapshot={technicals.snapshot} />

          {!phase3.loading && phase3.score && (
            <>
              <ComponentBreakdownPanel components={phase3.score.components} evidenceById={phase3.evidenceById} />
              <BullBearPanel bullCase={phase3.score.bull_case} bearCase={phase3.score.bear_case} />
            </>
          )}
        </>
      )}

      {/* HEALTH & DIAGNOSTICS TAB */}
      {(activeTab === "health" || activeTab === "all") && (
        <>
          {!phase3.loading && phase3.diagnostic && (
            <HealthDiagnostics diagnostic={phase3.diagnostic} />
          )}
          {!phase3.loading && !phase3.diagnostic && (
            <div className="panel">
              <h2>Health &amp; Diagnostics</h2>
              <p className="footnote">Diagnostic evaluation unavailable for this stock.</p>
            </div>
          )}
        </>
      )}

      {/* FINANCIALS & P&L TAB */}
      {(activeTab === "financials" || activeTab === "all") && (
        <>
          {!phase3.loading && phase3.structuredData?.has_data && (
            <HistoricalTrendsChart data={phase3.structuredData.data} />
          )}
          {!phase3.loading && phase3.fundamentals && <FundamentalsPanel data={phase3.fundamentals} />}
          {!phase3.loading && !phase3.fundamentals && (
            <div className="panel">
              <h2>Fundamentals</h2>
              <div className="notice">Fundamentals unavailable: {phase3.fundamentalsError ?? "unknown error"}</div>
            </div>
          )}
        </>
      )}

      {/* SHAREHOLDING TAB */}
      {(activeTab === "shareholding" || activeTab === "all") && (
        <>
          {!phase3.loading && phase3.structuredData?.has_data && (
            <ShareholdingChart data={phase3.structuredData.data} />
          )}
          {!phase3.loading && !phase3.structuredData?.has_data && (
            <div className="panel">
              <h2>Shareholding</h2>
              <p className="footnote">Shareholding records unavailable for this stock.</p>
            </div>
          )}
        </>
      )}

      {/* ASK AI TAB */}
      {(activeTab === "ai" || activeTab === "all") && (
        <div style={{ marginTop: "1rem" }}>
          <AiAnalystChat initialSymbol={symbol} isEmbedded={true} />
        </div>
      )}
    </>
  );
}
