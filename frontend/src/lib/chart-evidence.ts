import type { AnalysisViewModel, SignalViewModel } from "@/types/trading";

export const EVIDENCE_LAYERS = ["support", "resistance", "swing", "bos", "mss", "fvg", "ob", "entry", "tp", "sl"] as const;
export type EvidenceLayer = typeof EVIDENCE_LAYERS[number];
export const FOCUS_MODES = ["All", "Structure", "Liquidity", "Zones", "Trade"] as const;
export type EvidenceFocus = typeof FOCUS_MODES[number];
export const LAYER_NAMES: Record<EvidenceLayer, string> = { support: "Support", resistance: "Resistance", swing: "Swing H/L", bos: "BOS", mss: "MSS", fvg: "FVG", ob: "Order Block", entry: "Entry", tp: "TP", sl: "SL" };
export const EVIDENCE_PRESETS = ["Decision", "Structure", "All Evidence"] as const;
export type EvidencePreset = typeof EVIDENCE_PRESETS[number];
export interface EvidenceView { preset?: EvidencePreset; focus: EvidenceFocus; visible: Record<EvidenceLayer, boolean>; labels: Record<EvidenceLayer, boolean>; reset: number }
/** V2 presentation kept explicitly for regression fixtures; dashboard uses decisionEvidenceView. */
export function cleanEvidenceView(reset = 0): EvidenceView {
  return { focus: "All", reset, visible: Object.fromEntries(EVIDENCE_LAYERS.map((layer) => [layer, true])) as Record<EvidenceLayer, boolean>,
    labels: { support: true, resistance: true, swing: false, bos: true, mss: true, fvg: false, ob: false, entry: true, tp: true, sl: true } };
}
export function presetEvidenceView(preset: EvidencePreset, reset = 0): EvidenceView {
  const view = cleanEvidenceView(reset);
  const included = preset === "Decision" ? ["support", "resistance", "bos", "mss", "entry", "tp", "sl"] : preset === "Structure" ? ["swing", "bos", "mss", "entry", "tp", "sl"] : EVIDENCE_LAYERS;
  return { ...view, preset, visible: Object.fromEntries(EVIDENCE_LAYERS.map(layer => [layer, included.includes(layer)])) as Record<EvidenceLayer, boolean> };
}
export function decisionEvidenceView(reset = 0): EvidenceView { return presetEvidenceView("Decision", reset); }
export function layerVisible(layer: EvidenceLayer, view: EvidenceView): boolean {
  if (!view.visible[layer]) return false;
  if (["entry", "tp", "sl"].includes(layer)) return true;
  return view.focus === "All" || (view.focus === "Structure" && ["swing", "bos", "mss"].includes(layer)) ||
    (view.focus === "Liquidity" && ["swing", "support", "resistance"].includes(layer)) ||
    (view.focus === "Zones" && ["support", "resistance", "fvg", "ob"].includes(layer));
}
export interface EvidenceRecord { key: string; layer: EvidenceLayer; label: string; detail: unknown }
export function evidenceRecords(analysis: AnalysisViewModel | null, signal: SignalViewModel | null): EvidenceRecord[] {
  const rows: EvidenceRecord[] = [];
  // Presentation keys remain stable when stale analysis or signal is independently suppressed.
  const indices = Object.fromEntries(EVIDENCE_LAYERS.map(layer => [layer, 0])) as Record<EvidenceLayer, number>;
  const add = (layer: EvidenceLayer, label: string, detail: unknown) => rows.push({ key: `${layer}:${indices[layer]++}`, layer, label, detail });
  analysis?.supports.forEach((item) => add("support", item.id, item));
  analysis?.resistances.forEach((item) => add("resistance", item.id, item));
  analysis?.swings.forEach((item) => add("swing", `${item.kind} · ${item.id}`, item));
  analysis?.structures.forEach((item) => add(item.type === "BOS" ? "bos" : "mss", item.id, item));
  analysis?.zones.forEach((item) => add(item.kind === "FVG" ? "fvg" : "ob", `${item.id} · ${item.lifecycleState}`, item));
  if (signal && signal.finalDecision !== "NO_TRADE" && signal.entryMin !== null && signal.entryMax !== null) {
    add("entry", "Entry", signal.sourceEvidence ?? signal);
    if (signal.takeProfit !== null) add("tp", "TP", signal.sourceEvidence ?? signal);
    if (signal.stopLoss !== null) add("sl", "SL", signal.sourceEvidence ?? signal);
  }
  return rows;
}
export function evidenceCounts(rows: EvidenceRecord[]): Record<EvidenceLayer, number> {
  const counts = Object.fromEntries(EVIDENCE_LAYERS.map((layer) => [layer, 0])) as Record<EvidenceLayer, number>;
  for (const row of rows) counts[row.layer]++;
  return counts;
}

export interface LabelBox { x: number; y: number; width: number; height: number }
/** Screen-space collision avoidance only. Original evidence/time/lifecycle is never rewritten. */
export function acceptLabel(box: LabelBox, occupied: LabelBox[], width: number, height: number): boolean {
  if (box.x < 0 || box.y < 0 || box.x + box.width > width || box.y + box.height > height) return false;
  if (occupied.some((other) => box.x < other.x + other.width + 8 && box.x + box.width + 8 > other.x && box.y < other.y + other.height + 6 && box.y + box.height + 6 > other.y)) return false;
  occupied.push(box);
  return true;
}

export function rawEvidenceDetail(row: EvidenceRecord, source: unknown): unknown {
  if (!source || typeof source !== "object" || !("evaluation" in source)) return row.detail;
  const evaluation = source.evaluation as { market_structure_snapshot?: Record<string, { confirmed_swings?: unknown[]; structure_events?: unknown[]; support_candidates?: unknown[]; resistance_candidates?: unknown[] }>; smc_ict_snapshot?: { fvg?: { zones?: unknown[] }; order_blocks?: { order_blocks?: unknown[] } } };
  const structure = evaluation.market_structure_snapshot?.["15m"];
  const candidates = row.layer === "swing" ? structure?.confirmed_swings : row.layer === "support" ? structure?.support_candidates : row.layer === "resistance" ? structure?.resistance_candidates : ["bos", "mss"].includes(row.layer) ? structure?.structure_events : row.layer === "fvg" ? evaluation.smc_ict_snapshot?.fvg?.zones : row.layer === "ob" ? evaluation.smc_ict_snapshot?.order_blocks?.order_blocks : undefined;
  const detail = row.detail as { id?: string };
  return candidates?.find((candidate) => {
    if (!candidate || typeof candidate !== "object") return false;
    const value = candidate as Record<string, unknown>;
    return value.swing_id === detail.id || value.zone_id === detail.id || `${value.type}:${value.broken_structure_id}:${value.confirmed_at}` === detail.id;
  }) ?? row.detail;
}
