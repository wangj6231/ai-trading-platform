"use client";

import { useEffect, useRef } from "react";
import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import {
  levelAvailabilityStart,
  projectZoneWindows,
  projectStructureMarkers,
  projectSwingMarkers,
  signalAvailabilityStart,
} from "@/lib/chart-view-model";
import type { AnalysisViewModel, Candle, SignalViewModel } from "@/types/trading";

interface PriceChartProps {
  candles: Candle[];
  analysis: AnalysisViewModel | null;
  signal: SignalViewModel | null;
}

const MIN_LIVE_ZONE_WIDTH_PX = 18;
const LIVE_ZONE_EXTENSION_PX = 44;

interface ZoneHorizontalGeometry {
  left: number;
  width: number;
}

function unixTime(timestamp: string): UTCTimestamp {
  return Math.floor(new Date(timestamp).getTime() / 1000) as UTCTimestamp;
}

export function PriceChart({ candles, analysis, signal }: PriceChartProps) {
  const chartRoot = useRef<HTMLDivElement>(null);
  const zoneLayer = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!chartRoot.current || candles.length === 0) return;
    const root = chartRoot.current;
    const chart = createChart(root, {
      width: root.clientWidth,
      height: root.clientHeight,
      layout: {
        background: { type: ColorType.Solid, color: "#080d16" },
        textColor: "#6f7d92",
        fontFamily: "var(--font-mono)",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "rgba(109, 128, 155, 0.075)" },
        horzLines: { color: "rgba(109, 128, 155, 0.075)" },
      },
      rightPriceScale: { borderColor: "#1b2636", scaleMargins: { top: 0.08, bottom: 0.08 } },
      timeScale: { borderColor: "#1b2636", timeVisible: true, secondsVisible: false, rightOffset: 8 },
      crosshair: {
        vertLine: { color: "rgba(126, 149, 181, .38)", labelBackgroundColor: "#243149" },
        horzLine: { color: "rgba(126, 149, 181, .38)", labelBackgroundColor: "#243149" },
      },
      handleScroll: true,
      handleScale: true,
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#1ec997",
      downColor: "#f05d72",
      wickUpColor: "#47d6aa",
      wickDownColor: "#f27b8d",
      borderVisible: false,
      priceLineVisible: false,
      lastValueVisible: true,
    });
    series.setData(candles.map((candle) => ({
      time: unixTime(candle.timestamp),
      open: Number(candle.open),
      high: Number(candle.high),
      low: Number(candle.low),
      close: Number(candle.close),
    })));

    addMarkers(series, analysis);

    const renderZones = () => drawZoneOverlays(chart, series, zoneLayer.current, candles, analysis, signal);
    chart.timeScale().fitContent();
    requestAnimationFrame(renderZones);
    chart.timeScale().subscribeVisibleLogicalRangeChange(renderZones);

    const observer = new ResizeObserver(() => {
      chart.applyOptions({ width: root.clientWidth, height: root.clientHeight });
      renderZones();
    });
    observer.observe(root);
    return () => {
      observer.disconnect();
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(renderZones);
      chart.remove();
    };
  }, [candles, analysis, signal]);

  return (
    <div className="chart-canvas-wrap">
      <div className="chart-canvas" ref={chartRoot} />
      <div className="zone-layer" ref={zoneLayer} aria-hidden="true" />
    </div>
  );
}

function addMarkers(series: ISeriesApi<"Candlestick">, analysis: AnalysisViewModel | null) {
  if (!analysis) return;
  const markers: SeriesMarker<Time>[] = [
    ...projectSwingMarkers(analysis.swings),
    ...projectStructureMarkers(analysis.structures),
  ]
    .map((marker): SeriesMarker<Time> => ({
      time: unixTime(marker.at),
      position: marker.position,
      color: marker.color,
      shape: marker.shape,
      text: marker.label,
    }))
    .sort((a, b) => Number(a.time) - Number(b.time));
  createSeriesMarkers(series, markers);
}

function drawZoneOverlays(
  chart: IChartApi,
  series: ISeriesApi<"Candlestick">,
  layer: HTMLDivElement | null,
  candles: Candle[],
  analysis: AnalysisViewModel | null,
  signal: SignalViewModel | null,
) {
  if (!layer) return;
  layer.replaceChildren();
  const lastTime = unixTime(candles[candles.length - 1].timestamp);
  for (const level of analysis?.supports ?? []) {
    appendZone(
      layer,
      chart,
      series,
      unixTime(levelAvailabilityStart(level)),
      lastTime,
      level.lower,
      level.upper,
      "SUPPORT",
      "bullish",
    );
  }
  for (const level of analysis?.resistances ?? []) {
    appendZone(
      layer,
      chart,
      series,
      unixTime(levelAvailabilityStart(level)),
      lastTime,
      level.lower,
      level.upper,
      "RESISTANCE",
      "bearish",
    );
  }
  for (const projection of projectZoneWindows(
    analysis?.zones ?? [],
    candles[candles.length - 1].timestamp,
  )) {
    const { zone } = projection;
    appendZone(
      layer,
      chart,
      series,
      unixTime(projection.from),
      unixTime(projection.to),
      zone.lower,
      zone.upper,
      `${zone.kind} ${zone.status}`,
      zone.direction,
      projection.terminal,
    );
  }
  if (signal && signal.finalDecision !== "NO_TRADE" && signal.entryMin !== null && signal.entryMax !== null) {
    const availableAt = unixTime(signalAvailabilityStart(signal));
    const direction = signal.finalDecision === "LONG" ? "bullish" : "bearish";
    appendZone(layer, chart, series, availableAt, lastTime, signal.entryMin, signal.entryMax, "ENTRY", direction);
    if (signal.takeProfit !== null) {
      appendZone(layer, chart, series, availableAt, lastTime, signal.takeProfit, signal.takeProfit, "TP", direction);
    }
    if (signal.stopLoss !== null) {
      appendZone(layer, chart, series, availableAt, lastTime, signal.stopLoss, signal.stopLoss, "SL", direction);
    }
  }
}

function appendZone(
  layer: HTMLDivElement,
  chart: IChartApi,
  series: ISeriesApi<"Candlestick">,
  from: UTCTimestamp,
  to: UTCTimestamp,
  lower: number,
  upper: number,
  kind: string,
  direction: "bullish" | "bearish",
  terminal = false,
) {
  const x1 = chart.timeScale().timeToCoordinate(from);
  const x2 = chart.timeScale().timeToCoordinate(to);
  const y1 = series.priceToCoordinate(upper);
  const y2 = series.priceToCoordinate(lower);
  if (
    x1 === null ||
    x2 === null ||
    y1 === null ||
    y2 === null ||
    ![x1, x2, y1, y2].every(Number.isFinite)
  ) return;
  const horizontal = zoneHorizontalGeometry(x1, x2, terminal);
  if (horizontal === null) return;
  const element = document.createElement("div");
  const slug = kind.split(" ", 1)[0].toLowerCase().replace("_", "-");
  element.className = `chart-zone ${slug} ${direction}${terminal ? " terminal" : ""}`;
  element.style.left = `${horizontal.left}px`;
  element.style.width = `${horizontal.width}px`;
  element.style.top = `${Math.min(y1, y2)}px`;
  element.style.height = `${Math.max(3, Math.abs(y2 - y1))}px`;
  element.dataset.label = kind.replace("_", " ");
  layer.appendChild(element);
}

function zoneHorizontalGeometry(
  startX: number,
  endX: number,
  terminal: boolean,
): ZoneHorizontalGeometry | null {
  if (terminal) {
    if (endX < 0 || endX < startX) return null;
    const left = Math.max(0, startX);
    return { left, width: endX - left };
  }
  return {
    left: Math.max(0, startX),
    width: Math.max(
      MIN_LIVE_ZONE_WIDTH_PX,
      endX - startX + LIVE_ZONE_EXTENSION_PX,
    ),
  };
}
