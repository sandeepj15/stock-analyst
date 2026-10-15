import React, { useState } from "react";

interface Props {
  companyName?: string | null;
  symbol: string;
  sector?: string | null;
  industry?: string | null;
  description?: string | null;
  aiSummary?: string | null;
  keyPoints?: string | null;
  websiteUrl?: string | null;
}

export default function AboutCompanySection({
  companyName,
  symbol,
  sector,
  industry,
  description,
  aiSummary,
  keyPoints,
  websiteUrl,
}: Props) {
  const [showFullDescription, setShowFullDescription] = useState(false);
  const [showKeyPoints, setShowKeyPoints] = useState(true);

  const title = companyName ? `${companyName} (${symbol})` : symbol;
  const hasDescription = Boolean(description && description.trim().length > 0);
  const hasAiSummary = Boolean(aiSummary && aiSummary.trim().length > 0);
  const hasKeyPoints = Boolean(keyPoints && keyPoints.trim().length > 0);

  // If no data exists at all
  if (!hasDescription && !hasAiSummary && !sector) {
    return null;
  }

  const isLongDescription = hasDescription && (description?.length ?? 0) > 400;
  const displayDescription =
    isLongDescription && !showFullDescription
      ? description?.slice(0, 380) + "…"
      : description;

  const keyPointLines = keyPoints
    ? keyPoints
        .split("\n")
        .map((l) => l.trim())
        .filter((l) => l.length > 0)
    : [];

  return (
    <div className="panel about-company-panel">
      <div className="about-company-header">
        <div className="about-title-group">
          <h2 className="about-company-title">
            <span style={{ marginRight: "0.4rem" }}>🏢</span> About {title}
          </h2>
          <div className="about-badge-group">
            {sector && <span className="about-sector-badge">{sector}</span>}
            {industry && <span className="about-industry-badge">{industry}</span>}
          </div>
        </div>

        {websiteUrl && (
          <a
            href={websiteUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="about-website-btn"
            title={`Visit official website: ${websiteUrl}`}
          >
            <span>🌐 Website</span>
            <span style={{ fontSize: "0.75rem", opacity: 0.8 }}>↗</span>
          </a>
        )}
      </div>

      {/* AI BUSINESS SUMMARY BOX */}
      {hasAiSummary && (
        <div className="ai-summary-box">
          <div className="ai-summary-label">
            <span className="ai-sparkle-icon">✨</span>
            <span>AI Business Summary (In Simple Words)</span>
          </div>
          <p className="ai-summary-text">{aiSummary}</p>
        </div>
      )}

      {/* COMPANY FULL DESCRIPTION */}
      {hasDescription && (
        <div className="about-description-box">
          <h3 className="about-subheading">Company Overview</h3>
          <p className="about-description-text">{displayDescription}</p>
          {isLongDescription && (
            <button
              type="button"
              className="about-toggle-btn"
              onClick={() => setShowFullDescription(!showFullDescription)}
            >
              {showFullDescription ? "Show Less ▴" : "Read Full Profile ▾"}
            </button>
          )}
        </div>
      )}

      {/* KEY SEGMENTS & POINTS */}
      {hasKeyPoints && keyPointLines.length > 0 && (
        <div className="about-keypoints-box">
          <div
            className="about-keypoints-header"
            onClick={() => setShowKeyPoints(!showKeyPoints)}
            role="button"
            tabIndex={0}
          >
            <h3 className="about-subheading" style={{ margin: 0 }}>
              <span>📌 Key Business Segments &amp; Operations</span>
            </h3>
            <button type="button" className="about-toggle-btn" style={{ margin: 0 }}>
              {showKeyPoints ? "Hide ▴" : "Show ▾"}
            </button>
          </div>

          {showKeyPoints && (
            <div className="keypoints-list">
              {keyPointLines.map((line, idx) => (
                <div key={idx} className="keypoint-item">
                  <span className="keypoint-bullet">•</span>
                  <span className="keypoint-text">{line}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
