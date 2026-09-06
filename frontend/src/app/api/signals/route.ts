import type { NextRequest } from "next/server";
import { proxyBackend, proxyJsonPost } from "@/lib/backend-proxy";

export async function GET(request: NextRequest) {
  const symbol = request.nextUrl.searchParams.get("symbol");
  const timeframe = request.nextUrl.searchParams.get("timeframe");
  return proxyBackend("/api/v1/signals/evaluate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbol, timeframe }),
    signal: request.signal,
  });
}

export async function POST(request: NextRequest) {
  return proxyJsonPost(request, "/api/v1/signals/evaluate");
}
