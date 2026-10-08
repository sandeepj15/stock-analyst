"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { listInstruments, searchInstruments } from "../lib/api";
import { bandColor } from "../lib/bands";
import { sortInstruments } from "../lib/sort";
import type { InstrumentSortKey, InstrumentSummary, SortOrder } from "../lib/types";
import MarketPulse from "./MarketPulse";

interface Column {
  key: InstrumentSortKey;
  label: string;
}

const COLUMNS: Column[] = [
  { key: "symbol", label: "Symbol" },
  { key: "company_name", label: "Company" },
  { key: "sector", label: "Sector" },
  { key: "score", label: "Research Score" },
  { key: "momentum_pass", label: "Stage 2" },
  { key: "day_change_pct", label: "Day %" },
  { key: "revenue_growth_yoy", label: "Rev Growth YoY" },
  { key: "pat_growth_yoy", label: "Profit Growth YoY" },
  { key: "analyst_upside_pct", label: "Analyst Target" },
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

function DayChangeCell({ row }: { row: InstrumentSummary }) {
  if (row.day_change_pct === null) {
    return <span className="day-change flat">—</span>;
  }
  const tone = row.day_change_pct > 0 ? "up" : row.day_change_pct < 0 ? "down" : "flat";
  const sign = row.day_change_pct > 0 ? "+" : "";
  return (
    <span className={`day-change num ${tone}`}>
      {sign}
      {row.day_change_pct.toFixed(2)}%
    </span>
  );
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

export default function HomeBrowser({ initialInstruments }: { initialInstruments: InstrumentSummary[] }) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<InstrumentSummary[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  const [instruments, setInstruments] = useState<InstrumentSummary[]>(initialInstruments);
  const [sortKey, setSortKey] = useState<InstrumentSortKey>("symbol");
  const [sortOrder, setSortOrder] = useState<SortOrder>("asc");
  const [sortLoading, setSortLoading] = useState(false);
  const [sortError, setSortError] = useState<string | null>(null);
  // "Stage 2 Only" quick filter (SPEC.md section 39's Setup Scanner
  // concept) - server-side via ?momentum_pass=true, same reasoning as
  // sort/order being server-side above. Only applies to the "browse
  // all" table, same scoping as sort while a search query is active.
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

  // Clicking a header while browsing the full list re-fetches from the
  // server with ?sort=&order= (apps/api/routes/instruments.py does the
  // real sort + null-score-last handling there). GET /search has no sort
  // param by design, so while a search query is active the same click
  // instead sorts the current search results client-side (lib/sort.ts).
  const isFirstSort = useRef(true);
  useEffect(() => {
    if (query.trim().length > 0) return;
    // Skip the redundant fetch on first mount: initialInstruments
    // (loaded server-side by app/page.tsx) already reflects the default
    // sort=symbol/order=asc/no filter, so there's nothing new to fetch yet.
    if (isFirstSort.current && sortKey === "symbol" && sortOrder === "asc" && !stage2Only) {
      isFirstSort.current = false;
      return;
    }
    isFirstSort.current = false;
    let cancelled = false;
    setSortLoading(true);
    listInstruments({ sort: sortKey, order: sortOrder, momentumPass: stage2Only ? true : undefined })
      .then((rows) => {
        if (!cancelled) {
          setInstruments(rows);
          setSortError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setSortError(err instanceof Error ? err.message : "Could not re-sort the list.");
      })
      .finally(() => {
        if (!cancelled) setSortLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sortKey, sortOrder, stage2Only]);

  function handleSortClick(key: InstrumentSortKey) {
    if (key === sortKey) {
      setSortOrder((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortOrder("asc");
    }
  }

  const rows = useMemo(() => {
    const base = searchResults ? sortInstruments(searchResults, sortKey, sortOrder) : instruments;
    // Band filter (Market Pulse's score-distribution chart) is
    // client-side only and applies on top of whatever base rows are
    // already loaded - same scoping as the search-results sort above.
    const bandFiltered = bandFilter ? base.filter((row) => row.band === bandFilter) : base;
    if (!sectorFilter) return bandFiltered;
    return bandFiltered.filter((row) => (row.sector ?? "Unclassified") === sectorFilter);
  }, [searchResults, instruments, sortKey, sortOrder, bandFilter, sectorFilter]);

  const sectors = useMemo(() => {
    const set = new Set<string>();
    initialInstruments.forEach((i) => i.sector && set.add(i.sector));
    return set.size;
  }, [initialInstruments]);

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
        <h2>Find a stock</h2>
        <input
          type="text"
          placeholder="Search by symbol or company name (e.g. RELIANCE, TCS, Infosys)"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <p className="footnote">
          {initialInstruments.length} instruments seeded across {sectors} sectors (NSE). Click any row to open its
          research page. Click a column header to sort.
        </p>
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
          {bandFilter && (
            <span className="band-filter-chip">
              Band: {bandFilter}
              <button type="button" onClick={() => setBandFilter(null)} aria-label="Clear band filter">
                ✕
              </button>
            </span>
          )}
          {sectorFilter && (
            <span className="band-filter-chip">
              Sector: {sectorFilter}
              <button type="button" onClick={() => setSectorFilter(null)} aria-label="Clear sector filter">
                ✕
              </button>
            </span>
          )}
        </div>
        {searching && <p className="footnote">Searching…</p>}
        {searchError && <div className="notice error">{searchError}</div>}
        {sortError && <div className="notice error">{sortError}</div>}
        {!searching && rows.length === 0 && <p className="footnote">No matches.</p>}
        {rows.length > 0 && (
          <div className="market-table-scroll">
            <table
              className="market-table"
              style={{ opacity: sortLoading ? 0.6 : 1, transition: "opacity 0.1s ease" }}
            >
              <thead>
                <tr>
                  <th>S.No</th>
                  {COLUMNS.map((col) => {
                    const active = col.key === sortKey;
                    const arrow = active ? (sortOrder === "asc" ? "▲" : "▼") : "▴";
                    return (
                      <th
                        key={col.key}
                        className="sortable"
                        aria-sort={active ? (sortOrder === "asc" ? "ascending" : "descending") : "none"}
                        onClick={() => handleSortClick(col.key)}
                      >
                        {col.label}
                        <span className={`sort-indicator${active ? "" : " inactive"}`}>{arrow}</span>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, index) => (
                  <tr
                    key={`${row.exchange}:${row.symbol}`}
                    className="row-link"
                    onClick={() => router.push(`/stocks/${row.symbol}`)}
                  >
                    <td>{index + 1}</td>
                    <td>
                      <strong>{row.symbol}</strong>
                    </td>
                    <td>{row.company_name}</td>
                    <td>
                      <span className="badge">{row.sector ?? "Unclassified"}</span>
                    </td>
                    <td>
                      <ScoreCell row={row} />
                    </td>
                    <td>
                      <Stage2Cell row={row} />
                    </td>
                    <td>
                      <DayChangeCell row={row} />
                    </td>
                    <td>
                      <GrowthCell val={row.revenue_growth_yoy} />
                    </td>
                    <td>
                      <GrowthCell val={row.pat_growth_yoy} />
                    </td>
                    <td>
                      <AnalystTargetCell row={row} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
