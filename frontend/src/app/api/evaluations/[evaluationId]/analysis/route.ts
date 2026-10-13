import { proxyEvaluation } from "@/lib/evaluation-proxy";
export async function GET(request: Request, context: { params: Promise<{ evaluationId: string }> }) {
  return proxyEvaluation(request, (await context.params).evaluationId, "analysis");
}
