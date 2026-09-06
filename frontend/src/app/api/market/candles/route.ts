import type { NextRequest } from "next/server";
import { proxyBackend } from "@/lib/backend-proxy";

export async function GET(request: NextRequest) {
  const query = request.nextUrl.searchParams.toString();
  return proxyBackend(`/api/v1/market/candles?${query}`, {
    signal: request.signal,
  });
}
