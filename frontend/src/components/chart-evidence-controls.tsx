"use client";
import { useEffect, useRef, useState } from "react";
import { EVIDENCE_LAYERS, EVIDENCE_PRESETS, FOCUS_MODES, LAYER_NAMES, cleanEvidenceView, decisionEvidenceView, presetEvidenceView, layerVisible, type EvidenceLayer, type EvidencePreset, type EvidenceView } from "@/lib/chart-evidence";
import type { EvidenceDensity } from "@/lib/chart-density";

export function ChartEvidenceControls({ view, counts, onChange, onInspect, available = true, density }: { view: EvidenceView; counts: Record<EvidenceLayer, number>; onChange: (view: EvidenceView) => void; onInspect: () => void; available?: boolean; density?: EvidenceDensity }) {
  const [layersOpen, setLayersOpen] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { if (view.preset && layersOpen) dialog.current?.showModal(); }, [view.preset, layersOpen]);
  const layerGrid = <div className="evidence-layer-grid">{EVIDENCE_LAYERS.map((layer) => <div key={layer} data-layer-control={layer} className={!layerVisible(layer, view) ? "layer-muted" : ""}>
    <label><input type="checkbox" checked={view.visible[layer]} aria-label={`${LAYER_NAMES[layer]} layer`} onChange={(event) => onChange({ ...view, visible: { ...view.visible, [layer]: event.target.checked } })} />{LAYER_NAMES[layer]} <b data-evidence-count={layer}>{available ? counts[layer] : "—"}</b></label>
    <label><input type="checkbox" checked={view.labels[layer]} aria-label={`${LAYER_NAMES[layer]} labels`} onChange={(event) => onChange({ ...view, labels: { ...view.labels, [layer]: event.target.checked } })} />Text</label>
    {view.preset && <small data-density-layer={layer}>{available ? `${counts[layer]} source` : "Source unknown"}{density ? ` · ${density[layer].viewport} viewport · ${density[layer].renderedSource} rendered source · ${density[layer].visuals} visuals (${density[layer].clusters} clusters) · ${density[layer].offscreen} offscreen · ${density[layer].unavailable} unprojectable${density[layer].staleSuppressed ? ` (${density[layer].staleSuppressed} stale suppressed)` : ""}` : " · projection unavailable"}</small>}
  </div>)}</div>;
  if (view.preset) return <section className="evidence-controls density-controls" aria-label="Chart evidence controls">
    <div className="density-toolbar"><label>View <select aria-label="Chart view" value={view.preset} onChange={event => onChange(presetEvidenceView(event.target.value as EvidencePreset, view.reset))}>{EVIDENCE_PRESETS.map(preset => <option key={preset} value={preset}>{preset}</option>)}</select></label>
      <button type="button" onClick={() => setLayersOpen(true)}>Layers &amp; labels</button><button type="button" aria-label="Browse all evidence" onClick={onInspect} disabled={!available}>Evidence</button><button type="button" onClick={() => onChange(decisionEvidenceView(view.reset + 1))}>Reset View</button>
    </div>
    {layersOpen && <dialog ref={dialog} className="density-panel" aria-label="Chart layers" onClose={() => setLayersOpen(false)}>
      <div className="evidence-control-heading density-panel-heading"><strong>Layers · presentation only</strong><button type="button" onClick={() => dialog.current?.close()}>Close layers</button></div>
      <p>Source counts include the complete archive. Viewport means exact projections intersecting this chart; rendered source means members represented by mounted visuals. Unprojectable means this display has no exact timestamp / coordinate, or the source is not yet confirmed or validated.</p>
      {layerGrid}<div className="evidence-focus" role="group" aria-label="Evidence focus">{FOCUS_MODES.map(focus => <button type="button" key={focus} aria-pressed={view.focus === focus} onClick={() => onChange({ ...view, focus })}>{focus}</button>)}</div>
      <p>Clusters use an original visual representative. Inspect to see every original ID, price and lifecycle; no new strategy levels are calculated.</p>
    </dialog>}
  </section>;
  const defaults = cleanEvidenceView();
  const clean = view.focus === "All" && EVIDENCE_LAYERS.every((layer) => view.visible[layer] && view.labels[layer] === defaults.labels[layer]);
  return <section className="evidence-controls" aria-label="Chart evidence controls">
    <div className="evidence-control-heading"><strong>{clean ? "Clean View" : "Custom View"}</strong><span>15M evidence · display only</span><button type="button" onClick={() => onChange(cleanEvidenceView(view.reset + 1))}>Reset View</button><button type="button" onClick={onInspect} disabled={!available}>Browse all evidence</button></div>
    <div className="evidence-focus" role="group" aria-label="Evidence focus">{FOCUS_MODES.map((focus) => <button type="button" key={focus} aria-pressed={view.focus === focus} onClick={() => onChange({ ...view, focus })}>{focus}</button>)}</div>
    <details className="evidence-layers" open={layersOpen}><summary onClick={(event) => { event.preventDefault(); setLayersOpen(!layersOpen); }}>Layers &amp; labels <span>Counts = all source items · labels adapt to zoom</span></summary>
      {layersOpen && layerGrid}
    </details>
    <p>Hover or select a marker / zone to inspect. Liquidity focuses on swing and S/R references. Trade layers keep priority in every focus.</p>
  </section>;
}
