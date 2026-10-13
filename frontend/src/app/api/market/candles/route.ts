import { NextResponse, type NextRequest } from "next/server";
import { z } from "zod";
import { SYMBOLS, TIMEFRAMES } from "@/types/trading";
import { proxyBackend } from "@/lib/backend-proxy";

export async function GET(request: NextRequest) {
  const parsed = z.object({ symbol: z.enum(SYMBOLS), timeframe: z.enum(TIMEFRAMES) }).safeParse({
    symbol: request.nextUrl.searchParams.get("symbol"), timeframe: request.nextUrl.searchParams.get("timeframe"),
  });
  if (!parsed.success) return NextResponse.json({ error: { code: "INVALID_PRODUCT_REQUEST", message: "Select a supported Binance Spot symbol and chart timeframe." } }, { status: 400 });
  const query = request.nextUrl.searchParams.toString();
  return proxyBackend(`/api/v1/market/candles?${query}`, {
    signal: request.signal,
  }, request.headers);
}
