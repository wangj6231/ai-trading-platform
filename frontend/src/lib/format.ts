export function formatPrice(value: number | null, reference?: number): string {
  if (value === null || !Number.isFinite(value)) return "—";
  const decimals = reference && reference < 10 ? 4 : reference && reference < 1000 ? 2 : 1;
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
}

export function formatTimeframe(timeframe: string): string {
  return timeframe === "1h" ? "1H" : timeframe.toUpperCase();
}

export function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}
