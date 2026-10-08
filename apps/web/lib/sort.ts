import type { InstrumentSortKey, InstrumentSummary, SortOrder } from "./types";

// Client-side sort for whatever rows are currently displayed. The home
// page's main "browse all" table re-fetches from the server with
// `?sort=&order=` (apps/api/routes/instruments.py does the real
// sorting there); this is only used to sort the *search* results list
// (GET /api/v1/instruments/search has no sort param - its contract is
// intentionally left untouched), so clicking a column header still
// works while a search query is active. Mirrors the server's "null
// scores always sort last, regardless of direction" rule exactly.
export function sortInstruments(
  rows: InstrumentSummary[],
  key: InstrumentSortKey,
  order: SortOrder
): InstrumentSummary[] {
  const sign = order === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    if (key === "score") {
      if (a.score === null && b.score === null) return a.symbol.localeCompare(b.symbol);
      if (a.score === null) return 1;
      if (b.score === null) return -1;
      return (a.score - b.score) * sign;
    }

    if (key === "momentum_pass") {
      if (a.momentum_pass === null && b.momentum_pass === null) return a.symbol.localeCompare(b.symbol);
      if (a.momentum_pass === null) return 1;
      if (b.momentum_pass === null) return -1;
      // true-first on desc, matching the server's rule.
      return ((a.momentum_pass ? 1 : 0) - (b.momentum_pass ? 1 : 0)) * sign;
    }

    if (key === "analyst_upside_pct" || key === "day_change_pct") {
      const aVal = a[key];
      const bVal = b[key];
      if (aVal === null && bVal === null) return a.symbol.localeCompare(b.symbol);
      if (aVal === null) return 1;
      if (bVal === null) return -1;
      return (aVal - bVal) * sign;
    }

    const aValue = a[key] ?? "";
    const bValue = b[key] ?? "";
    const cmp = String(aValue).localeCompare(String(bValue));
    return cmp !== 0 ? cmp * sign : a.symbol.localeCompare(b.symbol);
  });
}
