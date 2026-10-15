import type { InstrumentSortKey, InstrumentSummary, SortCriterion, SortOrder } from "./types";

function compareSingleKey(
  a: InstrumentSummary,
  b: InstrumentSummary,
  key: InstrumentSortKey,
  order: SortOrder
): number {
  const sign = order === "asc" ? 1 : -1;
  if (key === "score") {
    if (a.score === null && b.score === null) return 0;
    if (a.score === null) return 1;
    if (b.score === null) return -1;
    return (a.score - b.score) * sign;
  }

  if (key === "is_vcp_setup") {
    if (a.is_vcp_setup === null && b.is_vcp_setup === null) return 0;
    if (a.is_vcp_setup === null) return 1;
    if (b.is_vcp_setup === null) return -1;
    return ((a.is_vcp_setup ? 1 : 0) - (b.is_vcp_setup ? 1 : 0)) * sign;
  }

  if (key === "momentum_pass") {
    if (a.momentum_pass === null && b.momentum_pass === null) return 0;
    if (a.momentum_pass === null) return 1;
    if (b.momentum_pass === null) return -1;
    // true-first on desc, matching the server's rule.
    return ((a.momentum_pass ? 1 : 0) - (b.momentum_pass ? 1 : 0)) * sign;
  }

  if (
    key === "analyst_upside_pct" ||
    key === "day_change_pct" ||
    key === "return_1w_pct" ||
    key === "return_1m_pct" ||
    key === "return_3m_pct" ||
    key === "return_6m_pct" ||
    key === "return_1y_pct" ||
    key === "revenue_growth_yoy" ||
    key === "pat_growth_yoy" ||
    key === "ml_forecast_5d_pct"
  ) {
    const aVal = a[key];
    const bVal = b[key];
    if (aVal === null && bVal === null) return 0;
    if (aVal === null) return 1;
    if (bVal === null) return -1;
    return (aVal - bVal) * sign;
  }

  const aValue = a[key] ?? "";
  const bValue = b[key] ?? "";
  const cmp = String(aValue).localeCompare(String(bValue));
  return cmp * sign;
}

export function sortInstrumentsMulti(
  rows: InstrumentSummary[],
  criteria: SortCriterion[]
): InstrumentSummary[] {
  if (!criteria || criteria.length === 0) return rows;
  return [...rows].sort((a, b) => {
    for (const { key, order } of criteria) {
      const diff = compareSingleKey(a, b, key, order);
      if (diff !== 0) return diff;
    }
    return a.symbol.localeCompare(b.symbol);
  });
}

// Client-side sort for whatever rows are currently displayed.
export function sortInstruments(
  rows: InstrumentSummary[],
  key: InstrumentSortKey,
  order: SortOrder
): InstrumentSummary[] {
  return sortInstrumentsMulti(rows, [{ key, order }]);
}
