"use client";

import { useEffect, useRef, useState } from "react";
import { ColorType, type IChartApi, type ISeriesApi, type LineData, type UTCTimestamp, createChart } from "lightweight-charts";
import { getPrice } from "../lib/api";
import { CHART_PALETTES } from "../lib/theme";
import { useTheme } from "../lib/useTheme";
import MarketRegimeBadge from "./MarketRegimeBadge";
import type { MarketRegimeResponse } from "../lib/types";

const BENCHMARK_SYMBOL = "NIFTY50";
type TimeRange = "1M" | "3M" | "6M" | "1Y";
const TIME_RANGES: TimeRange[] = ["1M", "3M", "6M", "1Y"];

function toTimestamp(dateStr: string): UTCTimestamp {
  return (new Date(`${dateStr}T00:00:00Z`).getTime() / 1000) as UTCTimestamp;
}

export default function NiftyMiniChart({ regime }: { regime: MarketRegimeResponse | null }) {
  const [theme] = useTheme();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Area"> | null>(null);
  
  const [error, setError] = useState<string | null>(null);
  const [latestClose, setLatestClose] = useState<number | null>(null);
  const [changePct, setChangePct] = useState<number | null>(null);
  const [timeRange, setTimeRange] = useState<TimeRange>("3M");

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const palette = CHART_PALETTES[theme];

    const chart = createChart(el, {
      width: el.clientWidth,
      height: 140,
      layout: { background: { type: ColorType.Solid, color: palette.background }, textColor: palette.text },
      grid: { vertLines: { visible: false }, horzLines: { color: palette.grid } },
      rightPriceScale: { borderColor: palette.border, minimumWidth: 56 },
      timeScale: { borderColor: palette.border, timeVisible: false },
      handleScroll: false,
      handleScale: false,
    });
    const series = chart.addAreaSeries({
      lineColor: palette.accent,
      topColor: `${palette.accent}33`,
      bottomColor: `${palette.accent}00`,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
    });
    chartRef.current = chart;
    seriesRef.current = series;

    const resizeObserver = new ResizeObserver(() => chart.applyOptions({ width: el.clientWidth }));
    resizeObserver.observe(el);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Only run once on mount

  // Handle data fetching when timeRange changes
  useEffect(() => {
    let cancelled = false;
    getPrice(BENCHMARK_SYMBOL, timeRange)
      .then((price) => {
        if (cancelled) return;
        const series = seriesRef.current;
        const chart = chartRef.current;
        if (!series || !chart) return;
        
        const data: LineData[] = price.bars.map((b) => ({ time: toTimestamp(b.date), value: b.close }));
        series.setData(data);
        chart.timeScale().fitContent();
        
        if (price.bars.length > 0) {
          const latest = price.bars[price.bars.length - 1];
          const first = price.bars[0];
          setLatestClose(latest.close);
          setChangePct(((latest.close - first.close) / first.close) * 100);
        } else {
          setLatestClose(null);
          setChangePct(null);
        }
        setError(null);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load Nifty price history.");
      });

    return () => {
      cancelled = true;
    };
  }, [timeRange]);

  useEffect(() => {
    const chart = chartRef.current;
    const series = seriesRef.current;
    if (!chart || !series) return;
    const palette = CHART_PALETTES[theme];
    chart.applyOptions({
      layout: { background: { type: ColorType.Solid, color: palette.background }, textColor: palette.text },
      grid: { vertLines: { visible: false }, horzLines: { color: palette.grid } },
      rightPriceScale: { borderColor: palette.border },
      timeScale: { borderColor: palette.border },
    });
    series.applyOptions({ lineColor: palette.accent, topColor: `${palette.accent}33`, bottomColor: `${palette.accent}00` });
  }, [theme]);

  return (
    <div className="pulse-card nifty-mini-card">
      <div className="pulse-card-head">
        <div>
          <h3>NIFTY 50</h3>
          {latestClose !== null && (
            <span className="nifty-mini-price num">
              {latestClose.toFixed(2)}
              {changePct !== null && (
                <span className={changePct >= 0 ? "day-change up" : "day-change down"}>
                  {" "}
                  {changePct >= 0 ? "+" : ""}
                  {changePct.toFixed(2)}% ({timeRange})
                </span>
              )}
            </span>
          )}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '8px' }}>
          <MarketRegimeBadge regime={regime} />
          <div className="range-selector" style={{ margin: 0 }}>
            {TIME_RANGES.map((r) => (
              <button
                key={r}
                className={timeRange === r ? "active" : ""}
                onClick={() => setTimeRange(r)}
                style={{ padding: '2px 6px', fontSize: '11px', minWidth: 'auto', marginLeft: '4px' }}
              >
                {r}
              </button>
            ))}
          </div>
        </div>
      </div>
      {error && <div className="notice error">{error}</div>}
      <div ref={containerRef} className="nifty-mini-chart" />
    </div>
  );
}

