// TEST ONLY. No fake market data or projection adapter enters the Next.js app.
export const CandlestickSeries = Symbol("CandlestickSeries");
export const ColorType = { Solid: "Solid" };
export const projection = new Map<number, number>();
const listeners = new Set<() => void>();
export let resizeCount = 0;

export function pan() {
  for (const listener of listeners) listener();
}

export function createChart() {
  const scale = {
    fitContent() {},
    timeToCoordinate: (timestamp: number) => projection.get(Number(timestamp)) ?? null,
    subscribeVisibleLogicalRangeChange: (listener: () => void) => listeners.add(listener),
    unsubscribeVisibleLogicalRangeChange: (listener: () => void) => listeners.delete(listener),
  };
  return {
    addSeries: () => ({
      setData() {},
      priceToCoordinate: (price: number) => 200 - price,
    }),
    applyOptions() { resizeCount += 1; },
    timeScale: () => scale,
    remove() {},
  };
}

export function createSeriesMarkers() {}
