import { z } from "zod";
import { ApiRequestError, BackendContractError, normalizeAnalysis, parseResponse, parseSignalPayload,
  ProvenanceSchema, StrategyIdentitySchema } from "./api";
import { SYMBOLS } from "@/types/trading";
import type { AnalysisViewModel, MarketDataProvenance, SignalViewModel, SymbolCode } from "@/types/trading";

const Timestamp = z.string().refine((value) => !Number.isNaN(Date.parse(value)) &&
  (value.endsWith("Z") || /[+-]\d{2}:\d{2}$/.test(value)), "Expected an aware timestamp");
const JobSchema = z.object({
  evaluation_id: z.uuid(), symbol: z.enum(SYMBOLS), canonical_timeframe: z.literal("15m"),
  cutoff: Timestamp, strategy_identity: StrategyIdentitySchema,
  market_data_identity: z.object({ provenance: ProvenanceSchema,
    history_content_hash: z.string().regex(/^[0-9a-f]{64}$/).nullable() }).strict().nullable(),
  created_at: Timestamp, started_at: Timestamp.nullable(), completed_at: Timestamp.nullable(),
  status: z.enum(["PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]),
  result_available: z.boolean(), failure: z.object({ code: z.string().min(1), message: z.string().min(1) }).strict().nullable(),
}).strict().superRefine((job, context) => {
  const terminal = ["COMPLETED", "FAILED", "CANCELLED"].includes(job.status);
  if (terminal !== (job.completed_at !== null) || job.result_available !== (job.status === "COMPLETED") ||
      (job.failure !== null) !== (job.status === "FAILED") ||
      (job.status === "RUNNING" && job.started_at === null) ||
      (job.status === "COMPLETED" && job.market_data_identity === null)) {
    context.addIssue({ code: "custom", message: "Evaluation lifecycle is inconsistent" });
  }
  const data = job.market_data_identity?.provenance;
  if (data && (data.symbol !== job.symbol || data.timeframe !== job.canonical_timeframe ||
      Date.parse(data.data_cutoff_at) !== Date.parse(job.cutoff))) {
    context.addIssue({ code: "custom", message: "Evaluation data identity differs from the accepted job" });
  }
});

export type EvaluationJob = z.infer<typeof JobSchema>;
export interface EvaluationResult { signal: SignalViewModel; analysis: AnalysisViewModel }

export function parseEvaluationJob(payload: unknown, symbol: SymbolCode, evaluationId?: string): EvaluationJob {
  const parsed = JobSchema.safeParse(payload);
  if (!parsed.success || parsed.data.symbol !== symbol || (evaluationId && parsed.data.evaluation_id !== evaluationId)) {
    throw new BackendContractError("Evaluation lifecycle or identity is invalid.");
  }
  return parsed.data;
}

function jobPath(evaluationId: string) {
  if (!z.uuid().safeParse(evaluationId).success) throw new BackendContractError("Invalid evaluation identifier.");
  return `/api/evaluations/${evaluationId}`;
}

export async function cancelEvaluation(evaluationId: string, symbol: SymbolCode): Promise<EvaluationJob> {
  const response = await fetch(jobPath(evaluationId), { method: "DELETE", cache: "no-store", keepalive: true });
  return parseEvaluationJob(await parseResponse(response), symbol, evaluationId);
}

function pause(signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) { reject(new DOMException("Evaluation request cancelled.", "AbortError")); return; }
    const aborted = () => { clearTimeout(timer); reject(new DOMException("Evaluation request cancelled.", "AbortError")); };
    const timer = setTimeout(() => { signal.removeEventListener("abort", aborted); resolve(); }, 1500);
    signal.addEventListener("abort", aborted, { once: true });
  });
}

export async function fetchEvaluation(symbol: SymbolCode, signal: AbortSignal,
  onState: (job: EvaluationJob) => void): Promise<EvaluationResult> {
  let current: EvaluationJob | undefined;
  let cancellationRequested = false;
  const cleanup = () => {
    if (current && !cancellationRequested && ["PENDING", "RUNNING"].includes(current.status)) {
      cancellationRequested = true;
      void cancelEvaluation(current.evaluation_id, symbol).catch(() => undefined);
    }
  };
  signal.addEventListener("abort", cleanup, { once: true });
  try {
    const response = await fetch("/api/evaluations", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol }), signal, cache: "no-store" });
    current = parseEvaluationJob(await parseResponse(response), symbol);
    if (signal.aborted) { cleanup(); throw new DOMException("Evaluation request cancelled.", "AbortError"); }
    const acceptedId = current.evaluation_id;
    const acceptedCutoff = current.cutoff;
    const acceptedConfig = current.strategy_identity.config_hash;
    onState(current);
    // Bound the whole client lifecycle while keeping every proxy request's
    // original deadline. Abort owns the polling timer and any active fetch.
    const expires = Date.now()+180_000;
    while (["PENDING", "RUNNING"].includes(current.status)) {
      if (Date.now() >= expires) { cleanup(); throw new ApiRequestError(504, "EVALUATION_WAIT_TIMEOUT", "Evaluation has not completed within its waiting lifetime."); }
      await pause(signal);
      const status = await fetch(jobPath(acceptedId), { signal, cache: "no-store" });
      current = parseEvaluationJob(await parseResponse(status), symbol, acceptedId);
      if (current.cutoff !== acceptedCutoff || current.strategy_identity.config_hash !== acceptedConfig) {
        throw new BackendContractError("Evaluation cutoff or configuration changed while running.");
      }
      if (signal.aborted) throw new DOMException("Evaluation request cancelled.", "AbortError");
      onState(current);
    }
    if (current.status !== "COMPLETED") {
      throw new ApiRequestError(503, current.failure?.code ?? "EVALUATION_CANCELLED",
        current.failure?.message ?? "Evaluation was cancelled. No strategy result is available.");
    }
    const url = jobPath(acceptedId);
    const [signalPayload, analysisPayload] = await Promise.all([
      fetch(`${url}/signal`, { signal, cache: "no-store" }).then(parseResponse),
      fetch(`${url}/analysis`, { signal, cache: "no-store" }).then(parseResponse),
    ]);
    const completedSignal = parseSignalPayload(signalPayload, symbol);
    const completedAnalysis = normalizeAnalysis(analysisPayload, symbol);
    const strategy = completedAnalysis.strategy;
    const data = current.market_data_identity!.provenance;
    const matchesData = (candidate: MarketDataProvenance | undefined) => candidate &&
      (Object.keys(data) as (keyof MarketDataProvenance)[]).every((key) => candidate[key] === data[key]);
    if (!strategy || Date.parse(completedSignal.dataCutoffAt) !== Date.parse(current.cutoff) ||
        Date.parse(strategy.dataCutoffAt) !== Date.parse(current.cutoff) ||
        !matchesData(completedSignal.provenance) || !matchesData(strategy.data) ||
        strategy.identity.config_hash !== current.strategy_identity.config_hash ||
        strategy.identity.strategy_version !== current.strategy_identity.strategy_version ||
        strategy.identity.algorithm_build_hash !== current.strategy_identity.algorithm_build_hash) {
      throw new BackendContractError("Completed results do not match this evaluation identity.");
    }
    return { signal: completedSignal, analysis: completedAnalysis };
  } catch (error) {
    cleanup();
    throw error;
  } finally {
    signal.removeEventListener("abort", cleanup);
  }
}
