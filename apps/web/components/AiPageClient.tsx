"use client";

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
