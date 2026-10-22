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

  if (key === "fundamental_score") {
    if (a.fundamental_score === null && b.fundamental_score === null) return 0;
    if (a.fundamental_score === null) return 1;
    if (b.fundamental_score === null) return -1;
    return (a.fundamental_score - b.fundamental_score) * sign;
  }

  if (key === "is_multibagger") {
    if (a.is_multibagger === null && b.is_multibagger === null) return 0;
    if (a.is_multibagger === null) return 1;
    if (b.is_multibagger === null) return -1;
    return ((a.is_multibagger ? 1 : 0) - (b.is_multibagger ? 1 : 0)) * sign;
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
    if (a.momentum_pass !== b.momentum_pass) {
      return ((a.momentum_pass ? 1 : 0) - (b.momentum_pass ? 1 : 0)) * sign;
    }
    const aDist = a.distance_from_52w_high_pct ?? -999;
    const bDist = b.distance_from_52w_high_pct ?? -999;
    return (aDist - bDist) * sign;
  }

  if (key === "tv_momentum_flag") {
    const rankMap: Record<string, number> = {
      STRONG_BUY_BOTH: 6,
      STRONG_BUY_1D: 5,
      STRONG_BUY_1W: 4,
      STRONG_SELL_1W: -4,
      STRONG_SELL_1D: -5,
      STRONG_SELL_BOTH: -6,
    };
    const aRank = a.tv_momentum_flag ? (rankMap[a.tv_momentum_flag] ?? 0) : 0;
    const bRank = b.tv_momentum_flag ? (rankMap[b.tv_momentum_flag] ?? 0) : 0;
    if (aRank === 0 && bRank === 0) return 0;
    if (aRank === 0) return 1;
    if (bRank === 0) return -1;
    return (aRank - bRank) * sign;
  }

  if (key === "analyst_recommendation") {
    const rankMap: Record<string, number> = {
      STRONG_BUY: 4,
      strong_buy: 4,
      BUY: 3,
      buy: 3,
      SELL: 2,
      sell: 2,
      STRONG_SELL: 1,
      strong_sell: 1,
    };
    const aVal = a.analyst_recommendation ? (rankMap[a.analyst_recommendation] ?? -1) : -1;
    const bVal = b.analyst_recommendation ? (rankMap[b.analyst_recommendation] ?? -1) : -1;
    if (aVal === -1 && bVal === -1) return 0;
    if (aVal === -1) return 1;
    if (bVal === -1) return -1;
    return (aVal - bVal) * sign;
  }

  if (
    key === "distance_from_52w_high_pct" ||
    key === "analyst_upside_pct" ||
    key === "day_change_pct" ||
    key === "return_1w_pct" ||
    key === "return_1m_pct" ||
    key === "return_3m_pct" ||
    key === "return_6m_pct" ||
    key === "return_1y_pct" ||
    key === "revenue_growth_yoy" ||
    key === "pat_growth_yoy" ||
    key === "ml_forecast_5d_pct" ||
    key === "fii_current" ||
    key === "fii_change_qoq_pct"
  ) {
    const aVal = a[key];
    const bVal = b[key];
    const aNull = aVal === null || aVal === undefined;
    const bNull = bVal === null || bVal === undefined;
    if (aNull && bNull) return 0;
    if (aNull) return 1;
    if (bNull) return -1;
    return ((aVal as number) - (bVal as number)) * sign;
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
