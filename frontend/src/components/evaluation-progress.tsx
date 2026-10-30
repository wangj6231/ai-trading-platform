"use client";
import { useState } from "react";
import { cancelEvaluation } from "@/lib/evaluations";
import type { EvaluationJob } from "@/lib/evaluations";

export function EvaluationProgress({ job, loadingResults, onCancelled }: {
  job: EvaluationJob | null; loadingResults: boolean; onCancelled: (job: EvaluationJob) => void;
}) {
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!job) return null;
  const active = job.status === "PENDING" || job.status === "RUNNING";
  const title = { PENDING: "Evaluation queued", RUNNING: "Evaluating closed 15M data",
    COMPLETED: loadingResults ? "Completed · loading validated results" : "Evaluation completed",
    FAILED: "Evaluation failed", CANCELLED: "Evaluation cancelled" }[job.status];
  async function cancel() {
    if (!job) return;
    setCancelling(true); setError(null);
    try { onCancelled(await cancelEvaluation(job.evaluation_id, job.symbol)); }
    catch { setError("Cancellation request failed. Evaluation may still be running."); }
    finally { setCancelling(false); }
  }
  return <section className="evaluation-progress" aria-label="Evaluation execution" data-evaluation-status={job.status}>
    <div className="evaluation-state"><strong role="status">{title}</strong><span>{job.status}</span>
      {active && <button type="button" className="refresh-button" disabled={cancelling} onClick={() => void cancel()}>{cancelling ? "Cancelling…" : "Cancel evaluation"}</button>}</div>
    <div className="evaluation-meta"><span>{job.symbol} · CLOSED 15M</span><time dateTime={job.cutoff}>{job.cutoff}</time><span title={job.evaluation_id}>Evaluation {job.evaluation_id.slice(0, 8)}</span></div>
    {active && <p>Waiting for a complete validated result. Trade levels appear after completion.</p>}
    {job.failure && <p role="alert">{job.failure.message}</p>}
    {error && <p role="alert">{error}</p>}
    {job.market_data_identity?.history_content_hash && <details><summary>Verified source history identity</summary><code>{job.market_data_identity.history_content_hash}</code></details>}
  </section>;
}
