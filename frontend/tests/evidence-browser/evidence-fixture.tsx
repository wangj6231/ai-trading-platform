// Explicit isolated presentation fixture. Real chart library/components/CSS; no strategy evaluation.
import { useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { PriceChart } from "@/components/price-chart";
import { ChartEvidenceControls } from "@/components/chart-evidence-controls";
import { ChartEvidenceInspector } from "@/components/chart-evidence-inspector";
import { cleanEvidenceView, evidenceCounts, evidenceRecords } from "@/lib/chart-evidence";
import { normalizeAnalysis } from "@/lib/api";
import type { AnalysisViewModel, Candle, SignalViewModel, ZoneOverlay } from "@/types/trading";
import "@/app/globals.css";

const base = Date.parse("2025-01-01T00:00:00Z");
const stamp = (index: number) => new Date(base + index * 900_000).toISOString();
const allCandles: Candle[] = Array.from({ length: 500 }, (_, index) => { const price = 100 + Math.sin(index / 15) * 6; return { timestamp: stamp(index), open: String(price), close: String(price + .5), high: String(price + 2), low: String(price - 2), volume: "1" }; });
const hourlyCandles: Candle[] = Array.from({ length: 125 }, (_, index) => { const group = allCandles.slice(index * 4, index * 4 + 4); return { timestamp: group[0].timestamp, open: group[0].open, high: String(Math.max(...group.map((candle) => Number(candle.high)))), low: String(Math.min(...group.map((candle) => Number(candle.low)))), close: group[3].close, volume: "4" }; });
const analysis: AnalysisViewModel = {
  supports: [{ id: "original-support", lower: 96, upper: 97, anchorPrice: 97, label: "SUPPORT", createdAt: stamp(100), confirmedAt: null }],
  resistances: [{ id: "original-resistance", lower: 105, upper: 106, anchorPrice: 105, label: "RESISTANCE", createdAt: stamp(100), confirmedAt: null }],
  swings: Array.from({ length: 900 }, (_, index) => ({ id: `original-swing-${index}`, kind: index % 2 ? "LOW" : "HIGH", pivotAt: stamp(Math.floor(index / 2)), confirmedAt: stamp(Math.floor(index / 2) + 2), price: index % 2 ? 96 : 105 })),
  structures: Array.from({ length: 600 }, (_, index) => ({ id: `original-structure-${index}`, type: index % 2 ? "MSS" : "BOS", direction: index % 2 ? "bullish" : "bearish", createdAt: stamp(Math.floor(index / 2)), confirmedAt: stamp(Math.floor(index / 2) + 2), price: 100 })),
  zones: Array.from({ length: 80 }, (_, index): ZoneOverlay => ({ id: `original-zone-${index}`, kind: index % 2 ? "ORDER_BLOCK" : "FVG", direction: index % 2 ? "bearish" : "bullish", lower: 97 + index % 10, upper: 98 + index % 10, createdAt: stamp(index * 4), confirmedAt: index % 2 ? null : stamp(index * 4), validatedAt: index % 2 ? stamp(index * 4 + 1) : null, updatedAt: stamp(index * 4 + 2), mitigatedAt: null, invalidatedAt: null, status: index % 2 ? "VALIDATED" : "OPEN", lifecycleState: index % 2 ? "VALIDATED" : "ACTIVE", lifecycle: [], terminalAt: null, isTerminal: false })), macd: [],
};
const signal: SignalViewModel = { symbol: "BTCUSDT", strategyEvaluationClock: "15m", dataCutoffAt: stamp(499), algorithmScore: 7, scoreBreakdown: {}, decisionMode: "DETERMINISTIC_ONLY", aiValidationStatus: "NOT_REQUESTED", algorithmDecision: "LONG", aiDecision: null, finalDecision: "LONG", entryMin: 100, entryMax: 101, takeProfit: 108, stopLoss: 94, confidence: null, riskReward: 1.4, reason: [], factors: {}, validatedAt: stamp(352) };

function Fixture() {
  const [period, setPeriod] = useState("15m");
  const [view, setView] = useState(cleanEvidenceView);
  const [selection, setSelection] = useState<string[] | null>(null);
  const [recorded, setRecorded] = useState<{ analysis: AnalysisViewModel; candles: Candle[]; hourly: Candle[] } | null>(null);
  const [error, setError] = useState("");
  const source = recorded?.analysis ?? analysis;
  const chartSignal = recorded ? null : signal;
  const rows = useMemo(() => evidenceRecords(source, chartSignal), [source, chartSignal]);
  const chartCandles = useMemo(() => period === "15m" ? recorded?.candles ?? allCandles : recorded?.hourly ?? hourlyCandles, [recorded, period]);
  async function loadRecorded() {
    try {
      const [raw, candles, hourly] = await Promise.all([fetch("/recorded-analysis.json").then((response) => response.json()), fetch("/recorded-candles.json").then((response) => response.json()), fetch("/recorded-candles-1h.json").then((response) => response.json())]);
      setRecorded({ analysis: normalizeAnalysis(raw, "BTCUSDT"), candles, hourly });
    } catch (reason) { setError(String(reason)); }
  }
  return <main className="terminal-shell"><h1 style={{ fontSize: 16 }}>Evidence V2 · {recorded ? "Recorded real Binance/API evidence" : "Explicit dense test fixture"}</h1>
    <div className="evidence-focus"><button onClick={() => setPeriod("15m")}>Display 15m</button><button onClick={() => setPeriod("1h")}>Display 1h</button><button onClick={loadRecorded}>Load recorded real evidence</button><span>{error}</span></div>
    <section className="market-workspace" style={{ display: "block" }}><ChartEvidenceControls view={view} counts={evidenceCounts(rows)} onChange={setView} onInspect={() => setSelection([])} />
      <div className="primary-chart" style={{ height: 460 }}><PriceChart candles={chartCandles} analysis={source} signal={chartSignal} view={view} onInspect={setSelection} /></div>
      {selection !== null && <ChartEvidenceInspector key={selection.join("|")} rows={rows} selection={selection} source={source.sourceEvidence} stale={Boolean(recorded)} onClose={() => setSelection(null)} />}
    </section></main>;
}
createRoot(document.getElementById("evidence-root")!).render(<Fixture />);
