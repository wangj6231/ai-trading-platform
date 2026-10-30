import { proxyEvaluation } from "@/lib/evaluation-proxy";
type Context = { params: Promise<{ evaluationId: string }> };
export async function GET(request: Request, context: Context) {
  return proxyEvaluation(request, (await context.params).evaluationId);
}
export async function DELETE(request: Request, context: Context) {
  return proxyEvaluation(request, (await context.params).evaluationId);
}
