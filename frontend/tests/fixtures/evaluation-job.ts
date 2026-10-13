// Explicit test-only lifecycle data, never real provider or performance evidence.
import { analysisFixture, signalFixture } from "./mtf-contract";
import type { EvaluationJob } from "@/lib/evaluations";
import type { SymbolCode } from "@/types/trading";

export function evaluationFixture(status: EvaluationJob["status"] = "COMPLETED", symbol: SymbolCode = "BTCUSDT",
  evaluationId = "00000000-0000-4000-8000-000000000001") {
  const terminal = ["COMPLETED", "FAILED", "CANCELLED"].includes(status);
  return {
    evaluation_id: evaluationId, symbol, canonical_timeframe: "15m", cutoff: signalFixture.data_cutoff_at,
    strategy_identity: analysisFixture.evaluation.strategy_identity,
    market_data_identity: status === "PENDING" ? null : {
      provenance: { ...signalFixture.provenance, symbol }, history_content_hash: "4".repeat(64),
    },
    created_at: "2025-01-01T00:30:01Z", started_at: status === "PENDING" ? null : "2025-01-01T00:30:02Z",
    completed_at: terminal ? "2025-01-01T00:30:20Z" : null, status, result_available: status === "COMPLETED",
    failure: status === "FAILED" ? { code: "EXPLICIT_FIXTURE_FAILURE", message: "Fixture evaluation failed." } : null,
  };
}
