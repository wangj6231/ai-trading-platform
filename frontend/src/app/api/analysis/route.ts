import type { NextRequest } from "next/server";
import { proxyStrategyRequest } from "@/lib/product-request";

export async function POST(request: NextRequest) {
  return proxyStrategyRequest(request, "/api/v1/analysis");
}
