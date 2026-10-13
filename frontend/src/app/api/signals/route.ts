import type { NextRequest } from "next/server";
import { forwardBackendHeaders } from "@/lib/backend-proxy";
import { proxyStrategyRequest } from "@/lib/product-request";

export async function GET(request: NextRequest) {
  const symbol = request.nextUrl.searchParams.get("symbol");
  // Deprecated chart context is not sent as strategy authority.
  return proxyStrategyRequest(new Request(request.url, {
    method: "POST",
    headers: forwardBackendHeaders(request.headers, { "Content-Type": "application/json" }),
    body: JSON.stringify({ symbol }),
    signal: request.signal,
  }), "/api/v1/signals/evaluate");
}

export async function POST(request: NextRequest) {
  return proxyStrategyRequest(request, "/api/v1/signals/evaluate");
}
