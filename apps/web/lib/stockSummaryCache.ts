import type { InstrumentSummary } from "./types";

const summaryCache = new Map<string, InstrumentSummary>();

export function seedStockSummaries(summaries: InstrumentSummary[]): void {
  if (!Array.isArray(summaries)) return;
  for (let i = 0; i < summaries.length; i++) {
    const s = summaries[i];
    if (s?.symbol) {
      summaryCache.set(s.symbol.toUpperCase(), s);
    }
  }
}

/**
 * Cache an instrument summary in-memory and in sessionStorage so that
 * when the user clicks the stock, its header, identity, current price,
 * and key badges render instantaneously on the first frame (0ms)
 * without waiting for full API roundtrips.
 */
export function saveStockSummary(summary: InstrumentSummary): void {
  if (!summary?.symbol) return;
  const sym = summary.symbol.toUpperCase();
  summaryCache.set(sym, summary);
  if (typeof window !== "undefined") {
    try {
      sessionStorage.setItem(`stock_summary_${sym}`, JSON.stringify(summary));
    } catch {}
  }
}

/**
 * Retrieve cached summary for instant optimistic stock page rendering.
 */
export function getStockSummary(symbol: string): InstrumentSummary | null {
  if (!symbol) return null;
  const sym = symbol.toUpperCase();
  if (summaryCache.has(sym)) {
    return summaryCache.get(sym)!;
  }
  if (typeof window !== "undefined") {
    try {
      const saved = sessionStorage.getItem(`stock_summary_${sym}`);
      if (saved) {
        const parsed = JSON.parse(saved) as InstrumentSummary;
        summaryCache.set(sym, parsed);
        return parsed;
      }
    } catch {}
  }
  return null;
}
