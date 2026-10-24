"use client";

import Link from "next/link";
import { useSearchParams, useRouter } from "next/navigation";
import { useState, useEffect } from "react";
import AiAlphaPicksTab from "./AiAlphaPicksTab";
import AiAnalystChat from "./AiAnalystChat";

export default function AiPageClient() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const initialTab = searchParams.get("tab") === "chat" ? "chat" : "picks";
  const [activeTab, setActiveTab] = useState<"picks" | "chat">(initialTab);

  useEffect(() => {
    const tabParam = searchParams.get("tab");
    if (tabParam === "chat" || tabParam === "picks") {
      setActiveTab(tabParam);
    }
  }, [searchParams]);

  const handleTabChange = (tab: "picks" | "chat") => {
    setActiveTab(tab);
    router.replace(`/ai?tab=${tab}`, { scroll: false });
  };

  return (
    <div className="ai-hub-container">
      {/* Primary Global Navigation Tabs */}
      <div className="home-tabs-container" style={{ marginBottom: "1rem" }}>
        <div className="home-tabs-bar" role="tablist" aria-label="SignalForge main views">
          <Link
            href="/?tab=pulse"
            className="home-tab-pill"
            style={{ textDecoration: "none" }}
          >
            <span className="home-tab-icon">📊</span>
            <span className="home-tab-label">Market Pulse</span>
          </Link>

          <Link
            href="/?tab=ml_alpha"
            className="home-tab-pill"
            style={{ textDecoration: "none" }}
          >
            <span className="home-tab-icon">🤖</span>
            <span className="home-tab-label">5D ML Forecast Accuracy &amp; Directional Alpha</span>
          </Link>

          <Link
            href="/?tab=screener"
            className="home-tab-pill"
            style={{ textDecoration: "none" }}
          >
            <span className="home-tab-icon">⚡</span>
            <span className="home-tab-label">Quant Screener</span>
          </Link>

          <Link
            href="/ai?tab=picks"
            className="home-tab-pill active ai-picks-top-pill"
            style={{ textDecoration: "none" }}
          >
            <span className="home-tab-icon">🎯</span>
            <span className="home-tab-label">AI Alpha Picks (Top 10)</span>
          </Link>
        </div>
      </div>
      {/* Top Tab Bar Navigation */}
      <div className="ai-hub-topbar">
        <div className="ai-hub-header-left">
          <div className="ai-hub-title-row">
            <h1 className="ai-hub-main-title">
              <span>AI Alpha &amp; Research</span>
            </h1>
            <span className="ai-hub-status-tag">Live Production</span>
          </div>
          <p className="ai-hub-subtitle">
            Quantitative multi-factor machine reasoning &amp; institutional equity research
          </p>
        </div>

        <div className="ai-nav-tabs-wrapper">
          <button
            type="button"
            onClick={() => handleTabChange("picks")}
            className={`ai-nav-tab-btn ${activeTab === "picks" ? "active" : ""}`}
          >
            <span>🎯 Multi-Factor AI Alpha Picks</span>
            <span className="ai-nav-count-badge">Top 10</span>
          </button>

          <button
            type="button"
            onClick={() => handleTabChange("chat")}
            className={`ai-nav-tab-btn ${activeTab === "chat" ? "active" : ""}`}
          >
            <span>💬 Interactive Chat Analyst</span>
          </button>
        </div>
      </div>

      {/* Tab Content */}
      {activeTab === "picks" ? (
        <AiAlphaPicksTab />
      ) : (
        <AiAnalystChat isEmbedded={false} />
      )}
    </div>
  );
}
