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
  getRelativeStrength,
  getScore,
  getTechnicals,
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
  type RelativeStrengthResponse,
  type ScoreResponse,
  type TechnicalsResponse,
} from "../lib/types";
import StockCharts from "./StockCharts";
import TechnicalSummaryPanel from "./TechnicalSummaryPanel";
import RelativeStrengthPanel from "./RelativeStrengthPanel";
import TickerHeader from "./TickerHeader";
import ComponentBreakdownPanel from "./ComponentBreakdownPanel";
import BullBearPanel from "./BullBearPanel";
import FundamentalsPanel from "./FundamentalsPanel";

interface State {
  price: PriceResponse | null;
  technicals: TechnicalsResponse | null;
  relativeStrength: RelativeStrengthResponse | null;
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
  loading: boolean;
}

export default function StockPageClient({ symbol }: { symbol: string }) {
  const [range, setRange] = useState<RangeKey>("6M");
  const [state, setState] = useState<State>({
    price: null,
    technicals: null,
    relativeStrength: null,
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
    loading: true,
  });

  useEffect(() => {
    let cancelled = false;
    setState((s) => ({ ...s, loading: true, error: null, notFound: false }));

    async function load() {
      try {
        const [price, technicals, relativeStrength] = await Promise.all([
          getPrice(symbol, range),
          getTechnicals(symbol, range),
          getRelativeStrength(symbol),
        ]);
        if (!cancelled) {
          setState({ price, technicals, relativeStrength, loading: false, error: null, notFound: false });
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setState({ price: null, technicals: null, relativeStrength: null, loading: false, error: err.detail, notFound: true });
        } else {
          const message = err instanceof ApiError ? err.detail : err instanceof Error ? err.message : "Unknown error";
          setState({ price: null, technicals: null, relativeStrength: null, loading: false, error: message, notFound: false });
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
      let score: ScoreResponse | null = null;
      let scoreError: string | null = null;
      let evidenceById = new Map<string, EvidenceItem>();
      try {
        score = await getScore(symbol);
        const evidence = await getEvidence(symbol, 200);
        evidenceById = new Map(evidence.items.map((item) => [item.id, item]));
      } catch (err) {
        scoreError = err instanceof ApiError ? err.detail : "Could not load the research score.";
      }

      let fundamentals: FundamentalsResponse | null = null;
      let fundamentalsError: string | null = null;
      try {
        fundamentals = await getFundamentals(symbol);
      } catch (err) {
        fundamentalsError = err instanceof ApiError ? err.detail : "Could not load fundamentals.";
      }

      let regime: MarketRegimeResponse | null = null;
      try {
        regime = await getMarketRegime();
      } catch {
        regime = null; // Not yet computed - MarketRegimeBadge renders its own "not yet computed" state.
      }

      let momentum: MomentumScanResponse | null = null;
      try {
        momentum = await getMomentumScan(symbol);
      } catch {
        momentum = null; // Stage2Badge renders its own "loading/n/a" state - never blocks the rest of the page.
      }

      let analystRating: AnalystRatingResponse | null = null;
      try {
        analystRating = await getAnalystRating(symbol);
      } catch {
        analystRating = null; // AnalystTargetBadge renders its own "no coverage" state - never blocks the rest of the page.
      }

      if (!cancelled) {
        setPhase3({
          score,
          scoreError,
          evidenceById,
          fundamentals,
          fundamentalsError,
          regime,
          momentum,
          analystRating,
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

  if (state.error || !state.price || !state.technicals || !state.relativeStrength) {
    return (
      <div className="notice error">
        Could not load data for <strong>{symbol}</strong>: {state.error ?? "unknown error"}
      </div>
    );
  }

  const { price, technicals, relativeStrength } = state;
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
          price={latest.close}
          change={change}
          changePct={changePct}
          score={phase3.score}
          regime={phase3.regime}
          momentum={phase3.momentum}
          analystRating={phase3.analystRating}
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
          <StockCharts bars={bars} series={technicals.series} />
        )}
      </div>

      <TechnicalSummaryPanel snapshot={technicals.snapshot} />
      <RelativeStrengthPanel data={relativeStrength} />

      {!phase3.loading && phase3.score && (
        <>
          <ComponentBreakdownPanel components={phase3.score.components} evidenceById={phase3.evidenceById} />
          <BullBearPanel bullCase={phase3.score.bull_case} bearCase={phase3.score.bear_case} />
        </>
      )}

      {!phase3.loading && phase3.fundamentals && <FundamentalsPanel data={phase3.fundamentals} />}
      {!phase3.loading && !phase3.fundamentals && (
        <div className="panel">
          <h2>Fundamentals</h2>
          <div className="notice">Fundamentals unavailable: {phase3.fundamentalsError ?? "unknown error"}</div>
        </div>
      )}
    </>
  );
}
