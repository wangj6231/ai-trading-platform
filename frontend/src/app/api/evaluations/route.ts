import type { NextRequest } from "next/server";
import { proxyStrategyRequest } from "@/lib/product-request";

export async function POST(request: NextRequest) {
  const response = await proxyStrategyRequest(request, "/api/v1/evaluations");
  response.headers.set("Cache-Control", "no-store");
  return response;
}
