"use client";

import { useEffect, useRef } from "react";
import { ColorType, createChart, HistogramSeries, LineSeries, type UTCTimestamp } from "lightweight-charts";
import type { LoadState, MacdPoint } from "@/types/trading";

export function MacdChart({ state }: { state: LoadState<MacdPoint[]> }) {
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (state.status !== "ready" || state.data.length === 0 || !rootRef.current) return;
    const root = rootRef.current;
    const chart = createChart(root, {
      width: root.clientWidth,
      height: root.clientHeight,
      layout: { background: { type: ColorType.Solid, color: "#080d16" }, textColor: "#65748b", fontFamily: "var(--font-mono)", fontSize: 10 },
      grid: { vertLines: { color: "rgba(109,128,155,.06)" }, horzLines: { color: "rgba(109,128,155,.06)" } },
      rightPriceScale: { borderColor: "#1b2636" },
      timeScale: { visible: false, borderColor: "#1b2636" },
      crosshair: { vertLine: { color: "rgba(126,149,181,.3)" }, horzLine: { color: "rgba(126,149,181,.3)" } },
    });
    const histogram = chart.addSeries(HistogramSeries, { priceFormat: { type: "price", precision: 5, minMove: 0.00001 }, priceLineVisible: false });
    const macdLine = chart.addSeries(LineSeries, { color: "#55a5ff", lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
    const signalLine = chart.addSeries(LineSeries, { color: "#e4af61", lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
    const time = (value: string) => Math.floor(new Date(value).getTime() / 1000) as UTCTimestamp;
    histogram.setData(state.data.filter((p) => p.histogram !== null).map((p) => ({ time: time(p.timestamp), value: p.histogram!, color: p.histogram! >= 0 ? "rgba(30,201,151,.72)" : "rgba(240,93,114,.72)" })));
    macdLine.setData(state.data.filter((p) => p.macd !== null).map((p) => ({ time: time(p.timestamp), value: p.macd! })));
    signalLine.setData(state.data.filter((p) => p.signal !== null).map((p) => ({ time: time(p.timestamp), value: p.signal! })));
    chart.timeScale().fitContent();
    const observer = new ResizeObserver(() => chart.applyOptions({ width: root.clientWidth, height: root.clientHeight }));
    observer.observe(root);
    return () => { observer.disconnect(); chart.remove(); };
  }, [state]);

  return (
    <section className="macd-panel">
      <div className="subchart-heading">
        <div><span>MACD</span><small>BACKEND CONFIG</small></div>
        <div className="macd-legend"><span className="macd-key blue">MACD</span><span className="macd-key gold">SIGNAL</span><span className="macd-key green">HISTOGRAM</span></div>
      </div>
      <div className="macd-chart" ref={rootRef}>
        {state.status === "loading" && <ChartMessage title="CALCULATING MACD" detail="Waiting for deterministic indicator output…" loading />}
        {state.status === "error" && <ChartMessage title="MACD UNAVAILABLE" detail={state.message} />}
        {state.status === "empty" && <ChartMessage title="NO MACD DATA" detail="No confirmed indicator values were returned." />}
      </div>
    </section>
  );
}

function ChartMessage({ title, detail, loading = false }: { title: string; detail: string; loading?: boolean }) {
  return <div className="chart-message">{loading && <span className="loader-ring" />}<strong>{title}</strong><span>{detail}</span></div>;
}
