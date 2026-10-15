"use client";

import { useEffect, useRef, useState } from "react";
import { getAiStatus, getAiStockContext, postAiChat, streamAiChat } from "../lib/api";
import type { AiChatMessage, AiStatusResponse, AiStockContextResponse } from "../lib/types";

interface Props {
  initialSymbol?: string;
  isEmbedded?: boolean;
}

const DEFAULT_PROMPTS = [
  "Which stock has the best and healthiest PE for the long term?",
  "Evaluate valuation vs 3-year profit growth",
  "Is the Stage 2 momentum and 50/200 SMA trend aligned?",
  "Check debt-to-equity, cash flow, and interest safety",
  "Which 5 stocks have the highest research score in the database?",
];

export default function AiAnalystChat({ initialSymbol, isEmbedded = false }: Props) {
  const [symbol, setSymbol] = useState<string>(initialSymbol?.toUpperCase() ?? "");
  const [customTicker, setCustomTicker] = useState<string>("");
  const [messages, setMessages] = useState<AiChatMessage[]>([]);
  const [input, setInput] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(false);
  const [statusText, setStatusText] = useState<string>("");
  const [streamingContent, setStreamingContent] = useState<string>("");
  const [aiStatus, setAiStatus] = useState<AiStatusResponse | null>(null);
  const [stockContext, setStockContext] = useState<AiStockContextResponse | null>(null);
  const [showContextDrawer, setShowContextDrawer] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Poll status on mount
  useEffect(() => {
    let cancelled = false;
    getAiStatus()
      .then((st) => {
        if (!cancelled) setAiStatus(st);
      })
      .catch((e) => {
        if (!cancelled) {
          setAiStatus({
            connected: false,
            provider: "vertex_ai",
            location: "global",
            model: "gemini-2.5-flash",
            models: [],
            model_ready: false,
            error: e.message,
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Fetch ground truth when symbol changes
  useEffect(() => {
    if (!symbol) {
      setStockContext(null);
      return;
    }
    let cancelled = false;
    getAiStockContext(symbol)
      .then((ctx) => {
        if (!cancelled) setStockContext(ctx);
      })
      .catch(() => {
        if (!cancelled) setStockContext(null);
      });
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  // Auto-scroll on messages or stream update
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, streamingContent]);

  const handleSend = async (textToSend?: string) => {
    const query = (textToSend ?? input).trim();
    if (!query || loading) return;

    setInput("");
    setError(null);

    const userMsg: AiChatMessage = { role: "user", content: query };
    const newHistory = [...messages, userMsg];
    setMessages(newHistory);
    setLoading(true);
    setStreamingContent("");
    setStatusText("Analyzing query & scanning database...");

    try {
      let accumulated = "";
      await streamAiChat(
        {
          message: query,
          symbol: symbol || undefined,
          history: newHistory,
        },
        (token) => {
          accumulated += token;
          setStreamingContent(accumulated);
        },
        (meta) => {
          // metadata event
        },
        (status) => {
          setStatusText(status);
        }
      );

      // If stream ended with no tokens, fallback to non-streaming POST endpoint
      if (!accumulated.trim()) {
        try {
          setStatusText("Synthesizing institutional analysis...");
          const fallbackRes = await postAiChat({
            message: query,
            symbol: symbol || undefined,
            history: newHistory,
          });
          accumulated = fallbackRes.response;
        } catch (postErr: any) {
          throw new Error(postErr.detail || postErr.message || "Failed to complete AI response. Please retry.");
        }
      }

      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: accumulated || "No response received." },
      ]);
      setStreamingContent("");
    } catch (err: any) {
      setError(err.message || "Failed to get AI response");
    } finally {
      setLoading(false);
      setStatusText("");
      setTimeout(() => textareaRef.current?.focus(), 50);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleSelectSymbol = (sym: string) => {
    setSymbol(sym.toUpperCase());
    setCustomTicker("");
  };

  const handleCustomTickerSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (customTicker.trim()) {
      handleSelectSymbol(customTicker.trim());
    }
  };

  const modelDisplay = aiStatus?.model
    ? aiStatus.model
        .replace("publishers/google/models/", "")
        .replace("gemini-", "Gemini ")
    : "Gemini 3.5 Flash";

  return (
    <div className={`ai-analyst-container ${isEmbedded ? "embedded" : ""}`}>
      {/* HEADER */}
      <div className="ai-header-card">
        <div className="ai-header-left">
          <div className="ai-badge-group">
            <span className="ai-title-badge">
              <span className="ai-sparkle">⚡</span> SignalForge AI Analyst
            </span>
            <span className={`ai-status-pill ${aiStatus?.connected ? "online" : "offline"}`}>
              <span className={`ai-status-dot ${aiStatus?.connected ? "online" : "offline"}`} />
              Vertex AI ({modelDisplay} · global)
            </span>
            <span className="ai-status-pill">
              <span className="ai-status-dot online" />
              Live PostgreSQL Connected
            </span>
          </div>
          <p className="ai-subtitle">
            Quantitative analysis powered by Google Cloud Vertex AI &amp; live SignalForge PostgreSQL database.
          </p>
        </div>

        {/* ACTIVE STOCK SELECTION BAR */}
        {!isEmbedded && (
          <div className="ai-ticker-selector">
            <div className="ai-selector-label">Target Universe / Stock Context:</div>
            <div className="ai-ticker-pills">
              <button
                type="button"
                className={`ai-ticker-pill ${symbol === "" ? "active" : ""}`}
                onClick={() => handleSelectSymbol("")}
              >
                🌐 Universe Wide (Cross-Stock Screening)
              </button>
              {["WIPRO", "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "TATAMOTORS"].map((t) => (
                <button
                  key={t}
                  type="button"
                  className={`ai-ticker-pill ${symbol === t ? "active" : ""}`}
                  onClick={() => handleSelectSymbol(t)}
                >
                  {t}
                </button>
              ))}
            </div>

            <form onSubmit={handleCustomTickerSubmit} className="ai-custom-ticker-form">
              <input
                type="text"
                placeholder="Enter any NSE ticker (e.g. TITAN, ITC, BEL)..."
                value={customTicker}
                onChange={(e) => setCustomTicker(e.target.value.toUpperCase())}
                className="ai-ticker-input"
              />
              <button type="submit" className="ai-ticker-submit-btn">
                Select
              </button>
            </form>
          </div>
        )}

        {/* ACTIVE STOCK SNAPSHOT DRAWER */}
        {symbol && stockContext && (
          <div className="ai-active-stock-bar">
            <div className="ai-active-stock-info">
              <span className="ai-stock-tag">{stockContext.symbol}</span>
              <span className="ai-stock-company">{stockContext.company_name}</span>
            </div>
            <button
              type="button"
              className="ai-context-toggle-btn"
              onClick={() => setShowContextDrawer(!showContextDrawer)}
            >
              {showContextDrawer ? "Hide Live DB Snapshot ▲" : "View Live DB Snapshot ▼"}
            </button>
          </div>
        )}

        {showContextDrawer && stockContext && (
          <div className="ai-context-drawer">
            <div className="ai-context-drawer-header">
              <span>PostgreSQL Injected Context ({stockContext.symbol})</span>
              <span className="ai-db-live-tag">100% GROUND TRUTH</span>
            </div>
            <pre className="ai-context-pre">{stockContext.formatted_context}</pre>
          </div>
        )}
      </div>

      {/* QUICK PROMPT CHIPS */}
      <div className="ai-chips-bar">
        <span className="ai-chips-label">Suggested:</span>
        <div className="ai-chips-list">
          {DEFAULT_PROMPTS.map((chip, idx) => (
            <button
              key={idx}
              type="button"
              className="ai-prompt-chip"
              onClick={() => handleSend(chip)}
              disabled={loading}
            >
              {chip}
            </button>
          ))}
        </div>
      </div>

      {/* MESSAGES SCROLL AREA */}
      <div className="ai-messages-scroll" ref={scrollRef}>
        {messages.length === 0 && !streamingContent && (
          <div className="ai-empty-state">
            <div className="ai-empty-icon">📈</div>
            <h3>
              {symbol
                ? `Ask anything about ${symbol} or query the database`
                : "Ask any quantitative or screening question"}
            </h3>
            <p>
              Ask about valuation ratios (P/E, ROCE, ROE), 3-year profit trends, Minervini Stage 2
              conditions, Piotroski health scores, or compare across the 1,510 stocks in the database.
            </p>
          </div>
        )}

        {messages.map((msg, idx) => (
          <div key={idx} className={`ai-message-row ${msg.role === "user" ? "user-row" : "assistant-row"}`}>
            <div className="ai-message-avatar">
              {msg.role === "user" ? "👤" : "⚡"}
            </div>
            <div className="ai-message-content-wrapper">
              <div className="ai-message-author">
                {msg.role === "user" ? "You" : `SignalForge Analyst (${modelDisplay})`}
              </div>
              <div className="ai-message-bubble">
                <MarkdownRenderer content={msg.content} />
              </div>
            </div>
          </div>
        ))}

        {/* STREAMING MESSAGE BUBBLE */}
        {streamingContent && (
          <div className="ai-message-row assistant-row">
            <div className="ai-message-avatar">⚡</div>
            <div className="ai-message-content-wrapper">
              <div className="ai-message-author">{`SignalForge Analyst (${modelDisplay})`}</div>
              <div className="ai-message-bubble">
                <MarkdownRenderer content={streamingContent} />
                <span className="ai-cursor-pulse">▋</span>
              </div>
            </div>
          </div>
        )}

        {/* LOADING TYPING INDICATOR */}
        {loading && !streamingContent && (
          <div className="ai-message-row assistant-row">
            <div className="ai-message-avatar">⚡</div>
            <div className="ai-message-content-wrapper">
              <div className="ai-typing-indicator">
                <span className="ai-dot" />
                <span className="ai-dot" />
                <span className="ai-dot" />
                <span className="ai-typing-label">{statusText || "Analyzing live database..."}</span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ERROR BANNER */}
      {error && (
        <div className="ai-error-banner">
          ⚠️ {error}
        </div>
      )}

      {/* INPUT AREA */}
      <div className="ai-input-footer">
        <div className="ai-input-box-wrapper">
          <textarea
            ref={textareaRef}
            rows={2}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              symbol
                ? `Ask about ${symbol} or query database (e.g., 'Compare PE with sector', 'Is Stage 2 met?')...`
                : "Ask any stock screening question (e.g., 'Which stock has the healthiest PE for long term?')..."
            }
            className="ai-chat-textarea"
            disabled={loading}
          />
          <div className="ai-input-actions">
            {messages.length > 0 && (
              <button
                type="button"
                className="ai-clear-btn"
                onClick={() => setMessages([])}
                title="Clear chat history"
              >
                Clear
              </button>
            )}
            <button
              type="button"
              className="ai-send-btn"
              onClick={() => handleSend()}
              disabled={loading || !input.trim()}
            >
              {loading ? "Thinking..." : "Send ↑"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * Lightweight, zero-dependency Markdown renderer for financial analysis outputs.
 * Parses tables, headers, bold metrics, bullet lists, numbered lists, dividers, quotes, and code spans.
 */
function MarkdownRenderer({ content }: { content: string }) {
  const parseInline = (text: string) => {
    // 1. Code spans `code`
    const codeParts = text.split(/`([^`]+)`/g);
    return codeParts.map((part, pIdx) => {
      if (pIdx % 2 === 1) {
        return (
          <code key={pIdx} className="ai-md-code">
            {part}
          </code>
        );
      }
      // 2. Bold **bold**
      const boldParts = part.split(/\*\*([^*]+)\*\*/g);
      return boldParts.map((bPart, bIdx) => {
        if (bIdx % 2 === 1) {
          return (
            <strong key={bIdx} className="ai-md-strong">
              {bPart}
            </strong>
          );
        }
        // 3. Italic *italic*
        const italicParts = bPart.split(/\*([^*]+)\*/g);
        return italicParts.map((iPart, iIdx) => {
          if (iIdx % 2 === 1) {
            return (
              <em key={iIdx} className="ai-md-em">
                {iPart}
              </em>
            );
          }
          return iPart;
        });
      });
    });
  };

  const rawLines = content.split("\n");
  const blocks: Array<
    | { type: "h2"; text: string }
    | { type: "h3"; text: string }
    | { type: "h4"; text: string }
    | { type: "bold-heading"; text: string }
    | { type: "hr" }
    | { type: "blockquote"; text: string }
    | { type: "bullet"; num?: string; text: string }
    | { type: "table"; headers: string[]; rows: string[][] }
    | { type: "p"; text: string }
    | { type: "spacer" }
  > = [];

  let i = 0;
  while (i < rawLines.length) {
    const line = rawLines[i];
    const trimmed = line.trim();

    // Check for Markdown table start
    if (trimmed.startsWith("|") && trimmed.endsWith("|") && trimmed.length > 2) {
      const tableLines: string[] = [];
      while (i < rawLines.length && rawLines[i].trim().startsWith("|") && rawLines[i].trim().endsWith("|")) {
        tableLines.push(rawLines[i].trim());
        i++;
      }
      if (tableLines.length >= 2) {
        const headers = tableLines[0]
          .slice(1, -1)
          .split("|")
          .map((c) => c.trim());
        const isSeparator = /^\|?(\s*:?-+:?\s*\|?)+$/.test(tableLines[1]);
        const dataLines = isSeparator ? tableLines.slice(2) : tableLines.slice(1);
        const rows = dataLines.map((rowLine) =>
          rowLine
            .slice(1, -1)
            .split("|")
            .map((c) => c.trim())
        );
        blocks.push({ type: "table", headers, rows });
        continue;
      } else {
        blocks.push({ type: "p", text: tableLines[0] });
        continue;
      }
    }

    if (trimmed === "---" || trimmed === "***" || trimmed === "___") {
      blocks.push({ type: "hr" });
      i++;
      continue;
    }

    if (trimmed.startsWith("# ")) {
      blocks.push({ type: "h2", text: trimmed.substring(2) });
      i++;
      continue;
    }

    if (trimmed.startsWith("## ")) {
      blocks.push({ type: "h3", text: trimmed.substring(3) });
      i++;
      continue;
    }

    if (trimmed.startsWith("### ")) {
      blocks.push({ type: "h4", text: trimmed.substring(4) });
      i++;
      continue;
    }

    if (trimmed.startsWith("> ")) {
      blocks.push({ type: "blockquote", text: trimmed.substring(2) });
      i++;
      continue;
    }

    if (trimmed.startsWith("- ") || trimmed.startsWith("* ") || trimmed.startsWith("+ ")) {
      blocks.push({ type: "bullet", text: trimmed.substring(2) });
      i++;
      continue;
    }

    const numMatch = trimmed.match(/^(\d+)\.\s+(.*)$/);
    if (numMatch) {
      blocks.push({ type: "bullet", num: numMatch[1], text: numMatch[2] });
      i++;
      continue;
    }

    if (trimmed.startsWith("**") && trimmed.endsWith("**") && !trimmed.includes("\n") && trimmed.length > 4) {
      blocks.push({ type: "bold-heading", text: trimmed });
      i++;
      continue;
    }

    if (trimmed === "") {
      blocks.push({ type: "spacer" });
      i++;
      continue;
    }

    blocks.push({ type: "p", text: trimmed });
    i++;
  }

  return (
    <div className="ai-markdown-render">
      {blocks.map((block, idx) => {
        if (block.type === "h2") {
          return (
            <h3 key={idx} className="ai-md-h2">
              {parseInline(block.text)}
            </h3>
          );
        }
        if (block.type === "h3") {
          return (
            <h3 key={idx} className="ai-md-h3">
              {parseInline(block.text)}
            </h3>
          );
        }
        if (block.type === "h4") {
          return (
            <h4 key={idx} className="ai-md-h4">
              {parseInline(block.text)}
            </h4>
          );
        }
        if (block.type === "hr") {
          return <hr key={idx} className="ai-md-hr" />;
        }
        if (block.type === "bold-heading") {
          return (
            <div key={idx} className="ai-md-bold-heading">
              {parseInline(block.text)}
            </div>
          );
        }
        if (block.type === "blockquote") {
          return (
            <blockquote key={idx} className="ai-md-quote">
              {parseInline(block.text)}
            </blockquote>
          );
        }
        if (block.type === "bullet") {
          return (
            <div key={idx} className="ai-md-bullet">
              {block.num ? (
                <span className="ai-bullet-num">{block.num}.</span>
              ) : (
                <span className="ai-bullet-dot">•</span>
              )}
              <span>{parseInline(block.text)}</span>
            </div>
          );
        }
        if (block.type === "table") {
          return (
            <div key={idx} className="ai-md-table-wrapper">
              <table className="ai-md-table">
                <thead>
                  <tr>
                    {block.headers.map((h, hIdx) => (
                      <th key={hIdx}>{parseInline(h)}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {block.rows.map((row, rIdx) => (
                    <tr key={rIdx}>
                      {row.map((cell, cIdx) => (
                        <td key={cIdx}>{parseInline(cell)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }
        if (block.type === "spacer") {
          return <div key={idx} className="ai-md-spacer" />;
        }
        return (
          <p key={idx} className="ai-md-p">
            {parseInline(block.text)}
          </p>
        );
      })}
    </div>
  );
}
