"use client";

import { useEffect, useState, useRef } from "react";
import Link from "next/link";
import { getStockSummary } from "../lib/stockSummaryCache";
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
  getStructuredData,
  getStockDiagnostic,
  type ForecastResponse,
  type StructuredDataResponse,
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
  type StockDiagnosticResponse,
} from "../lib/types";
import StockCharts from "./StockCharts";
import TechnicalSummaryPanel from "./TechnicalSummaryPanel";
import TickerHeader from "./TickerHeader";
import ComponentBreakdownPanel from "./ComponentBreakdownPanel";
import BullBearPanel from "./BullBearPanel";
import HealthDiagnostics from "./HealthDiagnostics";
import FinancialsAndPlView from "./FinancialsAndPlView";
import ShareholdingView from "./ShareholdingView";
import StockChecklistPanel from "./StockChecklistPanel";
import AiAnalystChat from "./AiAnalystChat";
import StockKPIGrid from "./StockKPIGrid";
import StockOverviewSidebar from "./StockOverviewSidebar";

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

export type TabKey =
  | "overview"
  | "technicals"
  | "financials"
  | "shareholding"
  | "health"
  | "checklist"
  | "ai"
  | "all";

interface StockPageClientProps {
  symbol: string;
  initialPrice?: PriceResponse | null;
  initialTechnicals?: TechnicalsResponse | null;
}

export default function StockPageClient({
  symbol,
  initialPrice,
  initialTechnicals,
}: StockPageClientProps) {
  const isInitialMount = useRef(true);
  const summary = getStockSummary(symbol);

  const [activeTab, setActiveTab] = useState<TabKey>("overview");
  const [range, setRange] = useState<RangeKey>("6M");

  useEffect(() => {
    if (typeof window !== "undefined") {
      const hash = window.location.hash.replace("#", "").toLowerCase();
      if (hash === "technicals" || hash === "chart") {
        setActiveTab("technicals");
      } else if (hash === "health" || hash === "diagnostics") {
        setActiveTab("health");
      } else if (hash === "financials" || hash === "fundamentals" || hash === "pl") {
        setActiveTab("financials");
      } else if (hash === "shareholding" || hash === "fii") {
        setActiveTab("shareholding");
      } else if (hash === "checklist" || hash === "multibagger") {
        setActiveTab("checklist");
      } else if (hash === "ai" || hash === "chat" || hash === "ask-ai") {
        setActiveTab("ai");
      } else if (hash === "all" || hash === "report") {
        setActiveTab("all");
      }
    }
  }, []);

  const [state, setState] = useState<State>(() => {
    if (initialPrice && initialTechnicals) {
      return {
        price: initialPrice,
        technicals: initialTechnicals,
        mlForecast: null,
        loading: false,
        error: null,
        notFound: false,
      };
    }
    return {
      price: null,
      technicals: null,
      mlForecast: null,
      loading: !summary,
      error: null,
      notFound: false,
    };
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

    // If initialPrice and initialTechnicals were provided for range="6M", skip refetching them on mount
    if (isInitialMount.current && initialPrice && initialTechnicals && range === "6M") {
      isInitialMount.current = false;
      getForecast(symbol)
        .then((mlForecast) => {
          if (!cancelled) setState((s) => ({ ...s, mlForecast }));
        })
        .catch(() => {});
      return;
    }
    isInitialMount.current = false;

    if (!summary && !state.price) {
      setState((s) => ({ ...s, loading: true, error: null, notFound: false }));
    }

    async function load() {
      try {
        const [price, technicals, mlForecast] = await Promise.all([
          getPrice(symbol, range),
          getTechnicals(symbol, range),
          getForecast(symbol).catch(() => null),
        ]);

        if (!cancelled) {
          setState({ price, technicals, mlForecast, loading: false, error: null, notFound: false });
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setState({ price: null, technicals: null, mlForecast: null, loading: false, error: err.detail, notFound: true });
        } else {
          const message = err instanceof ApiError ? err.detail : err instanceof Error ? err.message : "Unknown error";
          setState((s) => ({ ...s, loading: false, error: message }));
        }
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [symbol, range]);

  useEffect(() => {
    let cancelled = false;
    setPhase3((s) => ({ ...s, loading: true }));

    async function loadPhase3() {
      const scorePromise = getScore(symbol)
        .then((score) => {
          if (!cancelled) setPhase3((s) => ({ ...s, score, scoreError: null }));
        })
        .catch((err) => {
          if (!cancelled) setPhase3((s) => ({ ...s, scoreError: err instanceof ApiError ? err.detail : "Could not load score." }));
        });

      getEvidence(symbol, 50)
        .then((evidence) => {
          if (!cancelled && evidence) {
            const map = new Map<string, EvidenceItem>();
            evidence.items.forEach((item) => {
              map.set(item.id, item);
              if (item.metric_name && !map.has(item.metric_name)) {
                map.set(item.metric_name, item);
              }
            });
            setPhase3((s) => ({ ...s, evidenceById: map }));
          }
        })
        .catch(() => {});

      const momentumPromise = getMomentumScan(symbol)
        .then((momentum) => {
          if (!cancelled) setPhase3((s) => ({ ...s, momentum }));
        })
        .catch(() => {});

      const analystPromise = getAnalystRating(symbol)
        .then((analystRating) => {
          if (!cancelled) setPhase3((s) => ({ ...s, analystRating }));
        })
        .catch(() => {});

      getMarketRegime()
        .then((regime) => {
          if (!cancelled) setPhase3((s) => ({ ...s, regime }));
        })
        .catch(() => {});

      getFundamentals(symbol)
        .then((fundamentals) => {
          if (!cancelled) setPhase3((s) => ({ ...s, fundamentals, fundamentalsError: null }));
        })
        .catch((err) => {
          if (!cancelled) setPhase3((s) => ({ ...s, fundamentalsError: err instanceof ApiError ? err.detail : "Could not load fundamentals." }));
        });

      getStructuredData(symbol)
        .then((structuredData) => {
          if (!cancelled) setPhase3((s) => ({ ...s, structuredData }));
        })
        .catch(() => {});

      getStockDiagnostic(symbol)
        .then((diagnostic) => {
          if (!cancelled) setPhase3((s) => ({ ...s, diagnostic }));
        })
        .catch(() => {});

      Promise.allSettled([
        scorePromise,
        momentumPromise,
        analystPromise,
      ]).then(() => {
        if (!cancelled) setPhase3((s) => ({ ...s, loading: false }));
      });
    }

    loadPhase3();
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  if (state.loading && !summary && !initialPrice) {
    return (
      <div className="skeleton" style={{ padding: "3rem", textAlign: "center" }}>
        Loading {symbol} institutional research dossier…
      </div>
    );
  }

  if (state.notFound) {
    return (
      <div className="notice error">
        <strong>{symbol}</strong> was not found in the exchange universe. Check the ticker symbol or return to{" "}
        <Link href="/">dashboard</Link>.
      </div>
    );
  }

  if (state.error && !summary && !state.price) {
    return (
      <div className="notice error">
        Could not load data for <strong>{symbol}</strong>: {state.error ?? "unknown error"}
      </div>
    );
  }

  const price = state.price;
  const technicals = state.technicals;
  const bars = price?.bars ?? [];
  const latest = bars.length > 0 ? bars[bars.length - 1] : null;
  const previous = bars.length > 1 ? bars[bars.length - 2] : null;

  const currentPrice = latest ? latest.close : ((summary as any)?.price ?? (summary as any)?.last_close_price ?? null);
  const change = previous && latest ? latest.close - previous.close : (summary && summary.day_change_pct != null && currentPrice ? (currentPrice * summary.day_change_pct) / 100 : null);
  const changePct = previous && latest ? ((latest.close - previous.close) / previous.close) * 100 : (summary ? summary.day_change_pct : null);

  // High & Low 52-week values
  const high52w = price?.high_52w ?? (bars.length > 0 ? Math.max(...bars.map((b) => b.high)) : null);
  const low52w = price?.low_52w ?? (bars.length > 0 ? Math.min(...bars.map((b) => b.low)) : null);

  const effectivePrice: PriceResponse = price ?? {
    symbol,
    exchange: summary?.exchange ?? "NSE",
    company_name: summary?.company_name ?? symbol,
    logo_url: summary?.logo_url ?? null,
    sector: summary?.sector ?? null,
    industry: null,
    description: null,
    ai_summary: null,
    key_points: null,
    website_url: null,
    range,
    start_date: null,
    end_date: null,
    bars: [],
    data_freshness: {
      latest_trading_date: null,
      as_of: new Date().toISOString(),
      data_age_days: null,
      stale: false,
    },
    high_52w: null,
    low_52w: null,
    is_52w_breakout: summary?.is_52w_breakout ?? false,
    breakout_pct: null,
  };

  const effectiveMomentum: MomentumScanResponse | null = phase3.momentum ?? (summary && summary.momentum_pass !== null ? {
    instrument_id: "",
    symbol,
    exchange: summary.exchange,
    scan_date: new Date().toISOString().slice(0, 10),
    evaluable: true,
    passed: summary.momentum_pass,
    conditions: [
      { name: "T1", description: "Price > 150 & 200 SMA", passed: summary.momentum_pass, value: 0, threshold: 0 },
      { name: "T2", description: "150 SMA > 200 SMA", passed: summary.momentum_pass, value: 0, threshold: 0 },
      { name: "T3", description: "200 SMA trending up", passed: summary.momentum_pass, value: 0, threshold: 0 },
      { name: "T4", description: "50 SMA > 150 & 200 SMA", passed: summary.momentum_pass, value: 0, threshold: 0 },
      { name: "T5", description: "Price > 50 SMA", passed: summary.momentum_pass, value: 0, threshold: 0 },
      { name: "T6", description: "Price >= 30% above 52w Low", passed: summary.momentum_pass, value: 0, threshold: 0 },
      { name: "T7", description: "Price within 25% of 52w High", passed: summary.momentum_pass, value: 0, threshold: 0 },
      { name: "T8", description: "RS Rating >= 70", passed: summary.momentum_pass, value: 0, threshold: 0 },
    ],
    distance_from_52w_high_pct: summary.distance_from_52w_high_pct,
    rs_rank: null,
    rs_rank_universe: "broad_market",
    sma200_trend_lookback_days: 20,
    methodology_version: "minervini_v1",
    computed_at: new Date().toISOString(),
    reason: null,
    cache_hit: true,
    is_vcp_setup: summary.is_vcp_setup,
    vcp_reason: null,
  } : null);

  const effectiveAnalystRating: AnalystRatingResponse | null = phase3.analystRating ?? (summary && summary.analyst_recommendation ? {
    symbol,
    exchange: summary.exchange,
    has_coverage: true,
    target_mean_price: summary.analyst_target_price,
    target_high_price: null,
    target_low_price: null,
    target_median_price: summary.analyst_target_price,
    current_price: currentPrice,
    upside_pct: summary.analyst_upside_pct,
    recommendation_mean: null,
    recommendation_key: summary.analyst_recommendation,
    number_of_analyst_opinions: null,
    source: "market_data",
    source_timestamp: new Date().toISOString(),
    data_age_days: null,
    reason: null,
    cache_hit: true,
    is_vcp_setup: summary.is_vcp_setup,
    vcp_reason: null,
  } : null);

  const handleTabChange = (t: string) => {
    setActiveTab(t as TabKey);
    if (typeof window !== "undefined") {
      window.location.hash = t;
    }
  };

  return (
    <div className="stock-page-wrapper">
      {/* BREADCRUMB / BACK NAVIGATION */}
      <div className="stock-nav-breadcrumbs">
        <Link href="/" prefetch={true} className="breadcrumb-back-btn">
          <span className="breadcrumb-back-arrow">←</span>
          <span>Dashboard</span>
        </Link>
        <span className="breadcrumb-sep">/</span>
        <span className="breadcrumb-current-stock">{symbol}</span>
      </div>

      {/* 1. STOCK IDENTITY HEADER */}
      <TickerHeader
        symbol={symbol}
        companyName={effectivePrice.company_name}
        exchange={effectivePrice.exchange}
        sector={effectivePrice.sector}
        logoUrl={effectivePrice.logo_url}
        price={currentPrice}
        change={change}
        changePct={changePct}
        regime={phase3.regime}
        tvMomentumFlag={technicals?.tv_momentum_flag ?? summary?.tv_momentum_flag}
        tvSignal1d={technicals?.tv_signal_1d ?? summary?.tv_signal_1d}
        tvSignal1w={technicals?.tv_signal_1w ?? summary?.tv_signal_1w}
      />

      {/* 2. OVERVIEW TAB — 8-CARD KPI GRID */}
      <StockKPIGrid
        symbol={symbol}
        price={effectivePrice}
        momentum={effectiveMomentum}
        analystRating={effectiveAnalystRating}
        diagnostic={phase3.diagnostic}
        fundamentals={phase3.fundamentals}
        structuredData={phase3.structuredData}
        evidenceById={phase3.evidenceById}
        onTabChange={handleTabChange}
      />

      {/* 3. TAB NAVIGATION BAR */}
      <div className="stock-tabs-nav" role="tablist">
        <button
          type="button"
          role="tab"
          data-tab="overview"
          aria-selected={activeTab === "overview"}
          className={`stock-tab-btn ${activeTab === "overview" ? "active" : ""}`}
          onClick={() => handleTabChange("overview")}
        >
          <span>📊 Overview &amp; Charts</span>
        </button>
        <button
          type="button"
          role="tab"
          data-tab="technicals"
          aria-selected={activeTab === "technicals"}
          className={`stock-tab-btn ${activeTab === "technicals" ? "active" : ""}`}
          onClick={() => handleTabChange("technicals")}
        >
          <span>📈 Technicals</span>
        </button>
        <button
          type="button"
          role="tab"
          data-tab="financials"
          aria-selected={activeTab === "financials"}
          className={`stock-tab-btn ${activeTab === "financials" ? "active" : ""}`}
          onClick={() => handleTabChange("financials")}
        >
          <span>📑 Financials &amp; P&amp;L</span>
        </button>
        <button
          type="button"
          role="tab"
          data-tab="shareholding"
          aria-selected={activeTab === "shareholding"}
          className={`stock-tab-btn ${activeTab === "shareholding" ? "active" : ""}`}
          onClick={() => handleTabChange("shareholding")}
        >
          <span>👥 Shareholding</span>
        </button>
        <button
          type="button"
          role="tab"
          data-tab="health"
          aria-selected={activeTab === "health"}
          className={`stock-tab-btn ${activeTab === "health" ? "active" : ""}`}
          onClick={() => handleTabChange("health")}
        >
          <span>🛡️ Health &amp; Diagnostics</span>
          {phase3.diagnostic?.financial_health?.piotroski && (
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
          data-tab="checklist"
          aria-selected={activeTab === "checklist"}
          className={`stock-tab-btn ${activeTab === "checklist" ? "active" : ""}`}
          onClick={() => handleTabChange("checklist")}
        >
          <span>📋 Quality Checklist</span>
        </button>
        <button
          type="button"
          role="tab"
          data-tab="ai"
          aria-selected={activeTab === "ai"}
          className={`stock-tab-btn ai-tab ${activeTab === "ai" ? "active" : ""}`}
          onClick={() => handleTabChange("ai")}
        >
          <span>⚡ AI Analyst</span>
          <span className="stock-tab-badge up">Gemini</span>
        </button>
        <button
          type="button"
          role="tab"
          data-tab="all"
          aria-selected={activeTab === "all"}
          className={`stock-tab-btn ${activeTab === "all" ? "active" : ""}`}
          onClick={() => handleTabChange("all")}
        >
          <span>Full Report</span>
        </button>
      </div>

      {/* 4. TAB CONTENTS */}

      {/* TAB 1: OVERVIEW & CHARTS */}
      {(activeTab === "overview" || activeTab === "all") && (
        <div className="overview-two-column-layout">
          {/* LEFT COLUMN: INTERACTIVE CHART SUITE */}
          <div className="overview-chart-column">
            <div className="panel chart-container-panel">
              <div className="range-selector-row">
                <div className="range-selector">
                  {RANGE_KEYS.map((key) => (
                    <button
                      key={key}
                      className={key === range ? "active" : ""}
                      onClick={() => setRange(key)}
                    >
                      {key}
                    </button>
                  ))}
                </div>
                <div className="chart-legend-ticker">
                  <span className="legend-ohlc">
                    {latest ? (
                      <>
                        O <strong>{latest.open.toFixed(2)}</strong> H <strong>{latest.high.toFixed(2)}</strong> L <strong>{latest.low.toFixed(2)}</strong> C <strong>{latest.close.toFixed(2)}</strong>
                      </>
                    ) : (
                      <span>Loading timeframe OHLCV data…</span>
                    )}
                  </span>
                </div>
              </div>

              {bars.length === 0 || !technicals ? (
                <div
                  className="chart-loading-placeholder"
                  style={{
                    height: "440px",
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: "12px",
                    background: "var(--bg-panel)",
                    borderRadius: "8px",
                  }}
                >
                  <div
                    style={{
                      width: "36px",
                      height: "36px",
                      border: "3px solid var(--border)",
                      borderTopColor: "var(--accent)",
                      borderRadius: "50%",
                      animation: "spin 0.8s linear infinite",
                    }}
                  />
                  <span style={{ fontSize: "0.85rem", color: "var(--fg-muted)" }}>
                    Loading OHLCV candlestick chart &amp; overlays for {symbol}…
                  </span>
                </div>
              ) : (
                <StockCharts bars={bars} series={technicals.series} mlForecast={state.mlForecast} />
              )}
            </div>
          </div>

          {/* RIGHT COLUMN: SIGNAL SUMMARY, KEY LEVELS, RESEARCH SNAPSHOT & DRIVERS */}
          <StockOverviewSidebar
            symbol={symbol}
            price={effectivePrice}
            technicals={technicals}
            score={phase3.score}
            momentum={effectiveMomentum}
            currentPrice={currentPrice}
            high52w={high52w}
            low52w={low52w}
          />
        </div>
      )}

      {/* TAB 2: TECHNICALS */}
      {(activeTab === "technicals" || activeTab === "all") && (
        <div className="technicals-tab-view" style={{ marginTop: "1rem" }}>
          {technicals ? (
            <TechnicalSummaryPanel
              snapshot={technicals.snapshot}
              tvSignal1d={technicals.tv_signal_1d}
              tvSignal1w={technicals.tv_signal_1w}
              tvMomentumFlag={technicals.tv_momentum_flag}
            />
          ) : (
            <div className="panel" style={{ padding: "2rem", textAlign: "center" }}>
              Loading technical snapshot indicators…
            </div>
          )}

          {!phase3.loading && phase3.score && (
            <ComponentBreakdownPanel
              components={phase3.score.components}
              evidenceById={phase3.evidenceById}
            />
          )}

          {!phase3.loading && phase3.score && (
            <BullBearPanel
              bullCase={phase3.score.bull_case}
              bearCase={phase3.score.bear_case}
            />
          )}
        </div>
      )}

      {/* TAB 3: FINANCIALS & P&L */}
      {(activeTab === "financials" || activeTab === "all") && (
        <div style={{ marginTop: "1rem" }}>
          <FinancialsAndPlView
            symbol={symbol}
            fundamentals={phase3.fundamentals}
            structuredData={phase3.structuredData}
          />
        </div>
      )}

      {/* TAB 4: SHAREHOLDING */}
      {(activeTab === "shareholding" || activeTab === "all") && (
        <div style={{ marginTop: "1rem" }}>
          <ShareholdingView data={phase3.structuredData?.data as any} />
        </div>
      )}

      {/* TAB 5: HEALTH & DIAGNOSTICS */}
      {(activeTab === "health" || activeTab === "all") && (
        <div style={{ marginTop: "1rem" }}>
          <HealthDiagnostics
            diagnostic={phase3.diagnostic}
            structuredData={phase3.structuredData}
          />
        </div>
      )}

      {/* TAB 6: MULTIBAGGER CHECKLIST */}
      {(activeTab === "checklist" || activeTab === "all") && (
        <div style={{ marginTop: "1rem" }}>
          <StockChecklistPanel symbol={symbol} />
        </div>
      )}

      {/* TAB 7: AI ANALYST */}
      {(activeTab === "ai" || activeTab === "all") && (
        <div style={{ marginTop: "1rem" }}>
          <AiAnalystChat initialSymbol={symbol} isEmbedded={true} />
        </div>
      )}
    </div>
  );
}
