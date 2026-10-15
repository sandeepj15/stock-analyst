"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { listInstruments, searchInstruments } from "../lib/api";
import { bandColor } from "../lib/bands";
import { sortInstrumentsMulti } from "../lib/sort";
import type { InstrumentSortKey, InstrumentSummary, SortCriterion, SortOrder } from "../lib/types";
import MarketPulse from "./MarketPulse";

interface Column {
  key: InstrumentSortKey;
  label: string;
}

const COLUMNS: Column[] = [
  { key: "symbol", label: "Instrument" },
  { key: "sector", label: "Sector" },
  { key: "score", label: "Score" },
  { key: "momentum_pass", label: "Stage 2" },
  { key: "is_vcp_setup", label: "VCP" },
  { key: "day_change_pct", label: "Day %" },
  { key: "return_1m_pct" as any, label: "1M %" },
  { key: "return_1y_pct" as any, label: "1Y %" },
  { key: "revenue_growth_yoy", label: "Rev YoY" },
  { key: "pat_growth_yoy", label: "PAT YoY" },
  { key: "analyst_upside_pct", label: "Target" },
  { key: "ml_forecast_5d_pct", label: "5D ML %" },
];

function ScoreCell({ row }: { row: InstrumentSummary }) {
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
}

function ReturnCell({ val }: { val: number | null }) {
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
}

function DayChangeCell({ row }: { row: InstrumentSummary }) {
  return <ReturnCell val={row.day_change_pct} />;
}

// 1-year analyst consensus price target + % upside/downside vs. the
// current price (apps/api/routes/analyst.py, apps/api/routes/
// instruments.py). Green = target above current price (upside), red =
// below (downside) - reuses --up/--down, same convention as the Stage 2
// badge above. "No coverage" is a genuine, common state (many
// mid/small-cap NSE names have zero analyst coverage), never a
// fabricated number.
function GrowthCell({ val }: { val: number | null }) {
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
}

function AnalystTargetCell({ row }: { row: InstrumentSummary }) {
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
}

function VCPCell({ row }: { row: InstrumentSummary }) {
  if (row.is_vcp_setup === null) return <span className="stage2-badge stage2-na">—</span>;
  if (row.is_vcp_setup) return <span className="stage2-badge stage2-pass">✓ Setup</span>;
  return <span className="stage2-badge stage2-fail">No</span>;
}


function Stage2Cell({ row }: { row: InstrumentSummary }) {
  if (row.momentum_pass === null) {
    return <span className="stage2-badge stage2-na">—</span>;
  }
  if (row.momentum_pass) {
    return (
      <span className="stage2-badge stage2-pass">
        ✓ Pass
        {row.distance_from_52w_high_pct !== null && (
          <span className="stage2-distance num"> {row.distance_from_52w_high_pct.toFixed(1)}%</span>
        )}
      </span>
    );
  }
  return <span className="stage2-badge stage2-fail">✗ Fail</span>;
}

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
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<InstrumentSummary[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  const [instruments, setInstruments] = useState<InstrumentSummary[]>(initialInstruments);
  const [sortCriteria, setSortCriteria] = useState<SortCriterion[]>([
    { key: "symbol", order: "asc" },
  ]);
  const [pageSize, setPageSize] = useState<number>(200);
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [refreshing, setRefreshing] = useState(false);
  const tableScrollRef = useRef<HTMLDivElement>(null);
  const [stage2Only, setStage2Only] = useState(false);
  // Research Score band filter, driven by clicking a bar in the Market
  // Pulse dashboard's score-distribution chart (UI/UX "Market Pulse"
  // task) - client-side only (filters whatever rows are already loaded,
  // same scoping as the search-results sort in lib/sort.ts), combinable
  // with "Stage 2 Only" above rather than mutually exclusive.
  const [bandFilter, setBandFilter] = useState<string | null>(null);
  // Sector filter, driven by clicking a cell in the Market Pulse
  // dashboard's sector heatmap - same client-side-only pattern as
  // bandFilter above, combinable with it and with "Stage 2 Only".
  // `row.sector` can be `null` (table displays "Unclassified" for that
  // case, matching the heatmap's `COALESCE(sector, 'Unclassified')`
  // grouping - apps/api/routes/market.py), so the comparison must apply
  // the same fallback.
  const [sectorFilter, setSectorFilter] = useState<string | null>(null);

  useEffect(() => {
    const trimmed = query.trim();
    if (trimmed.length === 0) {
      setSearchResults(null);
      setSearchError(null);
      return;
    }

    setSearching(true);
    const handle = setTimeout(async () => {
      try {
        const results = await searchInstruments(trimmed);
        setSearchResults(results);
        setSearchError(null);
      } catch (err) {
        setSearchError(err instanceof Error ? err.message : "Search failed.");
        setSearchResults([]);
      } finally {
        setSearching(false);
      }
    }, 250); // debounce - hits GET /api/v1/instruments/search

    return () => clearTimeout(handle);
  }, [query]);

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
      return updated.length > 0 ? updated : [{ key: "symbol", order: "asc" }];
    });
  }

  function handleResetSort() {
    setSortCriteria([{ key: "symbol", order: "asc" }]);
  }

  function handleClearAllFilters() {
    setQuery("");
    setSectorFilter(null);
    setBandFilter(null);
    setStage2Only(false);
    setMinScoreFilter("");
    setMaxScoreFilter("");
    setMinAnalystUpside("");
    setMinRevGrowth("");
    setMinPatGrowth("");
    setMinReturn1M("");
    setMinReturn6M("");
    setMinReturn1Y("");
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
  const [minAnalystUpside, setMinAnalystUpside] = useState<number | "">("");
  const [minRevGrowth, setMinRevGrowth] = useState<number | "">("");
  const [minPatGrowth, setMinPatGrowth] = useState<number | "">("");
  const [minReturn1M, setMinReturn1M] = useState<number | "">("");
  const [minReturn6M, setMinReturn6M] = useState<number | "">("");
  const [minReturn1Y, setMinReturn1Y] = useState<number | "">("");

  const rows = useMemo(() => {
    const base = searchResults ?? instruments;
    let filtered = base;

    if (stage2Only) {
      filtered = filtered.filter((row) => row.momentum_pass === true);
    }
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
    if (minAnalystUpside !== "") {
      filtered = filtered.filter((row) => row.analyst_upside_pct !== null && row.analyst_upside_pct >= minAnalystUpside);
    }
    if (minRevGrowth !== "") {
      filtered = filtered.filter((row) => row.revenue_growth_yoy !== null && (row.revenue_growth_yoy * 100) >= minRevGrowth);
    }
    if (minPatGrowth !== "") {
      filtered = filtered.filter((row) => row.pat_growth_yoy !== null && (row.pat_growth_yoy * 100) >= minPatGrowth);
    }
    if (minReturn1M !== "") {
      filtered = filtered.filter((row) => row.return_1m_pct !== null && row.return_1m_pct >= minReturn1M);
    }
    if (minReturn6M !== "") {
      filtered = filtered.filter((row) => row.return_6m_pct !== null && row.return_6m_pct >= minReturn6M);
    }
    if (minReturn1Y !== "") {
      filtered = filtered.filter((row) => row.return_1y_pct !== null && row.return_1y_pct >= minReturn1Y);
    }

    return sortInstrumentsMulti(filtered, sortCriteria);
  }, [searchResults, instruments, sortCriteria, stage2Only, bandFilter, sectorFilter, minScoreFilter, maxScoreFilter, minAnalystUpside, minRevGrowth, minPatGrowth, minReturn1M, minReturn6M, minReturn1Y]);

  useEffect(() => {
    setCurrentPage(1);
  }, [
    query,
    bandFilter,
    sectorFilter,
    stage2Only,
    sortCriteria,
    minScoreFilter,
    maxScoreFilter,
    minAnalystUpside,
    minRevGrowth,
    minPatGrowth,
    minReturn1M,
    minReturn6M,
    minReturn1Y,
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
    stage2Only ||
    minScoreFilter !== "" ||
    maxScoreFilter !== "" ||
    minAnalystUpside !== "" ||
    minRevGrowth !== "" ||
    minPatGrowth !== "" ||
    minReturn1M !== "" ||
    minReturn6M !== "" ||
    minReturn1Y !== ""
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
      list.push({ id: "band", label: `Band: ${bandFilter}`, onRemove: () => setBandFilter(null) });
    }
    if (stage2Only) {
      list.push({ id: "stage2", label: "Stage 2 Only", onRemove: () => setStage2Only(false) });
    }
    if (minScoreFilter !== "") {
      list.push({ id: "minScore", label: `Score ≥ ${minScoreFilter}`, onRemove: () => setMinScoreFilter("") });
    }
    if (maxScoreFilter !== "") {
      list.push({ id: "maxScore", label: `Score ≤ ${maxScoreFilter}`, onRemove: () => setMaxScoreFilter("") });
    }
    if (minAnalystUpside !== "") {
      list.push({ id: "upside", label: `Upside ≥ ${minAnalystUpside}%`, onRemove: () => setMinAnalystUpside("") });
    }
    if (minRevGrowth !== "") {
      list.push({ id: "revGrowth", label: `Rev YoY ≥ ${minRevGrowth}%`, onRemove: () => setMinRevGrowth("") });
    }
    if (minPatGrowth !== "") {
      list.push({ id: "patGrowth", label: `PAT YoY ≥ ${minPatGrowth}%`, onRemove: () => setMinPatGrowth("") });
    }
    if (minReturn1M !== "") {
      list.push({ id: "return1m", label: `1M Return ≥ ${minReturn1M}%`, onRemove: () => setMinReturn1M("") });
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
    stage2Only,
    minScoreFilter,
    maxScoreFilter,
    minAnalystUpside,
    minRevGrowth,
    minPatGrowth,
    minReturn1M,
    minReturn6M,
    minReturn1Y,
  ]);

  const hasCustomSort =
    sortCriteria.length > 1 ||
    (sortCriteria.length === 1 && (sortCriteria[0].key !== "symbol" || sortCriteria[0].order !== "asc"));

  return (
    <>
      <MarketPulse
        instruments={initialInstruments}
        selectedBand={bandFilter}
        onSelectBand={setBandFilter}
        selectedSector={sectorFilter}
        onSelectSector={setSectorFilter}
      />

      <div className="panel search-box">
        <h2>Screener & Search</h2>
        <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", marginBottom: "1rem" }}>
          <div style={{ flex: "1 1 250px" }}>
            <label style={{ display: "block", fontSize: "0.85rem", marginBottom: "0.25rem", color: "var(--fg-muted)" }}>Search (Symbol/Name)</label>
            <input
              type="text"
              placeholder="e.g. RELIANCE, TCS"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              style={{ width: "100%" }}
            />
          </div>
          <div style={{ flex: "1 1 200px" }}>
            <label style={{ display: "block", fontSize: "0.85rem", marginBottom: "0.25rem", color: "var(--fg-muted)" }}>Sector</label>
            <select
              value={sectorFilter ?? ""}
              onChange={(e) => setSectorFilter(e.target.value === "" ? null : e.target.value)}
              style={{ width: "100%", padding: "8px", borderRadius: "4px", border: "1px solid var(--border)", background: "var(--bg)" }}
            >
              <option value="">All Sectors</option>
              {sectorsList.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div style={{ flex: "0 1 120px" }}>
            <label style={{ display: "block", fontSize: "0.85rem", marginBottom: "0.25rem", color: "var(--fg-muted)" }}>Min Score</label>
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
          <div style={{ flex: "0 1 120px" }}>
            <label style={{ display: "block", fontSize: "0.85rem", marginBottom: "0.25rem", color: "var(--fg-muted)" }}>Max Score</label>
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
          <div style={{ flex: "0 1 140px" }}>
            <label style={{ display: "block", fontSize: "0.85rem", marginBottom: "0.25rem", color: "var(--fg-muted)" }}>Min Upside %</label>
            <input
              type="number"
              placeholder="e.g. 15"
              value={minAnalystUpside}
              onChange={(e) => setMinAnalystUpside(e.target.value === "" ? "" : Number(e.target.value))}
              style={{ width: "100%" }}
            />
          </div>
          <div style={{ flex: "0 1 140px" }}>
            <label style={{ display: "block", fontSize: "0.85rem", marginBottom: "0.25rem", color: "var(--fg-muted)" }}>Min Rev Growth %</label>
            <input
              type="number"
              placeholder="e.g. 10"
              value={minRevGrowth}
              onChange={(e) => setMinRevGrowth(e.target.value === "" ? "" : Number(e.target.value))}
              style={{ width: "100%" }}
            />
          </div>
          <div style={{ flex: "0 1 140px" }}>
            <label style={{ display: "block", fontSize: "0.85rem", marginBottom: "0.25rem", color: "var(--fg-muted)" }}>Min PAT Growth %</label>
            <input
              type="number"
              placeholder="e.g. 15"
              value={minPatGrowth}
              onChange={(e) => setMinPatGrowth(e.target.value === "" ? "" : Number(e.target.value))}
              style={{ width: "100%" }}
            />
          </div>
          <div style={{ flex: "0 1 120px" }}>
            <label style={{ display: "block", fontSize: "0.85rem", marginBottom: "0.25rem", color: "var(--fg-muted)" }}>Min 1M Return %</label>
            <input
              type="number"
              placeholder="e.g. 5"
              value={minReturn1M}
              onChange={(e) => setMinReturn1M(e.target.value === "" ? "" : Number(e.target.value))}
              style={{ width: "100%" }}
            />
          </div>
          <div style={{ flex: "0 1 120px" }}>
            <label style={{ display: "block", fontSize: "0.85rem", marginBottom: "0.25rem", color: "var(--fg-muted)" }}>Min 6M Return %</label>
            <input
              type="number"
              placeholder="e.g. 20"
              value={minReturn6M}
              onChange={(e) => setMinReturn6M(e.target.value === "" ? "" : Number(e.target.value))}
              style={{ width: "100%" }}
            />
          </div>
          <div style={{ flex: "0 1 120px" }}>
            <label style={{ display: "block", fontSize: "0.85rem", marginBottom: "0.25rem", color: "var(--fg-muted)" }}>Min 1Y Return %</label>
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
          <div className="notice error" style={{ marginBottom: "1rem", padding: "8px" }}>
            Min Score cannot be greater than Max Score.
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
          <h2 style={{ margin: 0 }}>{searchResults ? `Search results for "${query}"` : "Browse all instruments"}</h2>
          <div className="filter-tabs" title={searchResults ? "Clear your search to use the Stage 2 filter" : undefined}>
            <button
              type="button"
              className={!stage2Only ? "active" : ""}
              disabled={!!searchResults}
              onClick={() => setStage2Only(false)}
            >
              All
            </button>
            <button
              type="button"
              className={stage2Only ? "active" : ""}
              disabled={!!searchResults}
              onClick={() => setStage2Only(true)}
            >
              Stage 2 Only
            </button>
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
              const isDefaultOnly = sortCriteria.length === 1 && crit.key === "symbol" && crit.order === "asc";
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
        {searching && <p className="footnote">Searching…</p>}
        {searchError && <div className="notice error">{searchError}</div>}
        {!searching && totalItems === 0 && <p className="footnote">No matches.</p>}
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
                        "score", "day_change_pct", "return_1m_pct", "return_1y_pct",
                        "revenue_growth_yoy", "pat_growth_yoy", "analyst_upside_pct", "ml_forecast_5d_pct"
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
                  {paginatedRows.map((row, index) => (
                    <tr
                      key={`${row.exchange}:${row.symbol}`}
                      className="row-link"
                      onClick={() => router.push(`/stocks/${row.symbol}`)}
                    >
                      <td className="col-sno sticky-col-1">{startIndex + index + 1}</td>
                      <td className="col-instrument sticky-col-2">
                        <div className="instrument-cell">
                          <span className="instrument-symbol">{row.symbol}</span>
                          <span className="instrument-name" title={row.company_name}>{row.company_name}</span>
                        </div>
                      </td>
                      <td className="col-sector" title={row.sector ?? "Unclassified"}>
                        <span className="badge">{row.sector ?? "Unclassified"}</span>
                      </td>
                      <td className="col-num">
                        <ScoreCell row={row} />
                      </td>
                      <td className="col-stage2">
                        <Stage2Cell row={row} />
                      </td>
                      <td className="col-vcp">
                        <VCPCell row={row} />
                      </td>
                      <td className="col-num">
                        <DayChangeCell row={row} />
                      </td>
                      <td className="col-num">
                        <ReturnCell val={row.return_1m_pct} />
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
                        <AnalystTargetCell row={row} />
                      </td>
                      <td className="col-num">
                        <ReturnCell val={row.ml_forecast_5d_pct} />
                      </td>
                    </tr>
                  ))}
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
                  <option value={50}>50</option>
                  <option value={100}>100</option>
                  <option value={200}>200 (Default)</option>
                  <option value={500}>500</option>
                  <option value={0}>All ({totalItems})</option>
                </select>
              </div>
            </div>
          </>
        )}
      </div>
    </>
  );
}
