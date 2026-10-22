"use client";

import React, { useState, useEffect } from "react";
import { changeTone, formatInr, formatPct } from "../lib/format";
import type { MarketRegimeResponse } from "../lib/types";

interface Props {
  symbol: string;
  companyName?: string | null;
  exchange?: string | null;
  sector?: string | null;
  price: number | null;
  change: number | null;
  changePct: number | null;
  regime: MarketRegimeResponse | null;
  tvMomentumFlag?: string | null;
  tvSignal1d?: string | null;
  tvSignal1w?: string | null;
  logoUrl?: string | null;
}

export default function TickerHeader({
  symbol,
  companyName,
  exchange = "NSE",
  sector,
  price,
  change,
  changePct,
  regime,
  tvMomentumFlag,
  tvSignal1d,
  tvSignal1w,
  logoUrl,
}: Props) {
  const [inWatchlist, setInWatchlist] = useState(false);
  const [copied, setCopied] = useState(false);
  const [copiedTicker, setCopiedTicker] = useState(false);
  const [logoError, setLogoError] = useState(false);

  useEffect(() => {
    try {
      const saved = localStorage.getItem("signalforge_watchlist");
      if (saved) {
        const list = JSON.parse(saved);
        if (Array.isArray(list) && list.includes(symbol)) {
          setInWatchlist(true);
        }
      }
    } catch {}
  }, [symbol]);

  const toggleWatchlist = () => {
    try {
      const saved = localStorage.getItem("signalforge_watchlist");
      let list: string[] = saved ? JSON.parse(saved) : [];
      if (!Array.isArray(list)) list = [];
      if (inWatchlist) {
        list = list.filter((s) => s !== symbol);
        setInWatchlist(false);
      } else {
        list.push(symbol);
        setInWatchlist(true);
      }
      localStorage.setItem("signalforge_watchlist", JSON.stringify(list));
    } catch {}
  };

  const handleShare = () => {
    if (typeof window !== "undefined") {
      navigator.clipboard.writeText(window.location.href);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const tone = changeTone(change);
  const regimeLabel = regime?.regime
    ? regime.regime === "BULLISH_TREND"
      ? "Bullish Trend"
      : regime.regime === "BEARISH_TREND"
      ? "Bearish Trend"
      : regime.regime.replace(/_/g, " ")
    : "Neutral Market Regime";
  const isRegimeBull = regime?.regime === "BULLISH_TREND" || regime?.regime === "LOW_VOLATILITY";
  const isRegimeBear = regime?.regime === "BEARISH_TREND" || regime?.regime === "HIGH_VOLATILITY";

  return (
    <div className="stock-identity-header">
      {/* LEFT BLOCK: LOGO & COMPANY INFO */}
      <div className="stock-identity-left">
        <div className={`stock-logo-circle ${logoUrl && !logoError ? "has-img" : "fallback"}`}>
          {logoUrl && !logoError ? (
            <img
              src={logoUrl}
              alt={symbol}
              className="stock-logo-img"
              referrerPolicy="no-referrer"
              onError={() => setLogoError(true)}
            />
          ) : (
            <span className="stock-logo-fallback">{symbol.slice(0, 3)}</span>
          )}
        </div>
        <div className="stock-identity-details">
          <div className="stock-title-row">
            <h1 className="stock-company-name">{companyName || symbol}</h1>
          </div>
          <div className="stock-meta-tags">
            <span
              className="stock-symbol-badge copyable-badge"
              title={copiedTicker ? "Copied!" : `Click to copy symbol "${symbol}"`}
              onClick={() => {
                navigator.clipboard.writeText(symbol);
                setCopiedTicker(true);
                setTimeout(() => setCopiedTicker(false), 1800);
              }}
            >
              <span>{symbol}</span>
              <span className="badge-copy-icon">
                {copiedTicker ? (
                  <span className="copied-green">✓</span>
                ) : (
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                  </svg>
                )}
              </span>
            </span>
            <span className="stock-exchange-tag">{exchange || "NSE"}</span>
            {sector && <span className="stock-sector-tag">{sector}</span>}
          </div>
        </div>
      </div>

      {/* CENTER / REGIME STATUS */}
      <div className="stock-regime-wrap">
        <div className={`stock-regime-pill ${isRegimeBull ? "bull" : isRegimeBear ? "bear" : "neutral"}`}>
          <span className="regime-dot" />
          <span className="regime-text">
            <strong>{isRegimeBear ? "Bearish Market Regime" : isRegimeBull ? "Bullish Market Regime" : "Range-bound Market"}</strong>
            {" · "}
            {isRegimeBear ? "Broad market in downtrend" : isRegimeBull ? "Broad market in uptrend" : "Consolidating"}
          </span>
        </div>

        {tvMomentumFlag === "STRONG_BUY_BOTH" && (
          <span className="tv-badge tv-strong-buy-both" title="1D & 1W Strong Buy">
            🔥 2x Strong Buy
          </span>
        )}
        {tvMomentumFlag?.startsWith("STRONG_BUY") && tvMomentumFlag !== "STRONG_BUY_BOTH" && (
          <span className="tv-badge tv-strong-buy">
            🟢 Strong Buy
          </span>
        )}
      </div>

      {/* RIGHT BLOCK: PRICE & ACTIONS */}
      <div className="stock-identity-right">
        <div className="stock-price-block">
          {price !== null && <span className="stock-current-price num">{formatInr(price)}</span>}
          {change !== null && (
            <span className={`stock-change-badge tone-${tone}`}>
              {change >= 0 ? "+" : ""}
              {change.toFixed(2)} ({formatPct(changePct)})
            </span>
          )}
        </div>

        <div className="stock-actions-group">
          <button
            type="button"
            className={`btn-watchlist ${inWatchlist ? "active" : ""}`}
            onClick={toggleWatchlist}
          >
            <span>{inWatchlist ? "✓ Watchlisted" : "+ Add to Watchlist"}</span>
          </button>
          <button
            type="button"
            className="btn-share-icon"
            onClick={handleShare}
            title={copied ? "Link Copied!" : "Share Stock"}
          >
            {copied ? "✓" : "🔗"}
          </button>
        </div>
      </div>
    </div>
  );
}
