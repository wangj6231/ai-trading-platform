import type { MarketDataProvenance, Timeframe } from "@/types/trading";

const PERIOD_MS: Record<Timeframe, number> = {
  "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
  "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000,
  "4h": 14_400_000, "1d": 86_400_000, "1w": 604_800_000,
};

/** Display-only age indicator. Never changes the server decision or MTF gate. */
export function snapshotStatus(data: MarketDataProvenance | undefined, now: number): "CURRENT" | "STALE" | "UNKNOWN" {
  if (!data) return "UNKNOWN";
  // Binance weekly buckets open Monday 00:00 UTC; other buckets use UTC epoch.
  const origin = data.timeframe === "1w" ? Date.UTC(1970, 0, 5) : 0;
  const period = PERIOD_MS[data.timeframe];
  const latestClose = Math.floor((now - origin) / period) * period + origin;
  return data.lag_seconds > 0 || Date.parse(data.data_cutoff_at) < latestClose ? "STALE" : "CURRENT";
}
