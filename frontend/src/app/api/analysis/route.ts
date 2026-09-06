import type { NextRequest } from "next/server";
import { proxyJsonPost } from "@/lib/backend-proxy";

export async function POST(request: NextRequest) {
  return proxyJsonPost(request, "/api/v1/analysis");
}
