import { snapshotStatus } from "@/lib/freshness";
import type { MarketDataProvenance } from "@/types/trading";

export function DataProvenance({ data, now, label, showCutoff = true }: { data?: MarketDataProvenance; now: number; label: string; showCutoff?: boolean }) {
  const status = snapshotStatus(data, now);
  return <section className="data-provenance" aria-label={label}>
    <div className="evidence-heading"><h3>{label}</h3><span className={`status-badge ${status.toLowerCase()}`}>{status === "UNKNOWN" ? "DATA STATUS UNKNOWN" : `${status} SNAPSHOT`}</span></div>
    {status === "STALE" && <p className="stale-notice" role="status">A newer closed candle may be available. Refresh to retrieve the latest snapshot.</p>}
    {data ? <details><summary>{data.provider} · {data.received_candles} closed candles · UTC</summary>
      <dl className="provenance-grid">
        {showCutoff && <div><dt>Cutoff</dt><dd><time dateTime={data.data_cutoff_at}>{data.data_cutoff_at}</time></dd></div>}
        <div><dt>Retrieved</dt><dd><time dateTime={data.retrieved_at}>{data.retrieved_at}</time></dd></div>
        <div><dt>Provider lag</dt><dd>{data.lag_seconds}s</dd></div>
        <div><dt>Data mode</dt><dd>{data.data_mode} · VALIDATED</dd></div>
        <div><dt>Coverage</dt><dd>{data.first_candle_at} → {data.last_candle_at}</dd></div>
      </dl>
    </details> : <p>Server provenance has not been returned.</p>}
  </section>;
}
