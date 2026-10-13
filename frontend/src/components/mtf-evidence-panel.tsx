import { formatTimeframe } from "@/lib/format";
import { snapshotStatus } from "@/lib/freshness";
import { TIMEFRAMES } from "@/types/trading";
import type { StrategyProvenance, Timeframe } from "@/types/trading";

// Labels from the product's frozen backend contract. No eligibility calculation.
const REQUIRED: readonly Timeframe[] = ["1h", "4h", "1d"];
const AVAILABILITY: readonly Timeframe[] = ["15m", "1h", "4h", "1d"];

export function MTFEvidencePanel({ provenance, now = 0 }: { provenance: StrategyProvenance; now?: number }) {
  const mtf = provenance.mtf;
  const freshness = snapshotStatus(provenance.data, now);
  return <section className="mtf-evidence" aria-label="MTF evidence">
    <div className="evidence-heading"><h3>MTF EVIDENCE</h3><span>SERVER RESULT</span></div>
    <p className="policy-note">{provenance.symbol} · CLOSED 15M · Cutoff: {provenance.dataCutoffAt}</p>
    {freshness === "STALE" && <p className="stale-notice">STALE SNAPSHOT · These MTF states belong to the saved cutoff. Refresh strategy for newer evidence.</p>}
    <p className="policy-note">Frozen V1 contract · required: 1H / 4H / 1D · veto: 1D · min aligned: 2<br />Availability required: 15M / 1H / 4H / 1D</p>
    {mtf ? <>
      <div className="mtf-result"><strong>{mtf.alignment}</strong><span>{mtf.eligibility ?? "ELIGIBILITY UNAVAILABLE"}</span>
        <span>Trade gate: {mtf.trade_allowed === undefined ? "UNKNOWN" : mtf.trade_allowed ? "ALLOWED" : "BLOCKED"}</span>
        <span>Required alignment · bullish {mtf.bullish_count ?? "—"} / bearish {mtf.bearish_count ?? "—"}</span>
      </div>
      <ul className="mtf-inputs">{TIMEFRAMES.filter((tf) => mtf.timeframes[tf]).map((tf) => {
        const row = mtf.timeframes[tf];
        const context = row.role === "CONTEXT_ONLY";
        const notReady = row.state === "INSUFFICIENT_DATA" || row.reason_codes.includes("MTF_WARMUP_INCOMPLETE");
        const status = row.stale ? "STALE" : !row.available ? "UNAVAILABLE" : "AVAILABLE";
        return <li key={tf} className={context ? "context-row" : "authority-row"} data-role={row.role} data-mtf-timeframe={tf}>
          <div className="mtf-row-heading"><strong>{formatTimeframe(row.timeframe)}</strong><span className={`role-badge role-${row.role.toLowerCase()}`}>{context ? "CONTEXT ONLY" : row.role.replaceAll("_", " ")}</span></div>
          {context ? <span>CONTEXT ONLY · NO ALIGNMENT / VETO AUTHORITY</span> : <div className="authority-badges">
            {REQUIRED.includes(tf) && <span>REQUIRED</span>}{tf === "1d" && <span className="veto-badge">VETO</span>}
            {AVAILABILITY.includes(tf) && <span>AVAILABILITY REQUIRED</span>}
          </div>}
          <span className={`mtf-readiness ${status.toLowerCase()}`}>{status}{notReady ? " · NOT READY" : ""} · {row.state.replaceAll("_", " ")} · {row.closed_bar_count} closed bars</span>
          {row.reason_codes.length > 0 && <small>{row.reason_codes.join(" · ")}</small>}
          <details><summary>Closed-bar evidence</summary><span>Latest close: {row.latest_closed_bar_at ?? "NOT RETURNED"}<br />State confirmed: {row.state_confirmed_at ?? "NOT RETURNED"}</span></details>
        </li>;
      })}</ul>
      {!!mtf.reason_codes?.length && <p className="policy-note">{mtf.reason_codes.join(" · ")}</p>}
    </> : <p>MTF EVIDENCE NOT RETURNED. Readiness is unknown for this snapshot.</p>}
  </section>;
}
