"use client";

import { memo, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { listInstruments, prefetchStock } from "../lib/api";
import { saveStockSummary } from "../lib/stockSummaryCache";
import { bandColor } from "../lib/bands";
import { sortInstrumentsMulti } from "../lib/sort";
import type { InstrumentSortKey, InstrumentSummary, SortCriterion, SortOrder } from "../lib/types";
import MarketPulse from "./MarketPulse";
import MlPerformanceWidget from "./MlPerformanceWidget";
import StockChecklistPanel from "./StockChecklistPanel";

interface Column {
  key: InstrumentSortKey;
  label: string;
}

const COLUMNS: Column[] = [
  { key: "symbol", label: "Instrument" },
  { key: "sector", label: "Sector" },
  { key: "score", label: "Score" },
  { key: "fundamental_score", label: "Fund Score" },
  { key: "is_multibagger", label: "Multibagger" },
  { key: "momentum_pass", label: "Stage 2" },
  { key: "is_vcp_setup", label: "VCP" },
  { key: "tv_momentum_flag", label: "TV Signal" },
  { key: "analyst_recommendation", label: "Analyst Rating" },
  { key: "day_change_pct", label: "1D %" },
  { key: "return_1w_pct" as any, label: "1W %" },
  { key: "return_1m_pct" as any, label: "1M %" },
  { key: "return_3m_pct" as any, label: "3M %" },
  { key: "return_1y_pct" as any, label: "1Y %" },
  { key: "revenue_growth_yoy", label: "Rev YoY" },
  { key: "pat_growth_yoy", label: "PAT YoY" },
  { key: "fii_change_qoq_pct" as any, label: "FII Δ %" },
  { key: "analyst_upside_pct", label: "Target" },
  { key: "ml_forecast_5d_pct", label: "5D ML %" },
];

const ScoreCell = memo(function ScoreCell({ row }: { row: InstrumentSummary }) {
  if (row.score === null || row.band === null) {
    return <span className="score-cell unscored">not yet scored</span>;
  }
  const color = bandColor(row.band);
  return (
    <span className="score-cell num" style={{ color }}>
      {row.score.toFixed(0)}
      <span className="score-band-pill" style={{ color }}>
        {row.band}
      </span>
    </span>
  );
});

const FundamentalScoreCell = memo(function FundamentalScoreCell({ row }: { row: InstrumentSummary }) {
  if (row.fundamental_score === null || row.fundamental_band === null) {
    return <span className="score-cell unscored">—</span>;
  }
  const color = bandColor(row.fundamental_band);
  return (
    <span className="score-cell num" style={{ color }}>
      {row.fundamental_score.toFixed(0)}
      <span className="score-band-pill" style={{ color }}>
        {row.fundamental_band}
      </span>
    </span>
  );
});

const MultibaggerCell = memo(function MultibaggerCell({
  row,
  onOpenChecklist,
}: {
  row: InstrumentSummary;
  onOpenChecklist: (symbol: string) => void;
}) {
  if (!row.is_multibagger) {
    return <span className="stage2-badge stage2-na">—</span>;
  }
  return (
    <button
      type="button"
      className="chk-quality-badge band-exceptional"
      style={{
        cursor: "pointer",
        fontSize: "0.72rem",
        padding: "2px 8px",
        borderRadius: "4px",
        fontWeight: 700,
        border: "none",
        display: "inline-flex",
        alignItems: "center",
        gap: "4px",
      }}
      title={`Click to view 6/6 Multibagger Checklist for ${row.symbol}`}
      onClick={(e) => {
        e.stopPropagation();
        onOpenChecklist(row.symbol);
      }}
    >
      🌟 6/6 Met
    </button>
  );
});

const ReturnCell = memo(function ReturnCell({ val }: { val: number | null }) {
  if (val === null) {
    return <span className="day-change flat">—</span>;
  }
  const tone = val > 0 ? "up" : val < 0 ? "down" : "flat";
  const sign = val > 0 ? "+" : "";
  return (
    <span className={`day-change num ${tone}`}>
      {sign}
      {val.toFixed(2)}%
    </span>
  );
});

const DayChangeCell = memo(function DayChangeCell({ row }: { row: InstrumentSummary }) {
  return <ReturnCell val={row.day_change_pct} />;
});

const FiiChangeCell = memo(function FiiChangeCell({ row }: { row: InstrumentSummary }) {
  const change = row.fii_change_qoq_pct;
  const current = row.fii_current;
  if (change === null || change === undefined) {
    return <span className="day-change flat" title="No shareholding data available">—</span>;
  }
  const tone = change > 0 ? "up" : change < 0 ? "down" : "flat";
  const sign = change > 0 ? "+" : "";
  const arrow = change > 0 ? "▲ " : change < 0 ? "▼ " : "";
  return (
    <div
      className="fii-change-cell"
      style={{ display: "inline-flex", flexDirection: "column", alignItems: "flex-end", lineHeight: 1.15 }}
      title={`FII Holding: ${current !== null && current !== undefined ? current.toFixed(2) + "%" : "N/A"}\nQoQ Change: ${sign}${change.toFixed(2)}%`}
    >
      <span className={`day-change num ${tone}`} style={{ fontWeight: 600 }}>
        {arrow}{sign}{change.toFixed(2)}%
      </span>
      {current !== null && current !== undefined && (
        <span style={{ fontSize: "0.68rem", color: "var(--fg-muted)", opacity: 0.85 }}>
          {current.toFixed(1)}% FII
        </span>
      )}
    </div>
  );
});

const GrowthCell = memo(function GrowthCell({ val }: { val: number | null }) {
  if (val === null) {
    return <span className="day-change flat">—</span>;
  }
  const pctVal = val * 100;
  const tone = pctVal > 0 ? "up" : pctVal < 0 ? "down" : "flat";
  const sign = pctVal > 0 ? "+" : "";
  return (
    <span className={`day-change num ${tone}`}>
      {sign}
      {pctVal.toFixed(1)}%
    </span>
  );
});

const AnalystTargetCell = memo(function AnalystTargetCell({ row }: { row: InstrumentSummary }) {
  if (row.analyst_target_price === null || row.analyst_upside_pct === null) {
    return <span className="analyst-cell no-coverage">No coverage</span>;
  }
  const tone = row.analyst_upside_pct > 0 ? "up" : row.analyst_upside_pct < 0 ? "down" : "flat";
  const sign = row.analyst_upside_pct > 0 ? "+" : "";
  return (
    <span className="analyst-cell">
      <span className="analyst-target-price num">₹{row.analyst_target_price.toFixed(2)}</span>
      <span className={`analyst-upside num ${tone}`}>
        {sign}
        {row.analyst_upside_pct.toFixed(1)}%
      </span>
    </span>
  );
});

const VCPCell = memo(function VCPCell({ row }: { row: InstrumentSummary }) {
  if (row.is_vcp_setup === null) return <span className="stage2-badge stage2-na">—</span>;
  if (row.is_vcp_setup) return <span className="stage2-badge stage2-pass">✓ Setup</span>;
  return <span className="stage2-badge stage2-fail">No</span>;
});

const TVSignalCell = memo(function TVSignalCell({ row }: { row: InstrumentSummary }) {
  const flag = row.tv_momentum_flag;
  const sig1d = row.tv_signal_1d ?? "NEUTRAL";
  const sig1w = row.tv_signal_1w ?? "NEUTRAL";

  if (!flag) {
    return (
      <span
        title={`TradingView TA · 1D: ${sig1d} · 1W: ${sig1w}`}
        style={{ color: "var(--text-muted)", opacity: 0.5, fontSize: "0.85rem" }}
      >
        —
      </span>
    );
  }

  if (flag === "STRONG_BUY_BOTH") {
    return (
      <span
        className="tv-badge tv-strong-buy-both"
        title="TradingView TA: 1D STRONG BUY & 1W STRONG BUY (Dual Timeframe Momentum)"
      >
        🔥 2x STRONG BUY
      </span>
    );
  }
  if (flag === "STRONG_BUY_1D") {
    return (
      <span
        className="tv-badge tv-strong-buy"
        title={`TradingView TA: 1D STRONG BUY · 1W ${sig1w}`}
      >
        🟢 STRONG BUY (1D)
      </span>
    );
  }
  if (flag === "STRONG_BUY_1W") {
    return (
      <span
        className="tv-badge tv-strong-buy"
        title={`TradingView TA: 1D ${sig1d} · 1W STRONG BUY`}
      >
        🟢 STRONG BUY (1W)
      </span>
    );
  }
  if (flag === "STRONG_SELL_BOTH") {
    return (
      <span
        className="tv-badge tv-strong-sell-both"
        title="TradingView TA: 1D STRONG SELL & 1W STRONG SELL (Dual Timeframe Breakdown)"
      >
        🚨 2x STRONG SELL
      </span>
    );
  }
  if (flag === "STRONG_SELL_1D") {
    return (
      <span
        className="tv-badge tv-strong-sell"
        title={`TradingView TA: 1D STRONG SELL · 1W ${sig1w}`}
      >
        🔴 STRONG SELL (1D)
      </span>
    );
  }
  if (flag === "STRONG_SELL_1W") {
    return (
      <span
        className="tv-badge tv-strong-sell"
        title={`TradingView TA: 1D ${sig1d} · 1W STRONG SELL`}
      >
        🔴 STRONG SELL (1W)
      </span>
    );
  }

  return <span style={{ color: "var(--text-muted)", opacity: 0.5 }}>—</span>;
});

const AnalystRatingCell = memo(function AnalystRatingCell({ row }: { row: InstrumentSummary }) {
  const rec = row.analyst_recommendation?.toUpperCase();
  if (!rec) {
    return <span style={{ color: "var(--text-muted)", opacity: 0.5, fontSize: "0.85rem" }}>—</span>;
  }

  if (rec === "STRONG_BUY") {
    return (
      <span className="tv-badge tv-strong-buy" title="TradingView Analyst Rating: Strong Buy">
        🟢 Strong Buy
      </span>
    );
  }
  if (rec === "BUY") {
    return (
      <span className="tv-badge tv-buy" title="TradingView Analyst Rating: Buy">
        ▲ Buy
      </span>
    );
  }
  if (rec === "SELL") {
    return (
      <span className="tv-badge tv-sell" title="TradingView Analyst Rating: Sell">
        ▼ Sell
      </span>
    );
  }
  if (rec === "STRONG_SELL") {
    return (
      <span className="tv-badge tv-strong-sell" title="TradingView Analyst Rating: Strong Sell">
        🔴 Strong Sell
      </span>
    );
  }

  return <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>{rec}</span>;
});


const Stage2Cell = memo(function Stage2Cell({ row }: { row: InstrumentSummary }) {
  const isBreakout = row.is_52w_breakout === true || (row.distance_from_52w_high_pct !== null && row.distance_from_52w_high_pct > 0);
  const breakoutText = row.distance_from_52w_high_pct !== null && row.distance_from_52w_high_pct > 0
    ? `💥 52W High (+${row.distance_from_52w_high_pct.toFixed(1)}%)`
    : "💥 52W High";

  if (row.momentum_pass === null) {
    if (isBreakout) {
      return (
        <span
          className="stage2-badge"
          style={{
            background: "rgba(249, 115, 22, 0.15)",
            color: "#ea580c",
            border: "1px solid rgba(249, 115, 22, 0.4)",
            fontWeight: 700,
            padding: "2px 6px",
            borderRadius: "4px",
            fontSize: "0.75rem",
          }}
          title="Closing strictly above 52-Week High (Breakout)"
        >
          {breakoutText}
        </span>
      );
    }
    return <span className="stage2-badge stage2-na">—</span>;
  }
  if (row.momentum_pass) {
    return (
      <span
        className="stage2-badge stage2-pass"
        style={
          isBreakout
            ? {
                background: "rgba(249, 115, 22, 0.18)",
                color: "#ea580c",
                borderColor: "rgba(249, 115, 22, 0.45)",
                fontWeight: 700,
              }
            : undefined
        }
        title={isBreakout ? "Closing strictly above 52-Week High (Breakout)" : undefined}
      >
        {isBreakout ? breakoutText : "✓ Pass"}
        {!isBreakout && row.distance_from_52w_high_pct !== null && (
          <span className="stage2-distance num"> {row.distance_from_52w_high_pct.toFixed(1)}%</span>
        )}
      </span>
    );
  }
  return (
    <span
      className="stage2-badge stage2-fail"
      style={
        isBreakout
          ? {
              background: "rgba(249, 115, 22, 0.18)",
              color: "#ea580c",
              borderColor: "rgba(249, 115, 22, 0.45)",
              fontWeight: 700,
            }
          : undefined
      }
      title={isBreakout ? "Closing strictly above 52-Week High (Breakout)" : undefined}
    >
      {isBreakout ? breakoutText : "✗ Fail"}
      {!isBreakout && row.distance_from_52w_high_pct !== null && (
        <span className="stage2-distance num"> {row.distance_from_52w_high_pct.toFixed(1)}%</span>
      )}
    </span>
  );
});

function getPaginationPages(currentPage: number, totalPages: number): (number | "...")[] {
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, i) => i + 1);
  }
  if (currentPage <= 4) {
    return [1, 2, 3, 4, 5, "...", totalPages];
  }
  if (currentPage >= totalPages - 3) {
    return [1, "...", totalPages - 4, totalPages - 3, totalPages - 2, totalPages - 1, totalPages];
  }
  return [1, "...", currentPage - 1, currentPage, currentPage + 1, "...", totalPages];
}

export default function HomeBrowser({ initialInstruments }: { initialInstruments: InstrumentSummary[] }) {
  const router = useRouter();
  const pathname = usePathname();
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query);

  const [instruments, setInstruments] = useState<InstrumentSummary[]>(initialInstruments);
  const [sortCriteria, setSortCriteria] = useState<SortCriterion[]>([
    { key: "day_change_pct", order: "desc" },
  ]);
  const [pageSize, setPageSize] = useState<number>(50);
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [refreshing, setRefreshing] = useState(false);
  const tableScrollRef = useRef<HTMLDivElement>(null);
  type FilterPreset = "all" | "ml_bullish" | "ml_bearish" | "stage2" | "breakout" | "multibagger" | "multibagger_stage2" | "tv_strong_buy" | "watchlist";
  const [filterPreset, setFilterPreset] = useState<FilterPreset>("all");
  type HomeTab = "pulse" | "ml_alpha" | "screener";
  const [homeTab, setHomeTab] = useState<HomeTab>("screener");
  const [modalSymbol, setModalSymbol] = useState<string | null>(null);
  const [watchlist, setWatchlist] = useState<string[]>([]);
  const [navigatingSymbol, setNavigatingSymbol] = useState<string | null>(null);
  const [copiedSymbol, setCopiedSymbol] = useState<string | null>(null);

  useEffect(() => {
    setNavigatingSymbol(null);
  }, [pathname]);

  const handleRowClick = (symbol: string, rowData?: InstrumentSummary, e?: React.MouseEvent) => {
    if (e && (e.metaKey || e.ctrlKey || e.button === 1)) {
      window.open(`/stocks/${symbol}`, "_blank", "noopener,noreferrer");
      return;
    }
    if (rowData) {
      saveStockSummary(rowData);
    }
    if (navigatingSymbol) return;
    setNavigatingSymbol(symbol);
    router.push(`/stocks/${symbol}`);
    setTimeout(() => {
      setNavigatingSymbol(null);
    }, 3000);
  };

  const handleCopySingleSymbol = (symbol: string) => {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      navigator.clipboard.writeText(symbol);
      setCopiedSymbol(symbol);
      setTimeout(() => {
        setCopiedSymbol((prev) => (prev === symbol ? null : prev));
      }, 1800);
    }
  };

  useEffect(() => {
    const updateWatchlist = () => {
      try {
        const saved = localStorage.getItem("signalforge_watchlist");
        if (saved) {
          const list = JSON.parse(saved);
          if (Array.isArray(list)) {
            setWatchlist(list);
          }
        } else {
          setWatchlist([]);
        }
      } catch {
        setWatchlist([]);
      }
    };
    updateWatchlist();
    window.addEventListener("storage", updateWatchlist);
    window.addEventListener("focus", updateWatchlist);
    return () => {
      window.removeEventListener("storage", updateWatchlist);
      window.removeEventListener("focus", updateWatchlist);
    };
  }, []);

  const watchlistSet = useMemo(() => new Set(watchlist.map((s) => s.toUpperCase())), [watchlist]);

  const toggleWatchlistSymbol = (sym: string) => {
    try {
      const symUp = sym.toUpperCase();
      const next = watchlistSet.has(symUp)
        ? watchlist.filter((s) => s.toUpperCase() !== symUp)
        : [...watchlist, symUp];
      setWatchlist(next);
      localStorage.setItem("signalforge_watchlist", JSON.stringify(next));
    } catch {}
  };

  // Research Score band filter, driven by clicking a bar in the Market
  // Pulse dashboard's score-distribution chart (UI/UX "Market Pulse"
  // task) - client-side only (filters whatever rows are already loaded,
  // same scoping as the search-results sort in lib/sort.ts).
  const [bandFilter, setBandFilter] = useState<string | null>(null);
  // Sector filter, driven by clicking a cell in the Market Pulse
  // dashboard's sector heatmap - same client-side-only pattern as
  // bandFilter above.
  const [sectorFilter, setSectorFilter] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window !== "undefined") {
      const hash = window.location.hash.replace("#", "").toLowerCase();
      if (hash === "multibagger" || hash === "checklist") {
        setFilterPreset("multibagger");
        setStage2Filter("all");
        setBreakoutFilter("all");
      } else if (hash === "multibagger_stage2" || hash === "multibagger-stage2") {
        setFilterPreset("multibagger_stage2");
        setStage2Filter("all");
        setBreakoutFilter("all");
      } else if (hash === "stage2") {
        setFilterPreset("stage2");
        setStage2Filter("all");
        setBreakoutFilter("all");
      } else if (hash === "breakout" || hash === "52w-breakout" || hash === "52w_breakout") {
        setFilterPreset("breakout");
        setStage2Filter("all");
        setBreakoutFilter("all");
      } else if (hash === "strong_buy" || hash === "strong-buy") {
        setFilterPreset("tv_strong_buy");
        setStage2Filter("all");
        setBreakoutFilter("all");
      } else if (hash === "watchlist" || hash === "starred") {
        setFilterPreset("watchlist");
        setStage2Filter("all");
        setBreakoutFilter("all");
      }
    }
  }, []);

  const counts = useMemo(() => {
    const trimmed = deferredQuery.trim().toLowerCase();
    const list = trimmed
      ? instruments.filter(
          (r) =>
            r.symbol.toLowerCase().includes(trimmed) ||
            r.company_name.toLowerCase().includes(trimmed)
        )
      : instruments;

    let all = 0;
    let mlBullish = 0;
    let mlBearish = 0;
    let stage2 = 0;
    let breakout = 0;
    let multibagger = 0;
    let mbStage2 = 0;
    let tvStrongBuy = 0;
    let watchlistCount = 0;
    for (const r of list) {
      all++;
      if (
        r.ml_forecast_5d_pct !== null &&
        r.ml_forecast_5d_pct >= 1.5 &&
        r.score !== null &&
        r.score >= 60 &&
        (r.momentum_pass === true || (r.distance_from_52w_high_pct !== null && r.distance_from_52w_high_pct >= -15.5))
      ) {
        mlBullish++;
      }
      if (
        r.ml_forecast_5d_pct !== null &&
        r.ml_forecast_5d_pct <= -2.5 &&
        r.score !== null &&
        r.score <= 45 &&
        r.distance_from_52w_high_pct !== null &&
        r.distance_from_52w_high_pct <= -20.0
      ) {
        mlBearish++;
      }
      if (r.momentum_pass === true) stage2++;
      if (r.is_52w_breakout === true || (r.distance_from_52w_high_pct !== null && r.distance_from_52w_high_pct > 0)) breakout++;
      if (r.is_multibagger === true) multibagger++;
      if (r.is_multibagger === true && r.momentum_pass === true) mbStage2++;
      if (r.tv_momentum_flag?.startsWith("STRONG_BUY")) tvStrongBuy++;
      if (watchlistSet.has(r.symbol.toUpperCase())) watchlistCount++;
    }
    return { all, mlBullish, mlBearish, stage2, breakout, multibagger, mbStage2, tvStrongBuy, watchlist: watchlistCount };
  }, [instruments, deferredQuery, watchlistSet]);

  function handleSortClick(key: InstrumentSortKey, event: React.MouseEvent) {
    const isShift = event.shiftKey;
    setSortCriteria((prev) => {
      const existingIndex = prev.findIndex((c) => c.key === key);

      if (!isShift) {
        // Normal click: make this column the single active sort
        if (existingIndex >= 0 && prev.length === 1) {
          return [{ key, order: prev[0].order === "asc" ? "desc" : "asc" }];
        }
        const defaultOrder: SortOrder =
          key === "symbol" || key === "company_name" || key === "sector" ? "asc" : "desc";
        return [{ key, order: defaultOrder }];
      }

      // Shift + click: multi-column sort!
      if (existingIndex >= 0) {
        // Toggle direction of this column
        const updated = [...prev];
        const curOrder = updated[existingIndex].order;
        updated[existingIndex] = {
          key,
          order: curOrder === "asc" ? "desc" : "asc",
        };
        return updated;
      } else {
        // Add as additional sort priority
        const defaultOrder: SortOrder =
          key === "symbol" || key === "company_name" || key === "sector" ? "asc" : "desc";
        return [...prev, { key, order: defaultOrder }];
      }
    });
  }

  function handleAddSortColumn(key: InstrumentSortKey) {
    if (!key) return;
    const defaultOrder: SortOrder =
      key === "symbol" || key === "company_name" || key === "sector" ? "asc" : "desc";
    setSortCriteria((prev) => {
      if (prev.some((c) => c.key === key)) return prev;
      return [...prev, { key, order: defaultOrder }];
    });
  }

  function handleToggleSortDirection(key: InstrumentSortKey) {
    setSortCriteria((prev) =>
      prev.map((c) => (c.key === key ? { ...c, order: c.order === "asc" ? "desc" : "asc" } : c))
    );
  }

  function handleRemoveSortCriterion(key: InstrumentSortKey) {
    setSortCriteria((prev) => {
      const updated = prev.filter((c) => c.key !== key);
      return updated.length > 0 ? updated : [{ key: "day_change_pct", order: "desc" }];
    });
  }

  function handleResetSort() {
    setSortCriteria([{ key: "day_change_pct", order: "desc" }]);
  }

  function handleClearAllFilters() {
    setQuery("");
    setSectorFilter(null);
    setBandFilter(null);
    setFilterPreset("all");
    setMultibaggerFilter("all");
    setStage2Filter("all");
    setVcpFilter("all");
    setTvSignalFilter("all");
    setFundBandFilter(null);
    setMinFundScoreFilter("");
    setMaxFundScoreFilter("");
    setMinScoreFilter("");
    setMaxScoreFilter("");
    setMinAnalystUpside("");
    setAnalystRatingFilter("all");
    setHasAnalystTargetFilter("all");
    setMinRevGrowth("");
    setMinPatGrowth("");
    setMaxDistanceFrom52wHigh("");
    setMinMlForecast("");
    setMinReturn1W("");
    setMinReturn1M("");
    setMinReturn3M("");
    setMinReturn6M("");
    setMinReturn1Y("");
    setFiiActivityFilter("all");
    setMinFiiHolding("");
    setBreakoutFilter("all");
  }

  function handleResetFilters() {
    handleClearAllFilters();
    handleResetSort();
  }

  async function handleRefresh() {
    setRefreshing(true);
    try {
      const fresh = await listInstruments();
      setInstruments(fresh);
    } catch {
      // Silently keep current instruments on failure
    } finally {
      setRefreshing(false);
    }
  }

  const [minScoreFilter, setMinScoreFilter] = useState<number | "">("");
  const [maxScoreFilter, setMaxScoreFilter] = useState<number | "">("");
  const [minFundScoreFilter, setMinFundScoreFilter] = useState<number | "">("");
  const [maxFundScoreFilter, setMaxFundScoreFilter] = useState<number | "">("");
  const [fundBandFilter, setFundBandFilter] = useState<string | null>(null);
  const [multibaggerFilter, setMultibaggerFilter] = useState<"all" | "yes" | "no">("all");
  const [stage2Filter, setStage2Filter] = useState<"all" | "pass" | "fail">("all");
  const [breakoutFilter, setBreakoutFilter] = useState<"all" | "breakout" | "near_breakout" | "close_breakout">("all");
  const [vcpFilter, setVcpFilter] = useState<"all" | "yes" | "no">("all");
  const [tvSignalFilter, setTvSignalFilter] = useState<"all" | "strong_buy_both" | "strong_buy_any" | "strong_sell_both" | "strong_sell_any">("all");
  const [maxDistanceFrom52wHigh, setMaxDistanceFrom52wHigh] = useState<number | "">("");
  const [minMlForecast, setMinMlForecast] = useState<number | "">("");
  const [minAnalystUpside, setMinAnalystUpside] = useState<number | "">("");
  const [analystRatingFilter, setAnalystRatingFilter] = useState<"all" | "strong_buy" | "buy" | "sell" | "strong_sell">("all");
  const [hasAnalystTargetFilter, setHasAnalystTargetFilter] = useState<"all" | "has_target" | "no_target">("all");
  const [minRevGrowth, setMinRevGrowth] = useState<number | "">("");
  const [minPatGrowth, setMinPatGrowth] = useState<number | "">("");
  const [minReturn1W, setMinReturn1W] = useState<number | "">("");
  const [minReturn1M, setMinReturn1M] = useState<number | "">("");
  const [minReturn3M, setMinReturn3M] = useState<number | "">("");
  const [minReturn6M, setMinReturn6M] = useState<number | "">("");
  const [minReturn1Y, setMinReturn1Y] = useState<number | "">("");
  const [fiiActivityFilter, setFiiActivityFilter] = useState<"all" | "buying" | "heavy_buying" | "selling">("all");
  const [minFiiHolding, setMinFiiHolding] = useState<number | "">("");

  const rows = useMemo(() => {
    const trimmed = deferredQuery.trim().toLowerCase();
    let filtered = instruments;

    // Instant in-memory search across symbol and company name
    if (trimmed) {
      filtered = filtered.filter((row) => {
        const sym = row.symbol.toLowerCase();
        const name = row.company_name.toLowerCase();
        return sym.includes(trimmed) || name.includes(trimmed);
      });
    }

    // Filter preset tabs
    if (filterPreset === "ml_bullish") {
      filtered = filtered.filter(
        (row) =>
          row.ml_forecast_5d_pct !== null &&
          row.ml_forecast_5d_pct >= 1.5 &&
          row.score !== null &&
          row.score >= 60 &&
          (row.momentum_pass === true || (row.distance_from_52w_high_pct !== null && row.distance_from_52w_high_pct >= -15.5))
      );
    } else if (filterPreset === "ml_bearish") {
      filtered = filtered.filter(
        (row) =>
          row.ml_forecast_5d_pct !== null &&
          row.ml_forecast_5d_pct <= -2.5 &&
          row.score !== null &&
          row.score <= 45 &&
          row.distance_from_52w_high_pct !== null &&
          row.distance_from_52w_high_pct <= -20.0
      );
    } else if (filterPreset === "stage2") {
      filtered = filtered.filter((row) => row.momentum_pass === true);
    } else if (filterPreset === "breakout") {
      filtered = filtered.filter((row) => row.is_52w_breakout === true || (row.distance_from_52w_high_pct !== null && row.distance_from_52w_high_pct > 0));
    } else if (filterPreset === "multibagger") {
      filtered = filtered.filter((row) => row.is_multibagger === true);
    } else if (filterPreset === "multibagger_stage2") {
      filtered = filtered.filter((row) => row.is_multibagger === true && row.momentum_pass === true);
    } else if (filterPreset === "tv_strong_buy") {
      filtered = filtered.filter((row) => row.tv_momentum_flag?.startsWith("STRONG_BUY"));
    } else if (filterPreset === "watchlist") {
      filtered = filtered.filter((row) => watchlistSet.has(row.symbol.toUpperCase()));
    }

    // Explicit Multibagger, Stage 2, and VCP filters
    if (multibaggerFilter === "yes") {
      filtered = filtered.filter((row) => row.is_multibagger === true);
    } else if (multibaggerFilter === "no") {
      filtered = filtered.filter((row) => !row.is_multibagger);
    }

    if (stage2Filter === "pass") {
      filtered = filtered.filter((row) => row.momentum_pass === true);
    } else if (stage2Filter === "fail") {
      filtered = filtered.filter((row) => row.momentum_pass === false);
    }

    // Breakout Filter (52W High)
    if (breakoutFilter === "breakout") {
      filtered = filtered.filter((row) => row.is_52w_breakout === true || (row.distance_from_52w_high_pct !== null && row.distance_from_52w_high_pct > 0));
    } else if (breakoutFilter === "near_breakout") {
      filtered = filtered.filter((row) => row.is_52w_breakout === true || (row.distance_from_52w_high_pct !== null && row.distance_from_52w_high_pct >= -2.0));
    } else if (breakoutFilter === "close_breakout") {
      filtered = filtered.filter((row) => row.is_52w_breakout === true || (row.distance_from_52w_high_pct !== null && row.distance_from_52w_high_pct >= -5.0));
    }

    if (vcpFilter === "yes") {
      filtered = filtered.filter((row) => row.is_vcp_setup === true);
    } else if (vcpFilter === "no") {
      filtered = filtered.filter((row) => row.is_vcp_setup === false);
    }

    if (tvSignalFilter === "strong_buy_both") {
      filtered = filtered.filter((row) => row.tv_momentum_flag === "STRONG_BUY_BOTH");
    } else if (tvSignalFilter === "strong_buy_any") {
      filtered = filtered.filter((row) => row.tv_momentum_flag?.startsWith("STRONG_BUY"));
    } else if (tvSignalFilter === "strong_sell_both") {
      filtered = filtered.filter((row) => row.tv_momentum_flag === "STRONG_SELL_BOTH");
    } else if (tvSignalFilter === "strong_sell_any") {
      filtered = filtered.filter((row) => row.tv_momentum_flag?.startsWith("STRONG_SELL"));
    }

    // Fundamental Quality & Bands
    if (fundBandFilter) {
      filtered = filtered.filter((row) => row.fundamental_band === fundBandFilter);
    }
    if (minFundScoreFilter !== "") {
      filtered = filtered.filter((row) => row.fundamental_score !== null && row.fundamental_score >= minFundScoreFilter);
    }
    if (maxFundScoreFilter !== "") {
      filtered = filtered.filter((row) => row.fundamental_score !== null && row.fundamental_score <= maxFundScoreFilter);
    }

    // Research Score & Bands
    if (bandFilter) {
      filtered = filtered.filter((row) => row.band === bandFilter);
    }
    if (sectorFilter) {
      filtered = filtered.filter((row) => (row.sector ?? "Unclassified") === sectorFilter);
    }
    if (minScoreFilter !== "") {
      filtered = filtered.filter((row) => row.score !== null && row.score >= minScoreFilter);
    }
    if (maxScoreFilter !== "") {
      filtered = filtered.filter((row) => row.score !== null && row.score <= maxScoreFilter);
    }

    // Growth & Estimates
    if (minAnalystUpside !== "") {
      filtered = filtered.filter((row) => row.analyst_upside_pct !== null && row.analyst_upside_pct >= minAnalystUpside);
    }
    if (hasAnalystTargetFilter === "has_target") {
      filtered = filtered.filter((row) => row.analyst_target_price !== null && row.analyst_target_price > 0);
    } else if (hasAnalystTargetFilter === "no_target") {
      filtered = filtered.filter((row) => row.analyst_target_price === null);
    }
    if (analystRatingFilter === "strong_buy") {
      filtered = filtered.filter((row) => row.analyst_recommendation?.toLowerCase() === "strong_buy");
    } else if (analystRatingFilter === "buy") {
      filtered = filtered.filter((row) => row.analyst_recommendation?.toLowerCase() === "buy");
    } else if (analystRatingFilter === "sell") {
      filtered = filtered.filter((row) => row.analyst_recommendation?.toLowerCase() === "sell");
    } else if (analystRatingFilter === "strong_sell") {
      filtered = filtered.filter((row) => row.analyst_recommendation?.toLowerCase() === "strong_sell");
    }
    if (minRevGrowth !== "") {
      filtered = filtered.filter((row) => row.revenue_growth_yoy !== null && (row.revenue_growth_yoy * 100) >= minRevGrowth);
    }
    if (minPatGrowth !== "") {
      filtered = filtered.filter((row) => row.pat_growth_yoy !== null && (row.pat_growth_yoy * 100) >= minPatGrowth);
    }

    // FII Holdings & Flows
    if (fiiActivityFilter === "buying") {
      filtered = filtered.filter((row) => row.fii_change_qoq_pct !== null && row.fii_change_qoq_pct !== undefined && row.fii_change_qoq_pct > 0);
    } else if (fiiActivityFilter === "heavy_buying") {
      filtered = filtered.filter((row) => row.fii_change_qoq_pct !== null && row.fii_change_qoq_pct !== undefined && row.fii_change_qoq_pct >= 1.0);
    } else if (fiiActivityFilter === "selling") {
      filtered = filtered.filter((row) => row.fii_change_qoq_pct !== null && row.fii_change_qoq_pct !== undefined && row.fii_change_qoq_pct < 0);
    }
    if (minFiiHolding !== "") {
      filtered = filtered.filter((row) => row.fii_current !== null && row.fii_current !== undefined && row.fii_current >= minFiiHolding);
    }

    // Technicals & Momentum
    if (maxDistanceFrom52wHigh !== "") {
      const threshold = -Math.abs(Number(maxDistanceFrom52wHigh));
      filtered = filtered.filter((row) => row.distance_from_52w_high_pct !== null && row.distance_from_52w_high_pct >= threshold);
    }
    if (minMlForecast !== "") {
      filtered = filtered.filter((row) => row.ml_forecast_5d_pct !== null && row.ml_forecast_5d_pct >= minMlForecast);
    }

    // Returns
    if (minReturn1W !== "") {
      filtered = filtered.filter((row) => row.return_1w_pct !== null && row.return_1w_pct >= minReturn1W);
    }
    if (minReturn1M !== "") {
      filtered = filtered.filter((row) => row.return_1m_pct !== null && row.return_1m_pct >= minReturn1M);
    }
    if (minReturn3M !== "") {
      filtered = filtered.filter((row) => row.return_3m_pct !== null && row.return_3m_pct >= minReturn3M);
    }
    if (minReturn6M !== "") {
      filtered = filtered.filter((row) => row.return_6m_pct !== null && row.return_6m_pct >= minReturn6M);
    }
    if (minReturn1Y !== "") {
      filtered = filtered.filter((row) => row.return_1y_pct !== null && row.return_1y_pct >= minReturn1Y);
    }

    // If searching and user is on default symbol sort, prioritize relevance:
    // 1. Exact symbol match
    // 2. Symbol prefix match
    // 3. Company name prefix match
    // 4. Alphabetical by symbol
    const isDefaultSort =
      sortCriteria.length === 1 &&
      ((sortCriteria[0].key === "day_change_pct" && sortCriteria[0].order === "desc") ||
        (sortCriteria[0].key === "symbol" && sortCriteria[0].order === "asc"));

    if (trimmed && isDefaultSort) {
      return [...filtered].sort((a, b) => {
        const aSym = a.symbol.toLowerCase();
        const bSym = b.symbol.toLowerCase();
        if (aSym === trimmed && bSym !== trimmed) return -1;
        if (aSym !== trimmed && bSym === trimmed) return 1;

        const aStarts = aSym.startsWith(trimmed);
        const bStarts = bSym.startsWith(trimmed);
        if (aStarts && !bStarts) return -1;
        if (!aStarts && bStarts) return 1;

        const aNameStarts = a.company_name.toLowerCase().startsWith(trimmed);
        const bNameStarts = b.company_name.toLowerCase().startsWith(trimmed);
        if (aNameStarts && !bNameStarts) return -1;
        if (!aNameStarts && bNameStarts) return 1;

        return aSym.localeCompare(bSym);
      });
    }

    return sortInstrumentsMulti(filtered, sortCriteria);
  }, [
    deferredQuery,
    instruments,
    sortCriteria,
    filterPreset,
    multibaggerFilter,
    stage2Filter,
    vcpFilter,
    tvSignalFilter,
    fundBandFilter,
    minFundScoreFilter,
    maxFundScoreFilter,
    bandFilter,
    sectorFilter,
    minScoreFilter,
    maxScoreFilter,
    minAnalystUpside,
    analystRatingFilter,
    hasAnalystTargetFilter,
    minRevGrowth,
    minPatGrowth,
    maxDistanceFrom52wHigh,
    minMlForecast,
    minReturn1W,
    minReturn1M,
    minReturn3M,
    minReturn6M,
    minReturn1Y,
    fiiActivityFilter,
    minFiiHolding,
    breakoutFilter,
    watchlistSet,
  ]);

  useEffect(() => {
    setCurrentPage(1);
  }, [
    query,
    bandFilter,
    sectorFilter,
    filterPreset,
    multibaggerFilter,
    stage2Filter,
    breakoutFilter,
    vcpFilter,
    tvSignalFilter,
    fundBandFilter,
    minFundScoreFilter,
    maxFundScoreFilter,
    sortCriteria,
    minScoreFilter,
    maxScoreFilter,
    minAnalystUpside,
    analystRatingFilter,
    hasAnalystTargetFilter,
    minRevGrowth,
    minPatGrowth,
    maxDistanceFrom52wHigh,
    minMlForecast,
    minReturn1W,
    minReturn1M,
    minReturn3M,
    minReturn6M,
    minReturn1Y,
    fiiActivityFilter,
    minFiiHolding,
    pageSize,
  ]);

  const totalItems = rows.length;
  const totalPages = pageSize > 0 ? Math.max(1, Math.ceil(totalItems / pageSize)) : 1;
  const validCurrentPage = Math.min(Math.max(1, currentPage), totalPages);
  const startIndex = pageSize > 0 ? (validCurrentPage - 1) * pageSize : 0;
  const endIndex = pageSize > 0 ? Math.min(startIndex + pageSize, totalItems) : totalItems;

  const paginatedRows = useMemo(() => {
    if (pageSize <= 0) return rows;
    return rows.slice(startIndex, endIndex);
  }, [rows, startIndex, endIndex, pageSize]);

  // Idle background pre-warming for top visible stocks so clicks are instantaneous
  useEffect(() => {
    if (typeof window === "undefined" || !paginatedRows.length) return;
    const timer = setTimeout(() => {
      const topRows = paginatedRows.slice(0, 4);
      for (const r of topRows) {
        saveStockSummary(r);
        prefetchStock(r.symbol);
      }
    }, 800);
    return () => clearTimeout(timer);
  }, [paginatedRows]);

  const handlePageChange = (newPage: number) => {
    const target = Math.max(1, Math.min(newPage, totalPages));
    setCurrentPage(target);
    if (tableScrollRef.current) {
      tableScrollRef.current.scrollTo({ top: 0, behavior: "smooth" });
    }
  };

  const sectorsList = useMemo(() => {
    const set = new Set<string>();
    initialInstruments.forEach((i) => set.add(i.sector ?? "Unclassified"));
    return Array.from(set).sort();
  }, [initialInstruments]);

  const availableSortColumns = useMemo(() => {
    const existingKeys = new Set(sortCriteria.map((c) => c.key));
    return COLUMNS.filter((c) => !existingKeys.has(c.key));
  }, [sortCriteria]);

  const hasActiveFilters = Boolean(
    query ||
    sectorFilter ||
    bandFilter ||
    filterPreset !== "all" ||
    breakoutFilter !== "all" ||
    multibaggerFilter !== "all" ||
    stage2Filter !== "all" ||
    vcpFilter !== "all" ||
    tvSignalFilter !== "all" ||
    fundBandFilter ||
    minFundScoreFilter !== "" ||
    maxFundScoreFilter !== "" ||
    minScoreFilter !== "" ||
    maxScoreFilter !== "" ||
    minAnalystUpside !== "" ||
    analystRatingFilter !== "all" ||
    hasAnalystTargetFilter !== "all" ||
    minRevGrowth !== "" ||
    minPatGrowth !== "" ||
    maxDistanceFrom52wHigh !== "" ||
    minMlForecast !== "" ||
    minReturn1W !== "" ||
    minReturn1M !== "" ||
    minReturn3M !== "" ||
    minReturn6M !== "" ||
    minReturn1Y !== "" ||
    fiiActivityFilter !== "all" ||
    minFiiHolding !== ""
  );

  const activeFilters = useMemo(() => {
    const list: Array<{ id: string; label: string; onRemove: () => void }> = [];
    if (query.trim()) {
      list.push({ id: "query", label: `Search: "${query.trim()}"`, onRemove: () => setQuery("") });
    }
    if (sectorFilter) {
      list.push({ id: "sector", label: `Sector: ${sectorFilter}`, onRemove: () => setSectorFilter(null) });
    }
    if (bandFilter) {
      list.push({ id: "band", label: `Score Band: ${bandFilter}`, onRemove: () => setBandFilter(null) });
    }
    if (fundBandFilter) {
      list.push({ id: "fundBand", label: `Fund Band: ${fundBandFilter}`, onRemove: () => setFundBandFilter(null) });
    }
    if (filterPreset === "ml_bullish") {
      list.push({ id: "mlBullishPreset", label: "🟢 ML Bullish Leaders Tab", onRemove: () => setFilterPreset("all") });
    } else if (filterPreset === "ml_bearish") {
      list.push({ id: "mlBearishPreset", label: "🔴 ML Breakdown / Exits Tab", onRemove: () => setFilterPreset("all") });
    } else if (filterPreset === "stage2") {
      list.push({ id: "stage2Preset", label: "⚡ Stage 2 Tab", onRemove: () => setFilterPreset("all") });
    } else if (filterPreset === "breakout") {
      list.push({ id: "breakoutPreset", label: "💥 52W Breakout Tab", onRemove: () => setFilterPreset("all") });
    } else if (filterPreset === "multibagger") {
      list.push({ id: "mbPreset", label: "🌟 Multibaggers Tab", onRemove: () => setFilterPreset("all") });
    } else if (filterPreset === "multibagger_stage2") {
      list.push({ id: "mbStage2Preset", label: "🚀 Multibagger + Stage 2 Tab", onRemove: () => setFilterPreset("all") });
    } else if (filterPreset === "tv_strong_buy") {
      list.push({ id: "tvStrongBuyPreset", label: "🔥 Strong Buy Tab", onRemove: () => setFilterPreset("all") });
    } else if (filterPreset === "watchlist") {
      list.push({ id: "watchlistPreset", label: "⭐ Watchlist Tab", onRemove: () => setFilterPreset("all") });
    }
    if (breakoutFilter === "breakout") {
      list.push({ id: "breakoutOnly", label: "💥 52W Breakout (Strict)", onRemove: () => setBreakoutFilter("all") });
    } else if (breakoutFilter === "near_breakout") {
      list.push({ id: "nearBreakout", label: "⚡ Near 52W Breakout (≤ 2%)", onRemove: () => setBreakoutFilter("all") });
    } else if (breakoutFilter === "close_breakout") {
      list.push({ id: "closeBreakout", label: "🎯 Close to 52W High (≤ 5%)", onRemove: () => setBreakoutFilter("all") });
    }
    if (multibaggerFilter === "yes") {
      list.push({ id: "multibagger", label: "🌟 6/6 Multibaggers Only", onRemove: () => setMultibaggerFilter("all") });
    } else if (multibaggerFilter === "no") {
      list.push({ id: "nonMultibagger", label: "Non-Multibaggers", onRemove: () => setMultibaggerFilter("all") });
    }
    if (stage2Filter === "pass") {
      list.push({ id: "stage2Pass", label: "✓ Stage 2 Pass", onRemove: () => setStage2Filter("all") });
    } else if (stage2Filter === "fail") {
      list.push({ id: "stage2Fail", label: "✗ Stage 2 Fail", onRemove: () => setStage2Filter("all") });
    }
    if (vcpFilter === "yes") {
      list.push({ id: "vcpYes", label: "✓ VCP Setup", onRemove: () => setVcpFilter("all") });
    }
    if (tvSignalFilter === "strong_buy_both") {
      list.push({ id: "tvSigBoth", label: "🔥 2x Strong Buy (1D & 1W)", onRemove: () => setTvSignalFilter("all") });
    } else if (tvSignalFilter === "strong_buy_any") {
      list.push({ id: "tvSigAny", label: "🟢 Strong Buy (Any TF)", onRemove: () => setTvSignalFilter("all") });
    } else if (tvSignalFilter === "strong_sell_both") {
      list.push({ id: "tvSigSellBoth", label: "🚨 2x Strong Sell (1D & 1W)", onRemove: () => setTvSignalFilter("all") });
    } else if (tvSignalFilter === "strong_sell_any") {
      list.push({ id: "tvSigSellAny", label: "🔴 Strong Sell (Any TF)", onRemove: () => setTvSignalFilter("all") });
    }
    if (minFundScoreFilter !== "") {
      list.push({ id: "minFundScore", label: `Fund Score ≥ ${minFundScoreFilter}`, onRemove: () => setMinFundScoreFilter("") });
    }
    if (maxFundScoreFilter !== "") {
      list.push({ id: "maxFundScore", label: `Fund Score ≤ ${maxFundScoreFilter}`, onRemove: () => setMaxFundScoreFilter("") });
    }
    if (minScoreFilter !== "") {
      list.push({ id: "minScore", label: `Score ≥ ${minScoreFilter}`, onRemove: () => setMinScoreFilter("") });
    }
    if (maxScoreFilter !== "") {
      list.push({ id: "maxScore", label: `Score ≤ ${maxScoreFilter}`, onRemove: () => setMaxScoreFilter("") });
    }
    if (minAnalystUpside !== "") {
      list.push({ id: "upside", label: `Target Upside ≥ ${minAnalystUpside}%`, onRemove: () => setMinAnalystUpside("") });
    }
    if (hasAnalystTargetFilter === "has_target") {
      list.push({ id: "hasTarget", label: "🎯 Has Analyst Target", onRemove: () => setHasAnalystTargetFilter("all") });
    } else if (hasAnalystTargetFilter === "no_target") {
      list.push({ id: "noTarget", label: "No Analyst Target", onRemove: () => setHasAnalystTargetFilter("all") });
    }
    if (analystRatingFilter === "strong_buy") {
      list.push({ id: "analystStrongBuy", label: "🎯 Rating: Strong Buy", onRemove: () => setAnalystRatingFilter("all") });
    } else if (analystRatingFilter === "buy") {
      list.push({ id: "analystBuy", label: "🎯 Rating: Buy", onRemove: () => setAnalystRatingFilter("all") });
    } else if (analystRatingFilter === "sell") {
      list.push({ id: "analystSell", label: "🎯 Rating: Sell", onRemove: () => setAnalystRatingFilter("all") });
    } else if (analystRatingFilter === "strong_sell") {
      list.push({ id: "analystStrongSell", label: "🎯 Rating: Strong Sell", onRemove: () => setAnalystRatingFilter("all") });
    }
    if (minRevGrowth !== "") {
      list.push({ id: "revGrowth", label: `Rev YoY ≥ ${minRevGrowth}%`, onRemove: () => setMinRevGrowth("") });
    }
    if (minPatGrowth !== "") {
      list.push({ id: "patGrowth", label: `PAT YoY ≥ ${minPatGrowth}%`, onRemove: () => setMinPatGrowth("") });
    }
    if (fiiActivityFilter === "buying") {
      list.push({ id: "fiiBuying", label: "🟢 FII Buying (QoQ > 0)", onRemove: () => setFiiActivityFilter("all") });
    } else if (fiiActivityFilter === "heavy_buying") {
      list.push({ id: "fiiHeavyBuying", label: "🚀 FII Inflows (QoQ ≥ 1%)", onRemove: () => setFiiActivityFilter("all") });
    } else if (fiiActivityFilter === "selling") {
      list.push({ id: "fiiSelling", label: "🔴 FII Selling (QoQ < 0)", onRemove: () => setFiiActivityFilter("all") });
    }
    if (minFiiHolding !== "") {
      list.push({ id: "minFiiHolding", label: `FII Holding ≥ ${minFiiHolding}%`, onRemove: () => setMinFiiHolding("") });
    }
    if (maxDistanceFrom52wHigh !== "") {
      list.push({ id: "dist52w", label: `Within ${Math.abs(Number(maxDistanceFrom52wHigh))}% of 52W High`, onRemove: () => setMaxDistanceFrom52wHigh("") });
    }
    if (minMlForecast !== "") {
      list.push({ id: "mlForecast", label: `5D ML ≥ ${minMlForecast}%`, onRemove: () => setMinMlForecast("") });
    }
    if (minReturn1W !== "") {
      list.push({ id: "return1w", label: `1W Return ≥ ${minReturn1W}%`, onRemove: () => setMinReturn1W("") });
    }
    if (minReturn1M !== "") {
      list.push({ id: "return1m", label: `1M Return ≥ ${minReturn1M}%`, onRemove: () => setMinReturn1M("") });
    }
    if (minReturn3M !== "") {
      list.push({ id: "return3m", label: `3M Return ≥ ${minReturn3M}%`, onRemove: () => setMinReturn3M("") });
    }
    if (minReturn6M !== "") {
      list.push({ id: "return6m", label: `6M Return ≥ ${minReturn6M}%`, onRemove: () => setMinReturn6M("") });
    }
    if (minReturn1Y !== "") {
      list.push({ id: "return1y", label: `1Y Return ≥ ${minReturn1Y}%`, onRemove: () => setMinReturn1Y("") });
    }
    return list;
  }, [
    query,
    sectorFilter,
    bandFilter,
    filterPreset,
    multibaggerFilter,
    stage2Filter,
    breakoutFilter,
    vcpFilter,
    tvSignalFilter,
    fundBandFilter,
    minFundScoreFilter,
    maxFundScoreFilter,
    minScoreFilter,
    maxScoreFilter,
    minAnalystUpside,
    analystRatingFilter,
    hasAnalystTargetFilter,
    minRevGrowth,
    minPatGrowth,
    fiiActivityFilter,
    minFiiHolding,
    maxDistanceFrom52wHigh,
    minMlForecast,
    minReturn1W,
    minReturn1M,
    minReturn3M,
    minReturn6M,
    minReturn1Y,
  ]);

  const hasCustomSort =
    sortCriteria.length > 1 ||
    (sortCriteria.length === 1 && (sortCriteria[0].key !== "day_change_pct" || sortCriteria[0].order !== "desc"));

  const handleSelectBand = (band: string | null) => {
    setBandFilter(band);
    if (band) {
      setHomeTab("screener");
    }
  };

  const handleSelectSector = (sector: string | null) => {
    setSectorFilter(sector);
    if (sector) {
      setHomeTab("screener");
    }
  };

  return (
    <>
      <div className="home-tabs-container">
        <div className="home-tabs-bar" role="tablist" aria-label="Home page views">
          <button
            type="button"
            role="tab"
            aria-selected={homeTab === "pulse"}
            className={`home-tab-pill ${homeTab === "pulse" ? "active" : ""}`}
            onClick={() => setHomeTab("pulse")}
          >
            <span className="home-tab-icon">📊</span>
            <span className="home-tab-label">Market Pulse</span>
          </button>

          <button
            type="button"
            role="tab"
            aria-selected={homeTab === "ml_alpha"}
            className={`home-tab-pill ${homeTab === "ml_alpha" ? "active" : ""}`}
            onClick={() => setHomeTab("ml_alpha")}
          >
            <span className="home-tab-icon">🤖</span>
            <span className="home-tab-label">5D ML Forecast Accuracy &amp; Directional Alpha</span>
          </button>

          <button
            type="button"
            role="tab"
            aria-selected={homeTab === "screener"}
            className={`home-tab-pill ${homeTab === "screener" ? "active" : ""}`}
            onClick={() => setHomeTab("screener")}
          >
            <span className="home-tab-icon">⚡</span>
            <span className="home-tab-label">Quant Screener</span>
            <span className="home-tab-count num">{counts.all}</span>
          </button>
        </div>
      </div>

      <div style={{ display: homeTab === "pulse" ? "block" : "none" }}>
        <MarketPulse
          instruments={initialInstruments}
          selectedBand={bandFilter}
          onSelectBand={handleSelectBand}
          selectedSector={sectorFilter}
          onSelectSector={handleSelectSector}
        />
      </div>

      <div style={{ display: homeTab === "ml_alpha" ? "block" : "none" }}>
        <div className="ml-alpha-tab-pane">
          <MlPerformanceWidget />
        </div>
      </div>

      <div style={{ display: homeTab === "screener" ? "block" : "none" }}>
        <div className="panel search-box">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem", flexWrap: "wrap", gap: "0.5rem" }}>
            <h2 style={{ margin: 0 }}>Quant Screener</h2>
            <span style={{ fontSize: "0.8rem", color: "var(--fg-muted)" }}>
              Filter across {initialInstruments.length.toLocaleString()} stocks by Fundamentals, Multibaggers, Stage 2, Growth &amp; Technicals
            </span>
          </div>

        {/* Filter Inputs Grid */}
        <div style={{ display: "flex", gap: "0.85rem", flexWrap: "wrap", marginBottom: "1rem" }}>
          {/* Categorization & Flags */}
          <div style={{ flex: "1 1 240px", position: "relative" }}>
            <label style={{ display: "block", fontSize: "0.82rem", marginBottom: "0.25rem", color: "var(--fg-muted)", fontWeight: 600 }}>
              Search (Symbol/Name)
            </label>
            <div style={{ position: "relative", display: "flex", alignItems: "center" }}>
              <input
                type="text"
                placeholder="e.g. RELIANCE, TCS"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                style={{ width: "100%", paddingRight: query ? "2rem" : "0.5rem" }}
              />
              {query && (
                <button
                  type="button"
                  onClick={() => setQuery("")}
                  title="Clear search"
                  style={{
                    position: "absolute",
                    right: "6px",
                    background: "none",
                    border: "none",
                    color: "var(--fg-muted)",
                    cursor: "pointer",
                    fontSize: "0.85rem",
                    padding: "2px 6px",
                  }}
                >
                  ✕
                </button>
              )}
            </div>
          </div>

          <div style={{ flex: "1 1 180px" }}>
            <label style={{ display: "block", fontSize: "0.82rem", marginBottom: "0.25rem", color: "var(--fg-muted)", fontWeight: 600 }}>
              Sector
            </label>
            <select
              value={sectorFilter ?? ""}
              onChange={(e) => setSectorFilter(e.target.value === "" ? null : e.target.value)}
              style={{ width: "100%", padding: "8px", borderRadius: "4px", border: "1px solid var(--border)", background: "var(--bg)" }}
            >
              <option value="">All Sectors</option>
              {sectorsList.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>

          <div style={{ flex: "1 1 180px" }}>
            <label style={{ display: "block", fontSize: "0.82rem", marginBottom: "0.25rem", color: "var(--fg-muted)", fontWeight: 600 }}>
              Multibagger Status
            </label>
            <select
              value={multibaggerFilter}
              onChange={(e) => setMultibaggerFilter(e.target.value as any)}
              style={{ width: "100%", padding: "8px", borderRadius: "4px", border: "1px solid var(--border)", background: "var(--bg)" }}
            >
              <option value="all">All Stocks</option>
              <option value="yes">🌟 6/6 Multibaggers Only ({counts.multibagger})</option>
              <option value="no">Non-Multibaggers</option>
            </select>
          </div>

          <div style={{ flex: "1 1 160px" }}>
            <label style={{ display: "block", fontSize: "0.82rem", marginBottom: "0.25rem", color: "var(--fg-muted)", fontWeight: 600 }}>
              Stage 2 Momentum
            </label>
            <select
              value={stage2Filter}
              onChange={(e) => setStage2Filter(e.target.value as any)}
              style={{ width: "100%", padding: "8px", borderRadius: "4px", border: "1px solid var(--border)", background: "var(--bg)" }}
            >
              <option value="all">All Stage 2 Statuses</option>
              <option value="pass">✓ Stage 2 Pass Only ({counts.stage2})</option>
              <option value="fail">✗ Stage 2 Fail Only</option>
            </select>
          </div>

          <div style={{ flex: "1 1 180px" }}>
            <label style={{ display: "block", fontSize: "0.82rem", marginBottom: "0.25rem", color: "var(--fg-muted)", fontWeight: 600 }}>
              Breakout Filter (52W High)
            </label>
            <select
              value={breakoutFilter}
              onChange={(e) => setBreakoutFilter(e.target.value as any)}
              style={{ width: "100%", padding: "8px", borderRadius: "4px", border: "1px solid var(--border)", background: "var(--bg)" }}
            >
              <option value="all">All Stocks</option>
              <option value="breakout">💥 52W High Breakout Only ({counts.breakout})</option>
              <option value="near_breakout">⚡ Near Breakout (Within 2%)</option>
              <option value="close_breakout">🎯 Close to Breakout (Within 5%)</option>
            </select>
          </div>

          <div style={{ flex: "1 1 130px" }}>
            <label style={{ display: "block", fontSize: "0.82rem", marginBottom: "0.25rem", color: "var(--fg-muted)", fontWeight: 600 }}>
              VCP Setup
            </label>
            <select
              value={vcpFilter}
              onChange={(e) => setVcpFilter(e.target.value as any)}
              style={{ width: "100%", padding: "8px", borderRadius: "4px", border: "1px solid var(--border)", background: "var(--bg)" }}
            >
              <option value="all">All</option>
              <option value="yes">✓ VCP Setup</option>
              <option value="no">No Setup</option>
            </select>
          </div>

          <div style={{ flex: "1 1 175px" }}>
            <label style={{ display: "block", fontSize: "0.82rem", marginBottom: "0.25rem", color: "var(--fg-muted)", fontWeight: 600 }}>
              TV Signal (1D/1W)
            </label>
            <select
              value={tvSignalFilter}
              onChange={(e) => setTvSignalFilter(e.target.value as any)}
              style={{ width: "100%", padding: "8px", borderRadius: "4px", border: "1px solid var(--border)", background: "var(--bg)" }}
            >
              <option value="all">All TV Signals</option>
              <option value="strong_buy_both">🔥 2x Strong Buy (1D &amp; 1W)</option>
              <option value="strong_buy_any">🟢 Strong Buy (1D or 1W)</option>
              <option value="strong_sell_both">🚨 2x Strong Sell (1D &amp; 1W)</option>
              <option value="strong_sell_any">🔴 Strong Sell (1D or 1W)</option>
            </select>
          </div>

          {/* Fundamental Quality & Scores */}
          <div style={{ flex: "0 1 125px" }}>
            <label style={{ display: "block", fontSize: "0.82rem", marginBottom: "0.25rem", color: "var(--fg-muted)", fontWeight: 600 }}>
              Min Fund Score
            </label>
            <input
              type="number"
              placeholder="e.g. 70"
              min="0"
              max="100"
              value={minFundScoreFilter}
              onChange={(e) => setMinFundScoreFilter(e.target.value === "" ? "" : Number(e.target.value))}
              style={{ width: "100%" }}
            />
          </div>

          <div style={{ flex: "0 1 125px" }}>
            <label style={{ display: "block", fontSize: "0.82rem", marginBottom: "0.25rem", color: "var(--fg-muted)", fontWeight: 600 }}>
              Max Fund Score
            </label>
            <input
              type="number"
              placeholder="100"
              min="0"
              max="100"
              value={maxFundScoreFilter}
              onChange={(e) => setMaxFundScoreFilter(e.target.value === "" ? "" : Number(e.target.value))}
              style={{ width: "100%" }}
            />
          </div>

          <div style={{ flex: "1 1 160px" }}>
            <label style={{ display: "block", fontSize: "0.82rem", marginBottom: "0.25rem", color: "var(--fg-muted)", fontWeight: 600 }}>
              Fund Quality Band
            </label>
            <select
              value={fundBandFilter ?? ""}
              onChange={(e) => setFundBandFilter(e.target.value === "" ? null : e.target.value)}
              style={{ width: "100%", padding: "8px", borderRadius: "4px", border: "1px solid var(--border)", background: "var(--bg)" }}
            >
              <option value="">All Quality Bands</option>
              <option value="Very Strong">🌟 Very Strong (80+)</option>
              <option value="Strong">🟢 Strong (70–79)</option>
              <option value="Moderate">🟡 Moderate (55–69)</option>
              <option value="Neutral">⚪ Neutral (40–54)</option>
              <option value="Weak">🔴 Weak (&lt;40)</option>
            </select>
          </div>

          <div style={{ flex: "0 1 110px" }}>
            <label style={{ display: "block", fontSize: "0.82rem", marginBottom: "0.25rem", color: "var(--fg-muted)", fontWeight: 600 }}>
              Min Score
            </label>
            <input
              type="number"
              placeholder="0"
              min="0"
              max="100"
              value={minScoreFilter}
              onChange={(e) => setMinScoreFilter(e.target.value === "" ? "" : Number(e.target.value))}
              style={{ width: "100%" }}
            />
          </div>

          <div style={{ flex: "0 1 110px" }}>
            <label style={{ display: "block", fontSize: "0.82rem", marginBottom: "0.25rem", color: "var(--fg-muted)", fontWeight: 600 }}>
              Max Score
            </label>
            <input
              type="number"
              placeholder="100"
              min="0"
              max="100"
              value={maxScoreFilter}
              onChange={(e) => setMaxScoreFilter(e.target.value === "" ? "" : Number(e.target.value))}
              style={{ width: "100%" }}
            />
          </div>

          {/* Growth, Valuation & Technicals */}
          <div style={{ flex: "0 1 130px" }}>
            <label style={{ display: "block", fontSize: "0.82rem", marginBottom: "0.25rem", color: "var(--fg-muted)", fontWeight: 600 }}>
              Min Rev YoY %
            </label>
            <input
              type="number"
              placeholder="e.g. 10"
              value={minRevGrowth}
              onChange={(e) => setMinRevGrowth(e.target.value === "" ? "" : Number(e.target.value))}
              style={{ width: "100%" }}
            />
          </div>

          <div style={{ flex: "0 1 130px" }}>
            <label style={{ display: "block", fontSize: "0.82rem", marginBottom: "0.25rem", color: "var(--fg-muted)", fontWeight: 600 }}>
              Min PAT YoY %
            </label>
            <input
              type="number"
              placeholder="e.g. 15"
              value={minPatGrowth}
              onChange={(e) => setMinPatGrowth(e.target.value === "" ? "" : Number(e.target.value))}
              style={{ width: "100%" }}
            />
          </div>

          <div style={{ flex: "0 1 125px" }}>
            <label style={{ display: "block", fontSize: "0.82rem", marginBottom: "0.25rem", color: "var(--fg-muted)", fontWeight: 600 }}>
              Min Target Upside %
            </label>
            <input
              type="number"
              placeholder="e.g. 15"
              value={minAnalystUpside}
              onChange={(e) => setMinAnalystUpside(e.target.value === "" ? "" : Number(e.target.value))}
              style={{ width: "100%" }}
            />
          </div>

          <div style={{ flex: "1 1 160px" }}>
            <label style={{ display: "block", fontSize: "0.82rem", marginBottom: "0.25rem", color: "var(--fg-muted)", fontWeight: 600 }}>
              Target Coverage
            </label>
            <select
              value={hasAnalystTargetFilter}
              onChange={(e) => setHasAnalystTargetFilter(e.target.value as any)}
              style={{ width: "100%", padding: "8px", borderRadius: "4px", border: "1px solid var(--border)", background: "var(--bg)" }}
            >
              <option value="all">All Coverage Status</option>
              <option value="has_target">🎯 Has Target Price</option>
              <option value="no_target">No Analyst Coverage</option>
            </select>
          </div>

          <div style={{ flex: "1 1 160px" }}>
            <label style={{ display: "block", fontSize: "0.82rem", marginBottom: "0.25rem", color: "var(--fg-muted)", fontWeight: 600 }}>
              Analyst Consensus
            </label>
            <select
              value={analystRatingFilter}
              onChange={(e) => setAnalystRatingFilter(e.target.value as any)}
              style={{ width: "100%", padding: "8px", borderRadius: "4px", border: "1px solid var(--border)", background: "var(--bg)" }}
            >
              <option value="all">All Ratings</option>
              <option value="strong_buy">🟢 Strong Buy</option>
              <option value="buy">▲ Buy</option>
              <option value="sell">▼ Sell</option>
              <option value="strong_sell">🔴 Strong Sell</option>
            </select>
          </div>

          {/* Institutional / FII Activity */}
          <div style={{ flex: "1 1 170px" }}>
            <label style={{ display: "block", fontSize: "0.82rem", marginBottom: "0.25rem", color: "var(--fg-muted)", fontWeight: 600 }}>
              FII Activity (QoQ)
            </label>
            <select
              value={fiiActivityFilter}
              onChange={(e) => setFiiActivityFilter(e.target.value as any)}
              style={{ width: "100%", padding: "8px", borderRadius: "4px", border: "1px solid var(--border)", background: "var(--bg)" }}
            >
              <option value="all">All FII Activity</option>
              <option value="buying">🟢 FII Buying (QoQ &gt; 0)</option>
              <option value="heavy_buying">🚀 Heavy Inflows (QoQ ≥ +1%)</option>
              <option value="selling">🔴 FII Selling (QoQ &lt; 0)</option>
            </select>
          </div>

          <div style={{ flex: "0 1 125px" }}>
            <label style={{ display: "block", fontSize: "0.82rem", marginBottom: "0.25rem", color: "var(--fg-muted)", fontWeight: 600 }}>
              Min FII Stake %
            </label>
            <input
              type="number"
              placeholder="e.g. 10"
              min="0"
              max="100"
              value={minFiiHolding}
              onChange={(e) => setMinFiiHolding(e.target.value === "" ? "" : Number(e.target.value))}
              style={{ width: "100%" }}
            />
          </div>

          <div style={{ flex: "0 1 155px" }}>
            <label
              style={{ display: "block", fontSize: "0.82rem", marginBottom: "0.25rem", color: "var(--fg-muted)", fontWeight: 600 }}
              title="Within X% of 52-week high (e.g. 15 means at most 15% below high)"
            >
              Within % of 52W High
            </label>
            <input
              type="number"
              placeholder="e.g. 15"
              min="0"
              value={maxDistanceFrom52wHigh !== "" ? Math.abs(Number(maxDistanceFrom52wHigh)) : ""}
              onChange={(e) => setMaxDistanceFrom52wHigh(e.target.value === "" ? "" : Number(e.target.value))}
              style={{ width: "100%" }}
            />
          </div>

          <div style={{ flex: "0 1 125px" }}>
            <label style={{ display: "block", fontSize: "0.82rem", marginBottom: "0.25rem", color: "var(--fg-muted)", fontWeight: 600 }}>
              Min 5D ML %
            </label>
            <input
              type="number"
              placeholder="e.g. 2"
              value={minMlForecast}
              onChange={(e) => setMinMlForecast(e.target.value === "" ? "" : Number(e.target.value))}
              style={{ width: "100%" }}
            />
          </div>

          <div style={{ flex: "0 1 110px" }}>
            <label style={{ display: "block", fontSize: "0.82rem", marginBottom: "0.25rem", color: "var(--fg-muted)", fontWeight: 600 }}>
              Min 1W %
            </label>
            <input
              type="number"
              placeholder="e.g. 2"
              value={minReturn1W}
              onChange={(e) => setMinReturn1W(e.target.value === "" ? "" : Number(e.target.value))}
              style={{ width: "100%" }}
            />
          </div>

          <div style={{ flex: "0 1 110px" }}>
            <label style={{ display: "block", fontSize: "0.82rem", marginBottom: "0.25rem", color: "var(--fg-muted)", fontWeight: 600 }}>
              Min 1M %
            </label>
            <input
              type="number"
              placeholder="e.g. 5"
              value={minReturn1M}
              onChange={(e) => setMinReturn1M(e.target.value === "" ? "" : Number(e.target.value))}
              style={{ width: "100%" }}
            />
          </div>

          <div style={{ flex: "0 1 110px" }}>
            <label style={{ display: "block", fontSize: "0.82rem", marginBottom: "0.25rem", color: "var(--fg-muted)", fontWeight: 600 }}>
              Min 3M %
            </label>
            <input
              type="number"
              placeholder="e.g. 10"
              value={minReturn3M}
              onChange={(e) => setMinReturn3M(e.target.value === "" ? "" : Number(e.target.value))}
              style={{ width: "100%" }}
            />
          </div>

          <div style={{ flex: "0 1 110px" }}>
            <label style={{ display: "block", fontSize: "0.82rem", marginBottom: "0.25rem", color: "var(--fg-muted)", fontWeight: 600 }}>
              Min 6M %
            </label>
            <input
              type="number"
              placeholder="e.g. 20"
              value={minReturn6M}
              onChange={(e) => setMinReturn6M(e.target.value === "" ? "" : Number(e.target.value))}
              style={{ width: "100%" }}
            />
          </div>

          <div style={{ flex: "0 1 110px" }}>
            <label style={{ display: "block", fontSize: "0.82rem", marginBottom: "0.25rem", color: "var(--fg-muted)", fontWeight: 600 }}>
              Min 1Y %
            </label>
            <input
              type="number"
              placeholder="e.g. 50"
              value={minReturn1Y}
              onChange={(e) => setMinReturn1Y(e.target.value === "" ? "" : Number(e.target.value))}
              style={{ width: "100%" }}
            />
          </div>
        </div>

        {minScoreFilter !== "" && maxScoreFilter !== "" && minScoreFilter > maxScoreFilter && (
          <div className="notice error" style={{ marginBottom: "0.5rem", padding: "8px" }}>
            Min Score cannot be greater than Max Score.
          </div>
        )}
        {minFundScoreFilter !== "" && maxFundScoreFilter !== "" && minFundScoreFilter > maxFundScoreFilter && (
          <div className="notice error" style={{ marginBottom: "0.5rem", padding: "8px" }}>
            Min Fund Score cannot be greater than Max Fund Score.
          </div>
        )}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <p className="footnote" style={{ margin: 0 }}>
            {totalItems} instruments matching your filters (from {initialInstruments.length} total across {sectorsList.length} sectors).
            {pageSize > 0 && totalItems > pageSize && (
              <> Showing <strong>{startIndex + 1}–{endIndex}</strong> on Page {validCurrentPage} of {totalPages}.</>
            )}{" "}
            Click any row to open its research page.
          </p>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <button 
              type="button" 
              onClick={handleResetFilters} 
              style={{ padding: "4px 12px", cursor: "pointer", background: "var(--bg-muted)", border: "1px solid var(--border)", borderRadius: "4px" }}
            >
              Reset Filters
            </button>
            <button 
              type="button" 
              onClick={handleRefresh}
              disabled={refreshing}
              style={{ padding: "4px 12px", cursor: "pointer", background: "var(--bg-muted)", border: "1px solid var(--border)", borderRadius: "4px", opacity: refreshing ? 0.6 : 1 }}
            >
              {refreshing ? "Refreshing…" : "↻ Refresh"}
            </button>
          </div>
        </div>
      </div>

      <div className="panel market-table-panel">
        <div className="market-table-head">
          <h2 style={{ margin: 0 }}>
            {query.trim() ? `Search results for "${query.trim()}" (${totalItems})` : `Quant Screener (${totalItems})`}
          </h2>
          <div className="filter-tabs">
            <button
              type="button"
              className={filterPreset === "all" && stage2Filter === "all" && breakoutFilter === "all" ? "active" : ""}
              onClick={() => {
                setFilterPreset("all");
                setStage2Filter("all");
                setBreakoutFilter("all");
              }}
            >
              All ({counts.all})
            </button>
            <button
              type="button"
              className={filterPreset === "ml_bullish" ? "active ml-bullish-tab" : ""}
              onClick={() => {
                setFilterPreset("ml_bullish");
                setStage2Filter("all");
                setBreakoutFilter("all");
              }}
              title="Bullish ML Confluence: Predicted Return ≥ +1.5%, Research Score ≥ 60, and Stage 2 / within 15% of 52W High"
            >
              🟢 ML Bullish ({counts.mlBullish})
            </button>
            <button
              type="button"
              className={filterPreset === "ml_bearish" ? "active ml-bearish-tab" : ""}
              onClick={() => {
                setFilterPreset("ml_bearish");
                setStage2Filter("all");
                setBreakoutFilter("all");
              }}
              title="Bearish Breakdown / Exits: Predicted Return ≤ -2.5%, Research Score ≤ 45, and Drawdown ≤ -20% from 52W High"
            >
              🔴 ML Breakdowns ({counts.mlBearish})
            </button>
            <button
              type="button"
              className={filterPreset === "stage2" ? "active" : ""}
              onClick={() => {
                setFilterPreset("stage2");
                setStage2Filter("all");
                setBreakoutFilter("all");
              }}
            >
              ⚡ Stage 2 ({counts.stage2})
            </button>
            <button
              type="button"
              className={filterPreset === "breakout" ? "active" : ""}
              onClick={() => {
                setFilterPreset("breakout");
                setStage2Filter("all");
                setBreakoutFilter("all");
              }}
            >
              💥 52W Breakout ({counts.breakout})
            </button>
            <button
              type="button"
              className={filterPreset === "multibagger" ? "active" : ""}
              onClick={() => {
                setFilterPreset("multibagger");
                setStage2Filter("all");
                setBreakoutFilter("all");
              }}
            >
              🌟 Multibaggers ({counts.multibagger})
            </button>
            <button
              type="button"
              className={filterPreset === "multibagger_stage2" ? "active" : ""}
              onClick={() => {
                setFilterPreset("multibagger_stage2");
                setStage2Filter("all");
                setBreakoutFilter("all");
              }}
            >
              🚀 Multibagger + Stage 2 ({counts.mbStage2})
            </button>
            <button
              type="button"
              className={filterPreset === "tv_strong_buy" ? "active" : ""}
              onClick={() => {
                setFilterPreset("tv_strong_buy");
                setStage2Filter("all");
                setBreakoutFilter("all");
              }}
            >
              🔥 Strong Buy ({counts.tvStrongBuy})
            </button>
            <button
              type="button"
              className={filterPreset === "watchlist" ? "active" : ""}
              onClick={() => {
                setFilterPreset("watchlist");
                setStage2Filter("all");
                setBreakoutFilter("all");
              }}
            >
              ⭐ Watchlist ({counts.watchlist})
            </button>
            <Link
              href="/ai?tab=picks"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "5px",
                textDecoration: "none",
                padding: "4px 10px",
                borderRadius: "4px",
                fontSize: "0.85rem",
                fontWeight: 600,
                background: "rgba(16, 185, 129, 0.12)",
                color: "#10b981",
                border: "1px solid rgba(16, 185, 129, 0.3)",
                marginLeft: "4px",
              }}
              title="View daily AI multi-factor alpha picks (Momentum, Value, Quality, Earnings Revisions)"
            >
              <span>🎯 AI Alpha Picks (Top 10)</span>
            </Link>
          </div>
        </div>

        {/* Visual Sort & Filter Pills Bar */}
        <div className="sort-filter-bar">
          {/* Row 1: Sort Priority Pills & Multi-Sort Controls */}
          <div className="sort-filter-row">
            <span className="sort-filter-label">
              <span>Sort:</span>
            </span>

            {sortCriteria.map((crit, idx) => {
              const colDef = COLUMNS.find((c) => c.key === crit.key);
              const label = colDef?.label ?? crit.key;
              const isDefaultOnly = sortCriteria.length === 1 && crit.key === "day_change_pct" && crit.order === "desc";
              return (
                <span key={crit.key} className="sort-pill" title={`Sort Priority #${idx + 1}: ${label} (${crit.order.toUpperCase()})`}>
                  <span className="sort-pill-rank">#{idx + 1}</span>
                  <span style={{ fontWeight: 600 }}>{label}</span>
                  <button
                    type="button"
                    className="sort-pill-toggle"
                    onClick={() => handleToggleSortDirection(crit.key)}
                    title={`Click to reverse order to ${crit.order === "asc" ? "Descending (▼)" : "Ascending (▲)"}`}
                    aria-label={`Toggle direction for ${label}`}
                  >
                    {crit.order === "asc" ? "▲ ASC" : "▼ DESC"}
                  </button>
                  {!isDefaultOnly && (
                    <button
                      type="button"
                      className="sort-pill-remove"
                      onClick={() => handleRemoveSortCriterion(crit.key)}
                      title={`Remove sort by ${label}`}
                      aria-label={`Remove sort by ${label}`}
                    >
                      ✕
                    </button>
                  )}
                </span>
              );
            })}

            {availableSortColumns.length > 0 && (
              <select
                className="sort-add-select"
                value=""
                onChange={(e) => {
                  if (e.target.value) {
                    handleAddSortColumn(e.target.value as InstrumentSortKey);
                  }
                }}
                aria-label="Add sort column"
              >
                <option value="" disabled>
                  + Add Sort Column…
                </option>
                {availableSortColumns.map((col) => (
                  <option key={col.key} value={col.key}>
                    + {col.label}
                  </option>
                ))}
              </select>
            )}

            {hasCustomSort && (
              <button
                type="button"
                className="sort-reset-btn"
                onClick={handleResetSort}
                title="Reset sorting to Symbol (Ascending)"
              >
                Reset Sort
              </button>
            )}

            <span style={{ fontSize: "0.72rem", color: "var(--text-muted)", marginLeft: "auto", fontStyle: "italic" }}>
              💡 Shift+Click headers to chain multi-sort
            </span>
          </div>

          {/* Row 2: Active Filter Chips */}
          {activeFilters.length > 0 && (
            <div className="sort-filter-row" style={{ borderTop: "1px solid var(--panel-border)", paddingTop: "0.35rem" }}>
              <span className="sort-filter-label">
                <span>Active Filters:</span>
              </span>
              {activeFilters.map((filter) => (
                <span key={filter.id} className="filter-pill">
                  <span>{filter.label}</span>
                  <button
                    type="button"
                    className="filter-pill-remove"
                    onClick={filter.onRemove}
                    aria-label={`Remove ${filter.label}`}
                    title={`Remove ${filter.label}`}
                  >
                    ✕
                  </button>
                </span>
              ))}
              <button
                type="button"
                className="filter-clear-btn"
                onClick={handleClearAllFilters}
                title="Clear all active filters"
              >
                Clear All ({activeFilters.length})
              </button>
            </div>
          )}
        </div>

        {totalItems === 0 && (
          <div style={{ padding: "3rem 1rem", textAlign: "center", color: "var(--fg-muted)" }}>
            {filterPreset === "watchlist" ? (
              <div className="watchlist-empty-state">
                <div className="watchlist-empty-icon">⭐</div>
                <h3>Your Watchlist is Empty</h3>
                <p>
                  You haven&apos;t added any stocks to your watchlist yet. Click the star <strong>☆</strong> next to any stock symbol or open any stock to add it.
                </p>
              </div>
            ) : filterPreset === "ml_bullish" ? (
              <div className="watchlist-empty-state">
                <div className="watchlist-empty-icon">🟢</div>
                <h3>No ML Bullish Leaders Matching Criteria</h3>
                <p>
                  No stocks currently meet all bullish confluence criteria (Predicted 5D Return ≥ +1.5%, Research Score ≥ 60, and Stage 2 / within 15% of 52W High).
                </p>
              </div>
            ) : filterPreset === "ml_bearish" ? (
              <div className="watchlist-empty-state">
                <div className="watchlist-empty-icon">🔴</div>
                <h3>No High-Risk Breakdowns Matching Criteria</h3>
                <p>
                  No stocks currently meet severe breakdown criteria (Predicted 5D Return ≤ -2.5%, Research Score ≤ 45, and Drawdown ≤ -20% from 52W High).
                </p>
              </div>
            ) : (
              <>
                <p style={{ fontSize: "1.05rem", fontWeight: 600, marginBottom: "0.5rem", color: "var(--fg-default)" }}>
                  No instruments match your search or filters.
                </p>
                <p className="footnote" style={{ margin: 0 }}>
                  Try searching by a different symbol or name, or{" "}
                  <button
                    type="button"
                    onClick={handleClearAllFilters}
                    style={{
                      background: "none",
                      border: "none",
                      color: "var(--accent, #3b82f6)",
                      cursor: "pointer",
                      textDecoration: "underline",
                      padding: 0,
                      font: "inherit",
                    }}
                  >
                    clear your filters
                  </button>
                  .
                </p>
              </>
            )}
          </div>
        )}
        {totalItems > 0 && (
          <>
            <div className="market-table-scroll" ref={tableScrollRef}>
              <table className="market-table">
                <thead>
                  <tr>
                    <th className="col-sno sticky-col-1">#</th>
                    {COLUMNS.map((col, idx) => {
                      const critIndex = sortCriteria.findIndex((c) => c.key === col.key);
                      const isActive = critIndex >= 0;
                      const currentCrit = isActive ? sortCriteria[critIndex] : null;
                      const arrow = isActive ? (currentCrit!.order === "asc" ? "▲" : "▼") : "▴";
                      const priorityBadge = sortCriteria.length > 1 && isActive ? `${critIndex + 1}` : "";
                      const isNum = [
                        "score", "fundamental_score", "day_change_pct", "return_1w_pct", "return_1m_pct", "return_3m_pct", "return_1y_pct",
                        "revenue_growth_yoy", "pat_growth_yoy", "fii_change_qoq_pct", "analyst_upside_pct", "ml_forecast_5d_pct"
                      ].includes(col.key);
                      const isFirst = idx === 0;
                      const stickyClass = isFirst ? "sticky-col-2" : "";
                      const colClass = `col-${col.key} ${isNum ? "col-num" : ""} ${stickyClass}`;
                      return (
                        <th
                          key={col.key}
                          className={`sortable ${colClass}`}
                          aria-sort={isActive ? (currentCrit!.order === "asc" ? "ascending" : "descending") : "none"}
                          title="Click to sort single column. Shift+Click to sort by multiple columns."
                          onClick={(e) => handleSortClick(col.key, e)}
                        >
                          <span style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
                            {col.label}
                            {priorityBadge && (
                              <span
                                style={{
                                  fontSize: "0.65rem",
                                  padding: "1px 4px",
                                  borderRadius: "3px",
                                  background: "var(--accent, #3b82f6)",
                                  color: "var(--accent-contrast, #fff)",
                                  fontWeight: 700,
                                  lineHeight: 1,
                                 }}
                              >
                                {priorityBadge}
                              </span>
                            )}
                            <span className={`sort-indicator${isActive ? "" : " inactive"}`}>{arrow}</span>
                          </span>
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody>
                  {paginatedRows.map((row, index) => {
                    const isNavigating = navigatingSymbol === row.symbol;
                    return (
                      <tr
                        key={`${row.exchange}:${row.symbol}`}
                        className={`row-link ${isNavigating ? "is-navigating" : ""}`}
                        onPointerEnter={() => {
                          saveStockSummary(row);
                          router.prefetch(`/stocks/${row.symbol}`);
                          prefetchStock(row.symbol);
                        }}
                        onClick={(e) => handleRowClick(row.symbol, row, e)}
                      >
                        <td className="col-sno sticky-col-1">{startIndex + index + 1}</td>
                        <td className="col-instrument sticky-col-2">
                          <div className="instrument-cell">
                            <button
                              type="button"
                              className={`star-btn ${watchlistSet.has(row.symbol.toUpperCase()) ? "active" : ""}`}
                              title={watchlistSet.has(row.symbol.toUpperCase()) ? "Remove from Watchlist" : "Add to Watchlist"}
                              onClick={(e) => {
                                e.stopPropagation();
                                toggleWatchlistSymbol(row.symbol);
                              }}
                            >
                              {watchlistSet.has(row.symbol.toUpperCase()) ? "★" : "☆"}
                            </button>
                            <div className="instrument-info">
                              <div className="symbol-row">
                                <Link
                                  href={`/stocks/${row.symbol}`}
                                  prefetch={false}
                                  className="instrument-symbol link-hover"
                                  title={`Open ${row.symbol} complete details (Cmd+Click or Middle-Click for new tab)`}
                                  onClick={(e) => {
                                    if (e.metaKey || e.ctrlKey || e.button === 1) return;
                                    saveStockSummary(row);
                                  }}
                                >
                                  {row.symbol}
                                </Link>

                                <div className="symbol-action-buttons">
                                  {/* 1-click Copy Symbol */}
                                  <button
                                    type="button"
                                    className={`symbol-action-btn copy-btn ${copiedSymbol === row.symbol ? "copied" : ""}`}
                                    title={copiedSymbol === row.symbol ? "Copied!" : `Copy symbol "${row.symbol}"`}
                                    aria-label={`Copy symbol ${row.symbol}`}
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      handleCopySingleSymbol(row.symbol);
                                    }}
                                  >
                                    {copiedSymbol === row.symbol ? (
                                      <span className="copied-check">✓</span>
                                    ) : (
                                      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                                        <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                                        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                                      </svg>
                                    )}
                                  </button>

                                  {/* 1-click Open in New Tab */}
                                  <a
                                    href={`/stocks/${row.symbol}`}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="symbol-action-btn new-tab-btn"
                                    title={`Open ${row.symbol} in a new tab`}
                                    aria-label={`Open ${row.symbol} in a new tab`}
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      saveStockSummary(row);
                                    }}
                                  >
                                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                                      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                                      <polyline points="15 3 21 3 21 9"></polyline>
                                      <line x1="10" y1="14" x2="21" y2="3"></line>
                                    </svg>
                                  </a>

                                  {isNavigating && <span className="row-nav-spinner" title="Navigating..." />}
                                </div>
                              </div>
                              <span className="instrument-name" title={row.company_name}>{row.company_name}</span>
                            </div>
                          </div>
                        </td>
                      <td className="col-sector" title={row.sector ?? "Unclassified"}>
                        <span className="badge">{row.sector ?? "Unclassified"}</span>
                      </td>
                      <td className="col-num">
                        <ScoreCell row={row} />
                      </td>
                      <td className="col-num">
                        <FundamentalScoreCell row={row} />
                      </td>
                      <td className="col-multibagger" style={{ textAlign: "center" }}>
                        <MultibaggerCell row={row} onOpenChecklist={(sym) => setModalSymbol(sym)} />
                      </td>
                      <td className="col-stage2">
                        <Stage2Cell row={row} />
                      </td>
                      <td className="col-vcp">
                        <VCPCell row={row} />
                      </td>
                      <td className="col-tv-signal" style={{ textAlign: "center" }}>
                        <TVSignalCell row={row} />
                      </td>
                      <td className="col-analyst-rating" style={{ textAlign: "center" }}>
                        <AnalystRatingCell row={row} />
                      </td>
                      <td className="col-num">
                        <DayChangeCell row={row} />
                      </td>
                      <td className="col-num">
                        <ReturnCell val={row.return_1w_pct} />
                      </td>
                      <td className="col-num">
                        <ReturnCell val={row.return_1m_pct} />
                      </td>
                      <td className="col-num">
                        <ReturnCell val={row.return_3m_pct} />
                      </td>
                      <td className="col-num">
                        <ReturnCell val={row.return_1y_pct} />
                      </td>
                      <td className="col-num">
                        <GrowthCell val={row.revenue_growth_yoy} />
                      </td>
                      <td className="col-num">
                        <GrowthCell val={row.pat_growth_yoy} />
                      </td>
                      <td className="col-num">
                        <FiiChangeCell row={row} />
                      </td>
                      <td className="col-num">
                        <AnalystTargetCell row={row} />
                      </td>
                      <td className="col-num">
                        <ReturnCell val={row.ml_forecast_5d_pct} />
                      </td>
                    </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="market-pagination">
              <div className="pagination-info">
                Showing <strong>{startIndex + 1}–{endIndex}</strong> of <strong>{totalItems}</strong> instruments
                {totalPages > 1 && (
                  <span>
                    {" "}(Page {validCurrentPage} of {totalPages})
                  </span>
                )}
              </div>

              {totalPages > 1 && (
                <div className="pagination-controls">
                  <button
                    type="button"
                    className="pagination-btn"
                    onClick={() => handlePageChange(1)}
                    disabled={validCurrentPage === 1}
                    title="First page"
                    aria-label="First page"
                  >
                    «
                  </button>
                  <button
                    type="button"
                    className="pagination-btn"
                    onClick={() => handlePageChange(validCurrentPage - 1)}
                    disabled={validCurrentPage === 1}
                    title="Previous page"
                    aria-label="Previous page"
                  >
                    ‹ Prev
                  </button>

                  {getPaginationPages(validCurrentPage, totalPages).map((p, idx) =>
                    p === "..." ? (
                      <span key={`dots-${idx}`} className="pagination-ellipsis">
                        …
                      </span>
                    ) : (
                      <button
                        key={p}
                        type="button"
                        className={`pagination-btn ${p === validCurrentPage ? "active" : ""}`}
                        onClick={() => handlePageChange(p as number)}
                      >
                        {p}
                      </button>
                    )
                  )}

                  <button
                    type="button"
                    className="pagination-btn"
                    onClick={() => handlePageChange(validCurrentPage + 1)}
                    disabled={validCurrentPage === totalPages}
                    title="Next page"
                    aria-label="Next page"
                  >
                    Next ›
                  </button>
                  <button
                    type="button"
                    className="pagination-btn"
                    onClick={() => handlePageChange(totalPages)}
                    disabled={validCurrentPage === totalPages}
                    title="Last page"
                    aria-label="Last page"
                  >
                    »
                  </button>
                </div>
              )}

              <div className="pagination-page-size">
                <label htmlFor="pageSizeSelect">Per page:</label>
                <select
                  id="pageSizeSelect"
                  className="pagination-select"
                  value={pageSize}
                  onChange={(e) => setPageSize(Number(e.target.value))}
                >
                  <option value={25}>25</option>
                  <option value={50}>50 (Default)</option>
                  <option value={100}>100</option>
                  <option value={200}>200</option>
                  <option value={0}>All ({totalItems})</option>
                </select>
              </div>
            </div>
          </>
        )}
      </div>
      </div>

      {/* Multibagger 6-Pillar Checklist Modal */}
      {modalSymbol && (
        <div
          className="modal-overlay"
          onClick={() => setModalSymbol(null)}
          style={{
            position: "fixed",
            inset: 0,
            backgroundColor: "rgba(0, 0, 0, 0.75)",
            backdropFilter: "blur(4px)",
            zIndex: 1000,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "1rem",
          }}
        >
          <div
            className="modal-content"
            onClick={(e) => e.stopPropagation()}
            style={{
              maxWidth: "960px",
              width: "100%",
              maxHeight: "90vh",
              overflowY: "auto",
              position: "relative",
              borderRadius: "12px",
              background: "var(--panel)",
              border: "1px solid var(--border)",
              boxShadow: "0 20px 40px rgba(0,0,0,0.5)",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "1rem 1.25rem",
                borderBottom: "1px solid var(--border)",
                background: "var(--bg-muted)",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                <span style={{ fontSize: "1.2rem" }}>🌟</span>
                <span style={{ fontWeight: 700, fontSize: "1.1rem" }}>{modalSymbol} — Multibagger Checklist</span>
              </div>
              <button
                type="button"
                onClick={() => setModalSymbol(null)}
                style={{
                  background: "transparent",
                  border: "none",
                  fontSize: "1.25rem",
                  cursor: "pointer",
                  color: "var(--fg-muted)",
                  padding: "4px 8px",
                }}
                aria-label="Close modal"
              >
                ✕
              </button>
            </div>
            <div style={{ padding: "1rem" }}>
              <StockChecklistPanel symbol={modalSymbol} />
            </div>
          </div>
        </div>
      )}
    </>
  );
}
