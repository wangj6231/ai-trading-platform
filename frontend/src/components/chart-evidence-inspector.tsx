"use client";
import { useState, type ReactNode } from "react";
import { EVIDENCE_LAYERS, LAYER_NAMES, rawEvidenceDetail, type EvidenceRecord } from "@/lib/chart-evidence";
import type { EvidenceProjection } from "@/lib/chart-density";

function projectionDetail(row: EvidenceRecord, projection?: EvidenceProjection) {
  const item = row.detail && typeof row.detail === "object" ? row.detail as Record<string, unknown> : {};
  const prices = ["price", "anchorPrice", "lower", "upper", "entryMin", "entryMax", "takeProfit", "stopLoss"].filter(key => item[key] !== undefined).map(key => `${key}: ${String(item[key])}`).join(" · ");
  const times = ["pivotAt", "createdAt", "confirmedAt", "validatedAt", "terminalAt", "lifecycleState", "isTerminal"].filter(key => item[key] !== undefined).map(key => `${key}: ${String(item[key])}`).join(" · ");
  const status = !projection ? "Snapshot inspection; current projection unavailable" : !projection.sources.has(row.key) ? "Stale-suppressed archive · inspection only" : !projection.projectable.has(row.key) ? "Unprojectable on this display (exact timestamp/coordinate or confirmation/validation unavailable)" : !projection.viewport.has(row.key) ? "Offscreen" : projection.rendered.has(row.key) ? "Viewport · rendered source member" : "Viewport · hidden presentation layer";
  return <span className="evidence-projection-detail">Source ID: {String(item.id ?? row.label)} · {prices}<br />{times}<br />Projection: {status}</span>;
}

/** Lazy, paged navigation: every raw field/array entry stays reachable, without mounting the full archive. */
function RawBranch({ label, value, evidenceKey, className, initiallyOpen = false }: { label: ReactNode; value: unknown; evidenceKey?: string; className?: string; initiallyOpen?: boolean }) {
  const [open, setOpen] = useState(initiallyOpen);
  return <details open={open} data-evidence-key={evidenceKey} className={className}><summary onClick={(event) => { event.preventDefault(); setOpen(!open); }}>{label}</summary>{open && <RawTree value={value} />}</details>;
}
function RawTree({ value }: { value: unknown }) {
  const [page, setPage] = useState(0);
  if (value === null || typeof value !== "object") return <code>{JSON.stringify(value) ?? "undefined"}</code>;
  const keys = Object.keys(value);
  const from = page * 25;
  return <div className="raw-tree"><span>{Array.isArray(value) ? "Array" : "Object"} · {keys.length} entries</span>
    {keys.slice(from, from + 25).map((key) => {
      const child = (value as Record<string, unknown>)[key];
      return child !== null && typeof child === "object" ? <RawBranch key={key} label={key} value={child} /> : <div className="raw-leaf" key={key}><b>{key}</b><code>{JSON.stringify(child) ?? "undefined"}</code></div>;
    })}
    {keys.length > 25 && <nav aria-label="Raw evidence pages"><button type="button" disabled={!page} onClick={() => setPage(page - 1)}>Previous fields</button><span>{from + 1}–{Math.min(from + 25, keys.length)} / {keys.length}</span><button type="button" disabled={from + 25 >= keys.length} onClick={() => setPage(page + 1)}>Next fields</button></nav>}
  </div>;
}

export function ChartEvidenceInspector({ rows, selection, source, stale, onClose, projection }: { rows: EvidenceRecord[]; selection: string[] | null; source?: unknown; stale: boolean; onClose: () => void; projection?: EvidenceProjection }) {
  const [filter, setFilter] = useState("All");
  const [page, setPage] = useState(0);
  const [query, setQuery] = useState("");
  const selected = selection?.length ? new Set(selection) : null;
  const filtered = rows.filter((row) => (!selected || selected.has(row.key)) && (filter === "All" || row.layer === filter) && row.label.toLowerCase().includes(query.toLowerCase()));
  const totalPages = Math.max(1, Math.ceil(filtered.length / 20));
  const current = Math.min(page, totalPages - 1);
  return <section className="evidence-inspector" aria-label="Evidence details">
    <div className="evidence-control-heading"><strong>{selected ? `Selected evidence · ${filtered.length}` : `All chart evidence · ${rows.length}`}</strong><button type="button" onClick={onClose}>Close evidence</button></div>
    <p>{stale ? "Previous completed snapshot · stale · inspection only" : "Original server evidence · inspection only"}. Hidden, clustered and unprojectable items remain in this list. One swing item has separate pivot and confirmation markers.</p>
    {selected && <p>Type and member IDs below · {selection!.length} selected source members. Any cluster geometry is an original visual representative, not a new strategy price. Original prices, source / confirmation timestamps and lifecycle remain unchanged.</p>}
    <div className="inspector-filters"><label>Layer <select aria-label="Evidence detail layer" value={filter} onChange={(event) => { setFilter(event.target.value); setPage(0); }}>{["All", ...EVIDENCE_LAYERS].map((layer) => <option key={layer} value={layer}>{layer === "All" ? layer : LAYER_NAMES[layer as keyof typeof LAYER_NAMES]}</option>)}</select></label><label>Find ID <input aria-label="Find evidence ID" value={query} onChange={(event) => { setQuery(event.target.value); setPage(0); }} /></label></div>
    <div className="evidence-records">{filtered.slice(current * 20, current * 20 + 20).map((row) => <RawBranch key={row.key} evidenceKey={row.key} initiallyOpen={selected !== null && filtered.length === 1} label={<><b>{LAYER_NAMES[row.layer]}</b> {row.label}{projectionDetail(row, projection)}</>} value={rawEvidenceDetail(row, source)} />)}</div>
    {!filtered.length && <p>No matching evidence.</p>}
    <nav aria-label="Evidence pages"><button type="button" disabled={current === 0} onClick={() => setPage(current - 1)}>Previous evidence</button><span>Page {current + 1} / {totalPages} · {filtered.length} items</span><button type="button" disabled={current + 1 >= totalPages} onClick={() => setPage(current + 1)}>Next evidence</button></nav>
    {source !== undefined && <RawBranch className="original-evidence" label="Complete original API evidence · all fields and timeframes" value={source} />}
  </section>;
}
