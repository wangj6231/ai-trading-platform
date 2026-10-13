import { EVIDENCE_LAYERS, type EvidenceLayer } from "./chart-evidence";

export interface LayerDensity { source: number; viewport: number; renderedSource: number; offscreen: number; unavailable: number; visuals: number; clusters: number; staleSuppressed?: number }
export type EvidenceDensity = Record<EvidenceLayer, LayerDensity>;
export interface EvidenceProjection { sources: ReadonlySet<string>; projectable: ReadonlySet<string>; viewport: ReadonlySet<string>; rendered: ReadonlySet<string> }
export function archiveDensity(density: EvidenceDensity | undefined, counts: Record<EvidenceLayer, number>): EvidenceDensity | undefined {
  if (!density) return undefined;
  return Object.fromEntries(EVIDENCE_LAYERS.map(layer => { const staleSuppressed = Math.max(0, counts[layer] - density[layer].source); return [layer, { ...density[layer], source: counts[layer], unavailable: density[layer].unavailable + staleSuppressed, staleSuppressed }]; })) as EvidenceDensity;
}
export function emptyDensity(): EvidenceDensity {
  return Object.fromEntries(EVIDENCE_LAYERS.map(layer => [layer, { source: 0, viewport: 0, renderedSource: 0, offscreen: 0, unavailable: 0, visuals: 0, clusters: 0 }])) as EvidenceDensity;
}
/** Pixel spacing, never a ranked/top-N source selection. More room per bar reveals members. */
export function densityCells(width: number, height: number, logicalSpan: number) {
  const barPixels = width / Math.max(1, logicalSpan);
  const pressure = Math.sqrt(Math.max(1, logicalSpan) / Math.max(1, width * height / (36 * 36)));
  const room = width * height / (90 * 60) * Math.min(2, Math.max(.5, Math.sqrt(barPixels / 6)));
  return { markerBudget: Math.max(3, Math.floor(room)), zoneBudget: Math.max(10, Math.floor(room)), markerX: barPixels >= 14 ? 10 : Math.min(70, Math.max(24, 36 * pressure)), markerY: barPixels >= 14 ? 14 : 28,
    referenceY: Math.max(10, Math.min(42, 22 * Math.max(.5, pressure))), zoneX: Math.max(18, Math.min(72, 36 * pressure)), zoneY: Math.max(14, Math.min(48, 28 * pressure)) };
}
/** Coarsen screen cells until every member fits the pixel budget. No member is discarded. */
export function aggregateGeometry<T>(items: T[], bucket: (item: T, scale: number) => string, budget: number): T[][] {
  let scale = 1, groups = groupGeometry(items, item => bucket(item, scale));
  while (groups.length > budget) { scale *= 2; groups = groupGeometry(items, item => bucket(item, scale)); }
  return groups;
}
/** Preserve object references, every member, and an original representative (no averaged price/time). */
export function groupGeometry<T>(items: T[], bucket: (item: T) => string): T[][] {
  const groups = new Map<string, T[]>();
  for (const item of items) { const key = bucket(item); const group = groups.get(key); if (group) group.push(item); else groups.set(key, [item]); }
  return [...groups.values()];
}
export function intersectsViewport(x1: number, x2: number, y1: number, y2: number, width: number, height: number): boolean {
  return x2 >= x1 && x2 >= 0 && x1 <= width && Math.max(y1, y2) >= 0 && Math.min(y1, y2) <= height;
}
