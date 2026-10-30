import { NextResponse } from "next/server";
import { z } from "zod";
import { proxyBackend } from "./backend-proxy";

export async function proxyEvaluation(request: Request, evaluationId: string, result?: "signal" | "analysis") {
  if (!z.uuid().safeParse(evaluationId).success) {
    return NextResponse.json({ error: { code: "INVALID_EVALUATION_ID", message: "Invalid evaluation identifier." } }, { status: 400 });
  }
  const response = await proxyBackend(`/api/v1/evaluations/${evaluationId}${result ? `/${result}` : ""}`,
    { method: request.method, signal: request.signal }, request.headers);
  response.headers.set("Cache-Control", "no-store");
  return response;
}
