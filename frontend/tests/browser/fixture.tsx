import { flushSync } from "react-dom";
import { createRoot } from "react-dom/client";
import { PriceChart } from "@/components/price-chart";
import "@/app/globals.css";
import type { Candle, ZoneOverlay } from "@/types/trading";
import { pan, projection, resizeCount } from "./projection-adapter";

const START = "2025-01-01T00:00:00Z";
const END = "2025-01-01T00:05:00Z";
const CHART_END = "2025-01-01T00:10:00Z";
const FUTURE = "2025-01-01T00:15:00Z";
const unix = (time: string) => new Date(time).getTime() / 1000;
const fixture = document.getElementById("fixture")!;
const root = createRoot(fixture);

export interface FixtureOptions {
  start: number;
  end: number;
  kind?: "FVG" | "IFVG" | "ORDER_BLOCK";
  state?: "FILLED" | "INVERTED" | "INVALIDATED" | "EXPIRED";
  live?: boolean;
}

const candle: Candle = {
  timestamp: CHART_END, open: "100", high: "110", low: "90", close: "105", volume: "1",
};
let current: FixtureOptions = { start: 100, end: 106 };
let candles = [candle];

function zone(): ZoneOverlay {
  const kind = current.kind ?? "FVG";
  const isOb = kind === "ORDER_BLOCK";
  const state = current.state ?? (kind === "FVG" ? "FILLED" : "INVALIDATED");
  const events = {
    FVG: { FILLED: "FVG_FILLED", INVERTED: "FVG_INVERTED", INVALIDATED: "IFVG_INVALIDATED", EXPIRED: "FVG_EXPIRED" },
    IFVG: { FILLED: "IFVG_FILLED", INVERTED: "FVG_INVERTED", INVALIDATED: "IFVG_INVALIDATED", EXPIRED: "IFVG_EXPIRED" },
    ORDER_BLOCK: { FILLED: "OB_INVALIDATED", INVERTED: "OB_INVALIDATED", INVALIDATED: "OB_INVALIDATED", EXPIRED: "OB_EXPIRED" },
  } as const;
  const live = current.live ?? false;
  return {
    id: "test-only-zone", kind: isOb ? "ORDER_BLOCK" : "FVG", direction: "bullish",
    lower: 100, upper: 120, createdAt: START,
    confirmedAt: isOb ? null : START, validatedAt: isOb ? START : null,
    updatedAt: live ? START : END, mitigatedAt: null,
    invalidatedAt: !live && state === "INVALIDATED" ? END : null,
    status: live ? "OPEN" : state === "INVERTED" ? "FILLED" : state,
    lifecycleState: live ? "ACTIVE" : state,
    lifecycle: [{
      type: live ? "FVG_CREATED" : events[kind][state], occurredAt: live ? START : END,
      fromState: live ? null : isOb ? "VALIDATED" : "ACTIVE", toState: live ? "ACTIVE" : state,
    }],
    terminalAt: live ? null : END, isTerminal: !live,
  };
}

function draw() {
  flushSync(() => root.render(<PriceChart candles={candles} signal={null}
    analysis={{ supports: [], resistances: [], swings: [], structures: [], macd: [], zones: [zone()] }} />));
}

function setProjection(start: number, end: number) {
  projection.set(unix(START), start);
  projection.set(unix(END), end);
  projection.set(unix(CHART_END), current.live ? end : 300);
  projection.set(unix(FUTURE), 500);
}

const chartFixture = {
  mount(options: FixtureOptions) {
    current = options;
    candles = [candle];
    setProjection(options.start, options.end);
    draw();
  },
  appendFuture() { candles = [...candles, { ...candle, timestamp: FUTURE }]; draw(); },
  pan(start: number, end: number) { setProjection(start, end); pan(); },
  resize(start: number, end: number) {
    setProjection(start, end);
    fixture.style.width = "660px"; // Real ResizeObserver; no synthetic callback.
  },
  resizeCount: () => resizeCount,
};

declare global { interface Window { chartFixture: typeof chartFixture } }
window.chartFixture = chartFixture;
