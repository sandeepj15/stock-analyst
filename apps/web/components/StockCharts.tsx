"use client";

import { useEffect, useRef, useState } from "react";
import {
  ColorType,
  CrosshairMode,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type MouseEventParams,
  type Time,
  type UTCTimestamp,
  createChart,
} from "lightweight-charts";
import type { IndicatorSeries, PriceBar } from "../lib/types";
import { CHART_PALETTES, type ChartPalette } from "../lib/theme";
import { useTheme } from "../lib/useTheme";

interface Props {
  bars: PriceBar[];
  series: IndicatorSeries;
}

type OverlayKey = "ema_20" | "ema_50" | "ema_200";

function toTimestamp(dateStr: string): UTCTimestamp {
  return (new Date(`${dateStr}T00:00:00Z`).getTime() / 1000) as UTCTimestamp;
}

// `{ time: UTCTimestamp; value: number }` is a strict subtype of
// `LineData<Time>` (whose `time` is the broader `Time` union), so this
// predicate's narrowed type is assignable to its parameter type and
// satisfies TS's type-predicate-assignability check - unlike filtering
// straight into `LineData[]`, which isn't (`Time` is not assignable to
// `UTCTimestamp`).
interface NumericPoint {
  time: UTCTimestamp;
  value: number;
}

function toLineData(dates: string[], values: (number | null)[]): LineData[] {
  return dates
    .map((d, i) => ({ time: toTimestamp(d), value: values[i] }))
    .filter((p): p is NumericPoint => p.value !== null);
}

// Shared across all three panes so time-axis labels/price-scale widths
// line up exactly (lightweight-charts v4 has no native multi-pane chart -
// three separate chart instances kept in lockstep is the documented way
// to do this, see the task's own pointer to subscribeVisibleLogicalRangeChange).
const PRICE_SCALE_MIN_WIDTH = 64;

interface Instances {
  candleChart: IChartApi;
  rsiChart: IChartApi;
  macdChart: IChartApi;
  candleSeries: ISeriesApi<"Candlestick">;
  volumeSeries: ISeriesApi<"Histogram">;
  rsiSeries: ISeriesApi<"Line">;
  macdLine: ISeriesApi<"Line">;
  macdSignal: ISeriesApi<"Line">;
  macdHist: ISeriesApi<"Histogram">;
  emaSeries: Record<OverlayKey, ISeriesApi<"Line">>;
  volumeUpDown: boolean[]; // per-bar: true if that bar closed up vs. previous bar
  macdHistSign: (boolean | null)[]; // per-point: true if >= 0, null if no value
}

export default function StockCharts({ bars, series }: Props) {
  const [theme] = useTheme();
  const candleRef = useRef<HTMLDivElement | null>(null);
  const rsiRef = useRef<HTMLDivElement | null>(null);
  const macdRef = useRef<HTMLDivElement | null>(null);
  const instancesRef = useRef<Instances | null>(null);

  const [overlays, setOverlays] = useState<Record<OverlayKey, boolean>>({
    ema_20: true,
    ema_50: true,
    ema_200: false,
  });

  // --- Build (and tear down) all three chart instances together, wired
  // for synced pan/zoom + synced crosshair. Only re-runs when the
  // underlying data changes (e.g. the user picks a different date
  // range) - theme re-styling is handled by the separate effect below
  // without rebuilding anything.
  useEffect(() => {
    const candleEl = candleRef.current;
    const rsiEl = rsiRef.current;
    const macdEl = macdRef.current;
    if (!candleEl || !rsiEl || !macdEl || bars.length === 0) return;

    const palette = CHART_PALETTES[theme];

    const sharedOptions = (showTimeLabels: boolean) => ({
      layout: { background: { type: ColorType.Solid, color: palette.background }, textColor: palette.text },
      grid: { vertLines: { color: palette.grid }, horzLines: { color: palette.grid } },
      rightPriceScale: { borderColor: palette.border, minimumWidth: PRICE_SCALE_MIN_WIDTH },
      timeScale: { borderColor: palette.border, visible: showTimeLabels, timeVisible: false },
      crosshair: { mode: CrosshairMode.Normal },
    });

    const candleChart = createChart(candleEl, {
      width: candleEl.clientWidth,
      height: 380,
      ...sharedOptions(false),
    });
    const rsiChart = createChart(rsiEl, {
      width: rsiEl.clientWidth,
      height: 160,
      ...sharedOptions(false),
    });
    const macdChart = createChart(macdEl, {
      width: macdEl.clientWidth,
      height: 160,
      ...sharedOptions(true), // bottom-most pane: the only one with visible time-axis labels
    });

    const candleSeries = candleChart.addCandlestickSeries({
      upColor: palette.up,
      downColor: palette.down,
      borderVisible: false,
      wickUpColor: palette.up,
      wickDownColor: palette.down,
    });
    const candleData: CandlestickData[] = bars.map((b) => ({
      time: toTimestamp(b.date),
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
    }));
    candleSeries.setData(candleData);

    const volumeUpDown = bars.map((b, i) => i === 0 || b.close >= bars[i - 1].close);
    const volumeSeries = candleChart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "volume" });
    volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    volumeSeries.setData(
      bars.map((b, i) => ({
        time: toTimestamp(b.date),
        value: b.volume,
        color: volumeUpDown[i] ? palette.upVolume : palette.downVolume,
      }))
    );

    const emaColors: Record<OverlayKey, string> = {
      ema_20: palette.warn,
      ema_50: palette.accent,
      ema_200: palette.purple,
    };
    const emaSeries = {} as Record<OverlayKey, ISeriesApi<"Line">>;
    (["ema_20", "ema_50", "ema_200"] as const).forEach((key) => {
      const line = candleChart.addLineSeries({
        color: emaColors[key],
        lineWidth: 1,
        visible: overlays[key],
        lastValueVisible: false,
        priceLineVisible: false,
      });
      line.setData(toLineData(series.dates, series[key]));
      emaSeries[key] = line;
    });

    const rsiSeries = rsiChart.addLineSeries({ color: palette.warn, lineWidth: 2, priceLineVisible: false });
    const rsiLineData = toLineData(series.dates, series.rsi_14);
    rsiSeries.setData(rsiLineData);
    rsiSeries.createPriceLine({ price: 70, color: palette.down, lineWidth: 1, lineStyle: 2, title: "70" });
    rsiSeries.createPriceLine({ price: 30, color: palette.up, lineWidth: 1, lineStyle: 2, title: "30" });

    const macdHistSign = series.dates.map((_, i) => (series.macd_histogram[i] === null ? null : series.macd_histogram[i]! >= 0));
    const macdHist = macdChart.addHistogramSeries({ priceFormat: { type: "price", precision: 2 } });
    macdHist.setData(
      series.dates
        .map((d, i) => ({
          time: toTimestamp(d),
          value: series.macd_histogram[i],
          color: macdHistSign[i] ? palette.upVolume : palette.downVolume,
        }))
        .filter((p) => p.value !== null) as HistogramData[]
    );
    const macdLine = macdChart.addLineSeries({ color: palette.accent, lineWidth: 2, priceLineVisible: false });
    const macdLineData = toLineData(series.dates, series.macd_line);
    macdLine.setData(macdLineData);
    const macdSignal = macdChart.addLineSeries({ color: palette.warn, lineWidth: 2, priceLineVisible: false });
    macdSignal.setData(toLineData(series.dates, series.macd_signal));

    instancesRef.current = {
      candleChart,
      rsiChart,
      macdChart,
      candleSeries,
      volumeSeries,
      rsiSeries,
      macdLine,
      macdSignal,
      macdHist,
      emaSeries,
      volumeUpDown,
      macdHistSign,
    };

    // --- Sync #1: pan/zoom. Any one chart's visible range change is
    // mirrored onto the other two, guarded against the feedback loop
    // that setVisibleLogicalRange(...) would otherwise cause (setting
    // chart B's range fires chart B's own change handler, which would
    // try to set chart A's and chart C's range again, etc).
    const charts = [candleChart, rsiChart, macdChart];
    let syncingRange = false;
    charts.forEach((chart) => {
      chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
        if (!range || syncingRange) return;
        syncingRange = true;
        charts.forEach((other) => {
          if (other !== chart) other.timeScale().setVisibleLogicalRange(range);
        });
        syncingRange = false;
      });
    });

    // --- Sync #2: crosshair. Build a time -> value lookup per pane (its
    // own series' value at that timestamp) so the mirrored crosshair's
    // horizontal line sits at a meaningful position on each pane, not
    // just the vertical (time) line.
    const closeByTime = new Map<Time, number>(candleData.map((d) => [d.time, d.close]));
    const rsiByTime = new Map<Time, number>(rsiLineData.map((d) => [d.time, d.value as number]));
    const macdByTime = new Map<Time, number>(macdLineData.map((d) => [d.time, d.value as number]));

    const panes: { chart: IChartApi; series: ISeriesApi<any>; valueByTime: Map<Time, number> }[] = [
      { chart: candleChart, series: candleSeries, valueByTime: closeByTime },
      { chart: rsiChart, series: rsiSeries, valueByTime: rsiByTime },
      { chart: macdChart, series: macdLine, valueByTime: macdByTime },
    ];

    let syncingCrosshair = false;
    panes.forEach((pane) => {
      pane.chart.subscribeCrosshairMove((param: MouseEventParams) => {
        if (syncingCrosshair) return;
        syncingCrosshair = true;
        panes.forEach((other) => {
          if (other.chart === pane.chart) return;
          if (param.time !== undefined) {
            const value = other.valueByTime.get(param.time) ?? 0;
            other.chart.setCrosshairPosition(value, param.time, other.series);
          } else {
            other.chart.clearCrosshairPosition();
          }
        });
        syncingCrosshair = false;
      });
    });

    candleChart.timeScale().fitContent();

    const resizeObserver = new ResizeObserver(() => {
      candleChart.applyOptions({ width: candleEl.clientWidth });
      rsiChart.applyOptions({ width: rsiEl.clientWidth });
      macdChart.applyOptions({ width: macdEl.clientWidth });
    });
    resizeObserver.observe(candleEl);

    return () => {
      resizeObserver.disconnect();
      candleChart.remove();
      rsiChart.remove();
      macdChart.remove();
      instancesRef.current = null;
    };
    // Theme changes are handled by the effect below without rebuilding -
    // `theme`'s value at build time is captured once here intentionally.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bars, series]);

  // --- Re-theme live, in place, without tearing down/rebuilding the
  // charts (which would also reset the user's current zoom/pan/crosshair
  // state). Runs on every theme toggle.
  useEffect(() => {
    const inst = instancesRef.current;
    if (!inst) return;
    const palette: ChartPalette = CHART_PALETTES[theme];

    [inst.candleChart, inst.rsiChart, inst.macdChart].forEach((chart) => {
      chart.applyOptions({
        layout: { background: { type: ColorType.Solid, color: palette.background }, textColor: palette.text },
        grid: { vertLines: { color: palette.grid }, horzLines: { color: palette.grid } },
        rightPriceScale: { borderColor: palette.border },
        timeScale: { borderColor: palette.border },
      });
    });

    inst.candleSeries.applyOptions({
      upColor: palette.up,
      downColor: palette.down,
      wickUpColor: palette.up,
      wickDownColor: palette.down,
    });
    inst.volumeSeries.setData(
      inst.volumeSeries
        .data()
        .map((point, i) => ({ ...point, color: inst.volumeUpDown[i] ? palette.upVolume : palette.downVolume })) as HistogramData[]
    );

    inst.emaSeries.ema_20.applyOptions({ color: palette.warn });
    inst.emaSeries.ema_50.applyOptions({ color: palette.accent });
    inst.emaSeries.ema_200.applyOptions({ color: palette.purple });

    inst.rsiSeries.applyOptions({ color: palette.warn });
    inst.macdLine.applyOptions({ color: palette.accent });
    inst.macdSignal.applyOptions({ color: palette.warn });
    inst.macdHist.setData(
      inst.macdHist.data().map((point, i) => ({
        ...point,
        color: inst.macdHistSign[i] ? palette.upVolume : palette.downVolume,
      })) as HistogramData[]
    );
  }, [theme]);

  function toggleOverlay(key: OverlayKey) {
    setOverlays((prev) => {
      const next = { ...prev, [key]: !prev[key] };
      instancesRef.current?.emaSeries[key].applyOptions({ visible: next[key] });
      return next;
    });
  }

  const emaColorStyle = (key: OverlayKey) => {
    const palette = CHART_PALETTES[theme];
    return key === "ema_20" ? palette.warn : key === "ema_50" ? palette.accent : palette.purple;
  };

  return (
    <div>
      <div className="overlay-toggles">
        <label>
          <input type="checkbox" checked={overlays.ema_20} onChange={() => toggleOverlay("ema_20")} />
          <span style={{ color: emaColorStyle("ema_20") }}>EMA 20</span>
        </label>
        <label>
          <input type="checkbox" checked={overlays.ema_50} onChange={() => toggleOverlay("ema_50")} />
          <span style={{ color: emaColorStyle("ema_50") }}>EMA 50</span>
        </label>
        <label>
          <input type="checkbox" checked={overlays.ema_200} onChange={() => toggleOverlay("ema_200")} />
          <span style={{ color: emaColorStyle("ema_200") }}>EMA 200</span>
        </label>
      </div>
      <div className="chart-frame">
        <div className="chart-pane">
          <div ref={candleRef} className="chart-pane-container" />
        </div>
        <div className="chart-pane">
          <div className="chart-pane-label">RSI (14)</div>
          <div ref={rsiRef} className="chart-pane-container" />
        </div>
        <div className="chart-pane">
          <div className="chart-pane-label">
            MACD (12, 26, 9) — <span className="legend-macd">MACD</span> / <span className="legend-signal">Signal</span>
          </div>
          <div ref={macdRef} className="chart-pane-container" />
        </div>
      </div>
    </div>
  );
}
