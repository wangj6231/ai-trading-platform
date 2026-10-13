import { NextResponse } from "next/server";
import { z } from "zod";
import { SYMBOLS } from "@/types/trading";
import { proxyBackend } from "./backend-proxy";

const StrategyRequest = z.object({ symbol: z.enum(SYMBOLS) }).strict();

export async function proxyStrategyRequest(request: Request, path: string) {
  const payload: unknown = await request.json().catch(() => null);
  const parsed = StrategyRequest.safeParse(payload);
  if (!parsed.success) return NextResponse.json({ error: {
    code: "INVALID_PRODUCT_REQUEST", message: "Select BTCUSDT or ETHUSDT. Strategy requests accept symbol only.",
  } }, { status: 400 });
  return proxyBackend(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(parsed.data), signal: request.signal }, request.headers);
}
