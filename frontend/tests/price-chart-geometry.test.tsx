import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const chartHarness = vi.hoisted(() => {
  const coordinates = new Map<number, number>();
  const resizeListeners = new Set<() => void>();
  const visibleRangeListeners = new Set<() => void>();
  const timeScale = {
    fitContent: vi.fn(),
    timeToCoordinate: vi.fn((time: number) => coordinates.get(Number(time)) ?? null),
    subscribeVisibleLogicalRangeChange: vi.fn((listener: () => void) => {
      visibleRangeListeners.add(listener);
    }),
    unsubscribeVisibleLogicalRangeChange: vi.fn((listener: () => void) => {
      visibleRangeListeners.delete(listener);
    }),
  };
  const series = {
    setData: vi.fn(),
    priceToCoordinate: vi.fn((price: number) => 200 - price),
  };
  const chart = {
    addSeries: vi.fn(() => series),
    applyOptions: vi.fn(),
    remove: vi.fn(),
    timeScale: vi.fn(() => timeScale),
  };
  return {
    chart,
    coordinates,
    createChart: vi.fn(() => chart),
    createSeriesMarkers: vi.fn(),
    resizeListeners,
    visibleRangeListeners,
  };
});

vi.mock("lightweight-charts", () => ({
  CandlestickSeries: Symbol("CandlestickSeries"),
  ColorType: { Solid: "Solid" },
  createChart: chartHarness.createChart,
  createSeriesMarkers: chartHarness.createSeriesMarkers,
}));

import { PriceChart } from "@/components/price-chart";
import type {
  AnalysisViewModel,
  Candle,
  SignalViewModel,
  ZoneOverlay,
} from "@/types/trading";

const START_AT = "2025-01-01T00:00:00Z";
const TERMINAL_AT = "2025-01-01T00:05:00Z";
const CHART_END_AT = "2025-01-01T00:10:00Z";
const FUTURE_CHART_END_AT = "2025-01-01T00:15:00Z";

function unixTime(timestamp: string): number {
  return Math.floor(new Date(timestamp).getTime() / 1000);
}

const candles: Candle[] = [
  {
    timestamp: CHART_END_AT,
    open: "100",
    high: "110",
    low: "90",
    close: "105",
    volume: "1",
  },
];

function terminalZone(
  lifecycleState: "FILLED" | "INVERTED" | "INVALIDATED" | "EXPIRED" = "FILLED",
  kind: "FVG" | "ORDER_BLOCK" = "FVG",
): ZoneOverlay {
  const fvgEvent = {
    FILLED: "FVG_FILLED",
    INVERTED: "FVG_INVERTED",
    INVALIDATED: "IFVG_INVALIDATED",
    EXPIRED: "FVG_EXPIRED",
  } as const;
  const orderBlockEvent = lifecycleState === "EXPIRED" ? "OB_EXPIRED" : "OB_INVALIDATED";
  return {
    id: `${kind.toLowerCase()}-${lifecycleState.toLowerCase()}`,
    kind,
    direction: "bullish",
    lower: 100,
    upper: 102,
    createdAt: START_AT,
    confirmedAt: kind === "FVG" ? START_AT : null,
    validatedAt: kind === "ORDER_BLOCK" ? START_AT : null,
    updatedAt: TERMINAL_AT,
    mitigatedAt: null,
    invalidatedAt: lifecycleState === "INVALIDATED" ? TERMINAL_AT : null,
    status:
      lifecycleState === "INVALIDATED"
        ? "INVALIDATED"
        : lifecycleState === "EXPIRED"
          ? "EXPIRED"
          : "FILLED",
    lifecycleState,
    lifecycle: [
      {
        type: kind === "FVG" ? fvgEvent[lifecycleState] : orderBlockEvent,
        occurredAt: TERMINAL_AT,
        fromState: kind === "FVG" ? "ACTIVE" : "VALIDATED",
        toState: lifecycleState,
      },
    ],
    terminalAt: TERMINAL_AT,
    isTerminal: true,
  };
}

function activeFvg(): ZoneOverlay {
  return {
    ...terminalZone(),
    id: "fvg-active",
    updatedAt: START_AT,
    status: "OPEN",
    lifecycleState: "ACTIVE",
    lifecycle: [
      {
        type: "FVG_CREATED",
        occurredAt: START_AT,
        fromState: null,
        toState: "ACTIVE",
      },
    ],
    terminalAt: null,
    isTerminal: false,
  };
}

function currentSignal(): SignalViewModel {
  return {
    symbol: "BTCUSDT",
    timeframe: "5m",
    decisionMode: "DETERMINISTIC_ONLY",
    aiValidationStatus: "NOT_REQUESTED",
    algorithmDecision: "LONG",
    aiDecision: null,
    finalDecision: "LONG",
    entryMin: 100,
    entryMax: 102,
    takeProfit: 110,
    stopLoss: 95,
    confidence: null,
    riskReward: 2,
    reason: [],
    factors: {},
    validatedAt: START_AT,
  };
}

function analysisWith(zone: ZoneOverlay): AnalysisViewModel {
  return {
    supports: [],
    resistances: [],
    swings: [],
    structures: [],
    zones: [zone],
    macd: [],
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  chartHarness.coordinates.clear();
  chartHarness.resizeListeners.clear();
  chartHarness.visibleRangeListeners.clear();
  chartHarness.coordinates.set(unixTime(START_AT), 100);
  chartHarness.coordinates.set(unixTime(TERMINAL_AT), 106);
  chartHarness.coordinates.set(unixTime(CHART_END_AT), 300);
  chartHarness.coordinates.set(unixTime(FUTURE_CHART_END_AT), 500);
  vi.stubGlobal(
    "ResizeObserver",
    class {
      private readonly notify: () => void;

      constructor(callback: ResizeObserverCallback) {
        this.notify = () => callback([], this as unknown as ResizeObserver);
        chartHarness.resizeListeners.add(this.notify);
      }

      observe() {}
      disconnect() {
        chartHarness.resizeListeners.delete(this.notify);
      }
    },
  );
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    callback(0);
    return 1;
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderedZone(
  container: HTMLElement,
  selector = ".chart-zone",
): HTMLElement {
  const zone = container.querySelector<HTMLElement>(selector);
  expect(zone).not.toBeNull();
  return zone!;
}

function rightEdge(zone: HTMLElement): number {
  return Number.parseFloat(zone.style.left) + Number.parseFloat(zone.style.width);
}

describe("PriceChart zone DOM geometry", () => {
  it("ends a short terminal zone at the trusted terminal projection", () => {
    const { container } = render(
      <PriceChart
        candles={candles}
        analysis={analysisWith(terminalZone())}
        signal={null}
      />,
    );

    const zone = renderedZone(container, ".chart-zone.terminal");
    expect(zone.style.left).toBe("100px");
    expect(zone.style.width).toBe("6px");
    expect(rightEdge(zone)).toBe(106);
  });

  it.each([
    ["FVG", "FILLED"],
    ["FVG", "INVERTED"],
    ["FVG", "INVALIDATED"],
    ["FVG", "EXPIRED"],
    ["ORDER_BLOCK", "INVALIDATED"],
    ["ORDER_BLOCK", "EXPIRED"],
  ] as const)("uses the exact endpoint for terminal %s %s", (kind, state) => {
    const { container } = render(
      <PriceChart
        candles={candles}
        analysis={analysisWith(terminalZone(state, kind))}
        signal={null}
      />,
    );

    expect(rightEdge(renderedZone(container, ".chart-zone.terminal"))).toBe(106);
  });

  it("does not add terminal padding to a normal-width zone", () => {
    chartHarness.coordinates.set(unixTime(TERMINAL_AT), 160);

    const { container } = render(
      <PriceChart
        candles={candles}
        analysis={analysisWith(terminalZone())}
        signal={null}
      />,
    );

    const zone = renderedZone(container, ".chart-zone.terminal");
    expect(zone.style.width).toBe("60px");
    expect(rightEdge(zone)).toBe(160);
  });

  it("keeps an active analysis zone on the existing live-extension path", () => {
    chartHarness.coordinates.set(unixTime(CHART_END_AT), 106);

    const { container } = render(
      <PriceChart
        candles={candles}
        analysis={analysisWith(activeFvg())}
        signal={null}
      />,
    );

    const zone = renderedZone(container, ".chart-zone:not(.terminal)");
    expect(zone.style.left).toBe("100px");
    expect(zone.style.width).toBe("50px");
    expect(rightEdge(zone)).toBe(150);
  });

  it("keeps a current entry plan on the existing live-extension path", () => {
    chartHarness.coordinates.set(unixTime(CHART_END_AT), 106);

    const { container } = render(
      <PriceChart candles={candles} analysis={null} signal={currentSignal()} />,
    );

    const entry = renderedZone(container, ".chart-zone.entry");
    expect(entry.style.width).toBe("50px");
    expect(rightEdge(entry)).toBe(150);
  });

  it("does not extend a terminal zone when future candles arrive", () => {
    const { container, rerender } = render(
      <PriceChart
        candles={candles}
        analysis={analysisWith(terminalZone())}
        signal={null}
      />,
    );
    expect(rightEdge(renderedZone(container, ".chart-zone.terminal"))).toBe(106);

    rerender(
      <PriceChart
        candles={[...candles, { ...candles[0], timestamp: FUTURE_CHART_END_AT }]}
        analysis={analysisWith(terminalZone())}
        signal={null}
      />,
    );

    expect(rightEdge(renderedZone(container, ".chart-zone.terminal"))).toBe(106);
  });

  it("recomputes an exact terminal endpoint after resize", () => {
    const { container } = render(
      <PriceChart
        candles={candles}
        analysis={analysisWith(terminalZone())}
        signal={null}
      />,
    );
    chartHarness.coordinates.set(unixTime(START_AT), 200);
    chartHarness.coordinates.set(unixTime(TERMINAL_AT), 212);

    act(() => {
      for (const notify of chartHarness.resizeListeners) notify();
    });

    const zone = renderedZone(container, ".chart-zone.terminal");
    expect(zone.style.left).toBe("200px");
    expect(zone.style.width).toBe("12px");
    expect(rightEdge(zone)).toBe(212);
  });

  it("recomputes an exact terminal endpoint after chart panning", () => {
    const { container } = render(
      <PriceChart
        candles={candles}
        analysis={analysisWith(terminalZone())}
        signal={null}
      />,
    );
    chartHarness.coordinates.set(unixTime(START_AT), 150);
    chartHarness.coordinates.set(unixTime(TERMINAL_AT), 162);

    act(() => {
      for (const notify of chartHarness.visibleRangeListeners) notify();
    });

    const zone = renderedZone(container, ".chart-zone.terminal");
    expect(zone.style.left).toBe("150px");
    expect(zone.style.width).toBe("12px");
    expect(rightEdge(zone)).toBe(162);
  });

  it.each([
    [100, 100, 0],
    [100, 100.5, 0.5],
  ])("renders terminal subpixel span %s to %s safely", (startX, endX, width) => {
    chartHarness.coordinates.set(unixTime(START_AT), startX);
    chartHarness.coordinates.set(unixTime(TERMINAL_AT), endX);

    const { container } = render(
      <PriceChart
        candles={candles}
        analysis={analysisWith(terminalZone())}
        signal={null}
      />,
    );

    const zone = renderedZone(container, ".chart-zone.terminal");
    expect(Number.parseFloat(zone.style.width)).toBe(width);
    expect(rightEdge(zone)).toBe(endX);
  });

  it("fails closed instead of rendering negative terminal width", () => {
    chartHarness.coordinates.set(unixTime(START_AT), 110);
    chartHarness.coordinates.set(unixTime(TERMINAL_AT), 106);

    const { container } = render(
      <PriceChart
        candles={candles}
        analysis={analysisWith(terminalZone())}
        signal={null}
      />,
    );

    expect(container.querySelector(".chart-zone.terminal")).toBeNull();
  });

  it("clips an off-screen start without moving the visible terminal endpoint", () => {
    chartHarness.coordinates.set(unixTime(START_AT), -4);
    chartHarness.coordinates.set(unixTime(TERMINAL_AT), 6);

    const { container } = render(
      <PriceChart
        candles={candles}
        analysis={analysisWith(terminalZone())}
        signal={null}
      />,
    );

    const zone = renderedZone(container, ".chart-zone.terminal");
    expect(zone.style.left).toBe("0px");
    expect(zone.style.width).toBe("6px");
    expect(rightEdge(zone)).toBe(6);
  });

  it.each([Number.NaN, Number.POSITIVE_INFINITY])(
    "fails closed for a non-finite terminal coordinate",
    (coordinate) => {
      chartHarness.coordinates.set(unixTime(TERMINAL_AT), coordinate);

      const { container } = render(
        <PriceChart
          candles={candles}
          analysis={analysisWith(terminalZone())}
          signal={null}
        />,
      );

      expect(container.querySelector(".chart-zone.terminal")).toBeNull();
    },
  );
});
