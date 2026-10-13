"use client";

import { useEffect, useRef } from "react";
import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type MouseEventParams,
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
  type LifecycleMarkerProjection,
} from "@/lib/chart-view-model";
import type { AnalysisViewModel, Candle, SignalViewModel } from "@/types/trading";
import { acceptLabel, decisionEvidenceView, evidenceRecords, layerVisible, type EvidenceLayer, type EvidenceView, type LabelBox } from "@/lib/chart-evidence";
import { aggregateGeometry, densityCells, emptyDensity, groupGeometry, intersectsViewport, type EvidenceDensity, type EvidenceProjection } from "@/lib/chart-density";

interface PriceChartProps {
  candles: Candle[];
  analysis: AnalysisViewModel | null;
  signal: SignalViewModel | null;
  view?: EvidenceView;
  onInspect?: (keys: string[]) => void;
  onDensity?: (density: EvidenceDensity, projection: EvidenceProjection) => void;
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

const DEFAULT_VIEW = decisionEvidenceView();
export function PriceChart({ candles, analysis, signal, view = DEFAULT_VIEW, onInspect, onDensity }: PriceChartProps) {
  const chartRoot = useRef<HTMLDivElement>(null);
  const zoneLayer = useRef<HTMLDivElement>(null);
  const markerLayer = useRef<HTMLDivElement>(null);
  const currentView = useRef(view);
  const currentInspect = useRef(onInspect);
  const currentDensity = useRef(onDensity);
  useEffect(() => { currentDensity.current = onDensity; }, [onDensity]);
  const renderRef = useRef<(() => void) | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  useEffect(() => { currentView.current = view; currentInspect.current = onInspect; renderRef.current?.(); }, [view, onInspect]);
  useEffect(() => { chartRef.current?.timeScale().fitContent(); renderRef.current?.(); }, [view.reset]);

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
    chartRef.current = chart;
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

    const prepared = prepareEvidence(analysis, signal, candles);
    let markerApi: ISeriesMarkersPluginApi<Time> | undefined;
    let scheduledFrame: number | null = null;
    const scheduleRender = () => {
      if (scheduledFrame !== null) return;
      scheduledFrame = requestAnimationFrame(() => { scheduledFrame = null; renderZones(); });
    };
    let previousPriceAnchor: number | null = null;
    const renderZones = () => {
      const occupied: LabelBox[] = [];
      const context = renderContext(chart, series, root, prepared);
      previousPriceAnchor = series.priceToCoordinate(Number(candles[0].close));
      drawZoneOverlays(chart, series, zoneLayer.current, prepared, currentView.current, occupied, context, currentInspect.current);
      const markers = drawMarkers(chart, markerLayer.current, prepared, currentView.current, occupied, currentInspect.current, context);
      for (const node of zoneLayer.current?.children ?? []) {
        const element = node as HTMLDivElement;
        const box = { x: parseFloat(element.style.left) + 5, y: parseFloat(element.style.top) + 3, width: 88, height: 16 };
        if (element.dataset.secondaryLabel && acceptLabel(box, occupied, root.clientWidth - 60, root.clientHeight - 28)) element.dataset.label = element.dataset.secondaryLabel;
      }
      if (markerApi) markerApi.setMarkers(markers);
      // Cluster representatives must not feed back into candle autoscale / viewport membership.
      else markerApi = currentView.current.preset ? createSeriesMarkers(series, markers, { autoScale: false }) : createSeriesMarkers(series, markers);
      currentDensity.current?.(summarizeDensity(prepared, context), context);
    };
    renderRef.current = renderZones;
    chart.timeScale().fitContent();
    const frame = requestAnimationFrame(renderZones);
    chart.timeScale().subscribeVisibleLogicalRangeChange(scheduleRender);
    const inspectZone = (event: MouseEventParams<Time>) => {
      if (previousPriceAnchor !== series.priceToCoordinate(Number(candles[0].close))) scheduleRender();
      if (!event.point || !zoneLayer.current) return;
      const { x, y } = event.point;
      const hitZone = (trade: boolean) => {
      for (const node of zoneLayer.current!.children) {
        const element = node as HTMLDivElement;
        if (["entry", "tp", "sl"].some((kind) => element.classList.contains(kind)) !== trade) continue;
        const left = parseFloat(element.style.left), top = parseFloat(element.style.top);
        if (x >= left && x <= left + parseFloat(element.style.width) && y >= top - 5 && y <= top + parseFloat(element.style.height) + 5 && element.dataset.evidenceKeys) {
          currentInspect.current?.(element.dataset.evidenceKeys.split(","));
          return true;
        }
      }
      return false;
      };
      if (hitZone(true)) return;
      for (const node of markerLayer.current?.children ?? []) {
        const element = node as HTMLButtonElement;
        const left = parseFloat(element.style.left), top = parseFloat(element.style.top);
        const width = element.dataset.textVisible === "true" ? 82 : 22;
        if (x >= left && x <= left + width && y >= top && y <= top + 22 && element.dataset.evidenceKeys) {
          currentInspect.current?.(element.dataset.evidenceKeys.split(","));
          return;
        }
      }
      hitZone(false);
    };
    chart.subscribeClick?.(inspectZone);
    chart.subscribeCrosshairMove?.(inspectZone);
    root.addEventListener("wheel", scheduleRender, { passive: true });
    const dragMove = () => scheduleRender();
    const dragEnd = () => { scheduleRender(); document.removeEventListener("pointermove", dragMove); document.removeEventListener("pointerup", dragEnd); document.removeEventListener("pointercancel", dragEnd); };
    const dragStart = () => { document.addEventListener("pointermove", dragMove, { passive: true }); document.addEventListener("pointerup", dragEnd); document.addEventListener("pointercancel", dragEnd); };
    root.addEventListener("pointerdown", dragStart);

    const observer = new ResizeObserver(() => {
      chart.applyOptions({ width: root.clientWidth, height: root.clientHeight });
      renderZones();
    });
    observer.observe(root);
    return () => {
      cancelAnimationFrame(frame);
      if (scheduledFrame !== null) cancelAnimationFrame(scheduledFrame);
      renderRef.current = null;
      chartRef.current = null;
      observer.disconnect();
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(scheduleRender);
      root.removeEventListener("wheel", scheduleRender);
      root.removeEventListener("pointerdown", dragStart);
      document.removeEventListener("pointermove", dragMove); document.removeEventListener("pointerup", dragEnd); document.removeEventListener("pointercancel", dragEnd);
      chart.unsubscribeClick?.(inspectZone);
      chart.unsubscribeCrosshairMove?.(inspectZone);
      chart.remove();
    };
  }, [candles, analysis, signal]);

  return (
    <div className="chart-canvas-wrap">
      <div className="chart-canvas" ref={chartRoot} />
      <div className="zone-layer" ref={zoneLayer} aria-label="Projected evidence zones" />
      <div className="marker-detail-layer" ref={markerLayer} />
    </div>
  );
}

interface PreparedMarker extends LifecycleMarkerProjection { layer: EvidenceLayer; key: string; price: number }
interface PreparedZone { from: UTCTimestamp; to: UTCTimestamp; lower: number; upper: number; kind: string; category: EvidenceLayer; direction: "bullish" | "bearish"; terminal: boolean; key: string }
function prepareEvidence(analysis: AnalysisViewModel | null, signal: SignalViewModel | null, candles: Candle[]) {
  const rows = evidenceRecords(analysis, signal);
  const keys = new Map(rows.map(row => [row.detail, row.key]));
  const bars = new Map(candles.map(candle => [unixTime(candle.timestamp), candle]));
  const markers: PreparedMarker[] = [];
  const addMarker = (marker: LifecycleMarkerProjection, layer: EvidenceLayer, key: string) => {
    // Exact original timestamp only: coarse displays must never backdate/snap evidence.
    const bar = bars.get(unixTime(marker.at));
    if (bar) markers.push({ ...marker, layer, key, price: Number(marker.position === "aboveBar" ? bar.high : bar.low) });
  };
  projectSwingMarkers(analysis?.swings ?? []).forEach((marker, index) => addMarker(marker, "swing", keys.get(analysis!.swings[Math.floor(index / 2)])!));
  projectStructureMarkers(analysis?.structures ?? []).forEach((marker, index) => addMarker(marker, analysis!.structures[index].type.toLowerCase() as EvidenceLayer, keys.get(analysis!.structures[index])!));
  const zones: PreparedZone[] = [];
  const end = unixTime(candles[candles.length - 1].timestamp);
  const add = (from: string, to: UTCTimestamp, lower: number, upper: number, kind: string, category: EvidenceLayer, direction: "bullish" | "bearish", terminal: boolean, key: string) => zones.push({ from: unixTime(from), to, lower, upper, kind, category, direction, terminal, key });
  if (signal && signal.finalDecision !== "NO_TRADE" && signal.entryMin !== null && signal.entryMax !== null) {
    const from = signalAvailabilityStart(signal), direction = signal.finalDecision === "LONG" ? "bullish" : "bearish";
    add(from, end, signal.entryMin, signal.entryMax, "ENTRY", "entry", direction, false, rows.find(row => row.layer === "entry")!.key);
    if (signal.takeProfit !== null) add(from, end, signal.takeProfit, signal.takeProfit, "TP", "tp", direction, false, rows.find(row => row.layer === "tp")!.key);
    if (signal.stopLoss !== null) add(from, end, signal.stopLoss, signal.stopLoss, "SL", "sl", direction, false, rows.find(row => row.layer === "sl")!.key);
  }
  for (const level of analysis?.supports ?? []) add(levelAvailabilityStart(level), end, level.lower, level.upper, "SUPPORT", "support", "bullish", false, keys.get(level)!);
  for (const level of analysis?.resistances ?? []) add(levelAvailabilityStart(level), end, level.lower, level.upper, "RESISTANCE", "resistance", "bearish", false, keys.get(level)!);
  for (const projection of projectZoneWindows(analysis?.zones ?? [], candles[candles.length - 1].timestamp)) {
    const zone = projection.zone;
    add(projection.from, unixTime(projection.to), zone.lower, zone.upper, `${zone.kind} ${zone.status}`, zone.kind === "FVG" ? "fvg" : "ob", zone.direction, projection.terminal, keys.get(zone)!);
  }
  return { rows, markers, zones, bars, sources: new Set(rows.map(row => row.key)) };
}
type PreparedEvidence = ReturnType<typeof prepareEvidence>;
function renderContext(chart: IChartApi, series: ISeriesApi<"Candlestick">, root: HTMLDivElement, prepared: PreparedEvidence) {
  const scale = chart.timeScale();
  const realViewport = typeof scale.getVisibleLogicalRange === "function";
  const width = Math.max(1, root.clientWidth - (realViewport ? chart.priceScale("right").width() : 60));
  const height = Math.max(1, root.clientHeight - (realViewport ? scale.height() : 28));
  const range = scale.getVisibleLogicalRange?.();
  const cells = densityCells(width, height, range ? range.to - range.from : prepared.bars.size);
  const xCache = new Map<number, number | null>(), yCache = new Map<number, number | null>();
  const x = (time: UTCTimestamp) => {
    if (!xCache.has(time)) xCache.set(time, realViewport && !prepared.bars.has(time) ? null : scale.timeToCoordinate(time));
    return xCache.get(time)!;
  };
  const y = (price: number) => { if (!yCache.has(price)) yCache.set(price, series.priceToCoordinate(price)); return yCache.get(price)!; };
  return { realViewport, width, height, cells, x, y, sources: prepared.sources, projectable: new Set<string>(), viewport: new Set<string>(), rendered: new Set<string>(), density: emptyDensity() };
}
type RenderContext = ReturnType<typeof renderContext>;
function summarizeDensity(prepared: PreparedEvidence, context: RenderContext): EvidenceDensity {
  for (const row of prepared.rows) {
    const count = context.density[row.layer]; count.source++;
    if (!context.projectable.has(row.key)) count.unavailable++;
    else if (!context.viewport.has(row.key)) count.offscreen++;
    if (context.viewport.has(row.key)) count.viewport++;
    if (context.rendered.has(row.key)) count.renderedSource++;
  }
  return context.density;
}
function drawMarkers(chart: IChartApi, layer: HTMLDivElement | null, prepared: PreparedEvidence, view: EvidenceView, occupied: LabelBox[], inspect: ((keys: string[]) => void) | undefined, context: RenderContext): SeriesMarker<Time>[] {
  layer?.replaceChildren();
  const candidates: (PreparedMarker & { x: number; y: number })[] = [];
  const fallback: SeriesMarker<Time>[] = [];
  for (const marker of prepared.markers) {
    const x = context.x(unixTime(marker.at)), coordinate = context.y(marker.price);
    if (x === null || coordinate === null || !Number.isFinite(x) || !Number.isFinite(coordinate)) {
      // Legacy coordinate adapter retains its original exact-timestamp assertion behavior.
      if (!context.realViewport && layerVisible(marker.layer, view)) fallback.push({ time: unixTime(marker.at), position: marker.position, color: marker.color, shape: marker.shape, text: "" });
      continue;
    }
    context.projectable.add(marker.key);
    if (context.realViewport && !intersectsViewport(x, x, coordinate, coordinate, context.width, context.height)) continue;
    context.viewport.add(marker.key);
    if (!layerVisible(marker.layer, view)) continue;
    candidates.push({ ...marker, x, y: coordinate + (marker.position === "aboveBar" ? -18 : 10) });
  }
  const groups = view.preset ? aggregateGeometry(candidates, (marker, scale) => `${marker.layer}:${Math.floor(Math.max(0, marker.x) / (context.cells.markerX * scale))}:${Math.floor(Math.max(0, marker.y) / (context.cells.markerY * scale))}`, context.cells.markerBudget) : groupGeometry(candidates, marker => `${marker.layer}:${Math.floor(marker.x / 28)}:${Math.floor(marker.y / 24)}`);
  const result = [...fallback];
  const labelBudget = layer ? Math.max(4, Math.floor(context.width / 130) * Math.floor(context.height / 95)) : 0;
  let textCount = 0;
  const bos = groups.filter(group => group[0].layer === "bos"), mss = groups.filter(group => group[0].layer === "mss");
  const prioritized = Array.from({ length: Math.max(bos.length, mss.length) }, (_, index) => [mss[index], bos[index]].filter(Boolean)).flat().concat(groups.filter(group => group[0].layer === "swing"));
  for (const members of prioritized) {
    // Pick an existing member nearest the screen group's centre, never a fabricated time/price.
    const centreX = (Math.min(...members.map(member => member.x)) + Math.max(...members.map(member => member.x))) / 2;
    const centreY = (Math.min(...members.map(member => member.y)) + Math.max(...members.map(member => member.y))) / 2;
    const first = members.reduce((best, member) => Math.hypot(member.x - centreX, member.y - centreY) < Math.hypot(best.x - centreX, best.y - centreY) ? member : best);
    const ids = [...new Set([first.key, ...members.map(member => member.key)])];
    result.push({ time: unixTime(first.at), position: first.position, color: first.color, shape: first.shape, text: "" });
    ids.forEach(key => context.rendered.add(key));
    context.density[first.layer].visuals++; if (ids.length > 1) context.density[first.layer].clusters++;
    if (!layer) continue;
    const button = document.createElement("button");
    button.type = "button";
    button.className = `evidence-marker ${first.layer}${ids.length > 1 ? " cluster" : ""}`;
    button.style.left = `${Math.max(0, Math.min(first.x - 10, context.width - 82))}px`;
    button.style.top = `${Math.max(0, Math.min(first.y, context.height - 24))}px`;
    button.style.color = first.color;
    button.dataset.evidenceMembers = String(ids.length); button.dataset.evidenceKeys = ids.join(","); button.dataset.markerLayer = first.layer;
    button.dataset.representativeAt = first.at;
    button.dataset.projectionAvailability = "EXACT_TIMESTAMP_VIEWPORT";
    button.title = `Original visual representative; all ${ids.length} source items available\n${members.map(member => `${member.id} · ${member.label} · ${member.at} · ${member.availability}`).join("\n")}`;
    button.setAttribute("aria-label", `Inspect ${first.layer} · ${ids.length} evidence items`);
    const box = { x: parseFloat(button.style.left), y: parseFloat(button.style.top), width: 82, height: 22 };
    const showText = textCount < labelBudget && view.labels[first.layer] && acceptLabel(box, occupied, context.width, context.height);
    if (showText) textCount++;
    button.textContent = showText ? `${first.layer === "swing" ? first.label : first.layer.toUpperCase()}${ids.length > 1 ? ` ×${ids.length}` : ""}` : "•";
    button.dataset.textVisible = String(showText);
    const select = () => inspect?.(ids); button.onclick = select; button.onmouseenter = select; button.onfocus = select;
    layer.appendChild(button);
  }
  return result.sort((a, b) => Number(a.time) - Number(b.time));
}
function drawZoneOverlays(chart: IChartApi, series: ISeriesApi<"Candlestick">, layer: HTMLDivElement | null, prepared: PreparedEvidence, view: EvidenceView, occupied: LabelBox[], context: RenderContext, inspect?: (keys: string[]) => void) {
  if (!layer) return;
  layer.replaceChildren();
  const candidates: (PreparedZone & { x1: number; x2: number; y1: number; y2: number })[] = [];
  for (const zone of prepared.zones) {
    const x1 = context.x(zone.from), x2 = context.x(zone.to);
    if (x1 === null || x2 === null) continue;
    const y1 = context.y(zone.upper), y2 = context.y(zone.lower);
    if (y1 === null || y2 === null || ![x1,x2,y1,y2].every(Number.isFinite)) continue;
    context.projectable.add(zone.key);
    if (context.realViewport && !intersectsViewport(x1,x2,y1,y2,context.width,context.height)) continue;
    context.viewport.add(zone.key);
    if (!layerVisible(zone.category, view)) continue;
    candidates.push({ ...zone, x1,x2,y1,y2 });
  }
  const trade = (zone: PreparedZone) => ["entry", "tp", "sl"].includes(zone.category);
  const groups = !view.preset ? candidates.map(zone => [zone]) : [
    ...candidates.filter(trade).map(zone => [zone]),
    ...aggregateGeometry(candidates.filter(zone => !trade(zone)), (zone, scale) => {
      // Clip only the grouping coordinates. Original representative geometry below is untouched.
      const x1 = Math.max(0, Math.min(context.width, zone.x1)), x2 = Math.max(0, Math.min(context.width, zone.x2));
      const y1 = Math.max(0, Math.min(context.height, zone.y1)), y2 = Math.max(0, Math.min(context.height, zone.y2));
      if (["support", "resistance"].includes(zone.category)) return `${zone.category}:${Math.floor((y1 + y2) / 2 / (context.cells.referenceY * scale))}`;
      return `${zone.category}:${zone.direction}:${zone.terminal}:${Math.floor(x1 / (context.cells.zoneX * scale))}:${Math.floor(x2 / (context.cells.zoneX * scale))}:${Math.floor(y1 / (context.cells.zoneY * scale))}:${Math.floor(y2 / (context.cells.zoneY * scale))}`;
    }, context.cells.zoneBudget),
  ];
  for (const members of groups) {
    const first = members[0], ids = members.map(member => member.key);
    // Draw only an original member, with its unchanged horizontal geometry and terminal endpoint.
    const element = appendZone(layer, chart, series, first.from, first.to, first.lower, first.upper, first.kind, first.direction, first.terminal, view.labels[first.category], occupied, first.key);
    if (!element) continue;
    ids.forEach(key => context.rendered.add(key)); context.density[first.category].visuals++;
    if (ids.length > 1) { context.density[first.category].clusters++; element.classList.add("geometry-cluster"); if (view.labels[first.category]) element.dataset.secondaryLabel = `${first.kind.split(" ")[0].replace("_", " ")} ×${ids.length}`; }
    element.dataset.evidenceKeys = ids.join(","); element.dataset.evidenceMembers = String(ids.length);
    element.dataset.projectionAvailability = "ORIGINAL_WINDOW_VIEWPORT";
    element.title = `${ids.length > 1 ? "Visual representative of original geometry; no new strategy price. " : ""}${members.map(member => `${member.key} · prices ${member.lower}–${member.upper} · ${new Date(Number(member.from) * 1000).toISOString()} → ${new Date(Number(member.to) * 1000).toISOString()} · ${member.terminal ? "terminal" : "active"}`).join("\n")}`;
    element.tabIndex = 0; element.setAttribute("role", "button"); element.setAttribute("aria-label", `Inspect ${first.category} · ${ids.length} evidence items · original visual representative`);
    element.onfocus = () => inspect?.(ids); element.onkeydown = event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); inspect?.(ids); } };
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
  labels = true,
  occupied: LabelBox[] = [],
  evidenceKey?: string,
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
  const trade = ["ENTRY", "TP", "SL"].includes(kind);
  const box = { x: horizontal.left + 5, y: Math.min(y1, y2) + 3, width: trade ? 44 : 88, height: 16 };
  if (labels && trade) {
    element.dataset.label = kind.replace("_", " ");
    occupied.push(box);
  } else if (labels) element.dataset.secondaryLabel = kind.replace("_", " ");
  element.title = `${kind} · ${lower}–${upper} · ${new Date(Number(from) * 1000).toISOString()} → ${new Date(Number(to) * 1000).toISOString()}`;
  element.dataset.projectionFrom = String(from); element.dataset.projectionTo = String(to);
  element.dataset.sourceLower = String(lower); element.dataset.sourceUpper = String(upper);
  element.dataset.terminal = String(terminal);
  if (evidenceKey) element.dataset.evidenceKey = evidenceKey;
  layer.appendChild(element);
  return element;
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
