import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { decisionEvidenceView, EVIDENCE_LAYERS, layerVisible, presetEvidenceView, evidenceCounts, evidenceRecords } from "@/lib/chart-evidence";
import { aggregateGeometry, archiveDensity, densityCells, emptyDensity, groupGeometry, intersectsViewport } from "@/lib/chart-density";
import { ChartEvidenceControls } from "@/components/chart-evidence-controls";
import { normalizeAnalysis, parseSignalPayload } from "@/lib/api";
import { analysisFixture, signalFixture } from "./fixtures/mtf-contract";

describe("V3 presentation density, never strategy selection", () => {
  it("Decision hides archives; Structure and All preserve independently selectable sources", () => {
    const decision = decisionEvidenceView();
    expect(EVIDENCE_LAYERS.filter(layer => layerVisible(layer, decision))).toEqual(["support", "resistance", "bos", "mss", "entry", "tp", "sl"]);
    expect(layerVisible("swing", presetEvidenceView("Structure"))).toBe(true);
    expect(layerVisible("support", presetEvidenceView("Structure"))).toBe(false);
    expect(EVIDENCE_LAYERS.every(layer => layerVisible(layer, presetEvidenceView("All Evidence")))).toBe(true);
  });
  it("aggregation retains every exact object/price/timestamp, including the last member", () => {
    const sources = Array.from({ length: 7630 }, (_, id) => ({ id: `server-${id}`, price: 83000 + id / 10, confirmedAt: `original-${id}` }));
    const before = JSON.stringify(sources);
    const groups = groupGeometry(sources, source => String(Math.floor(source.price / 100)));
    expect(groups.flat()).toEqual(sources);
    expect(groups.at(-1)!.at(-1)).toBe(sources.at(-1));
    expect(JSON.stringify(sources)).toBe(before);
    expect(groups.length).toBeLessThan(sources.length);
  });
  it("coarsens intersecting zones to a pixel budget without dropping any member", () => {
    const sources = Array.from({ length: 1000 }, (_, index) => ({ id: index, x: index % 300, y: index % 200 }));
    const groups = aggregateGeometry(sources, (source, scale) => `${Math.floor(source.x / (10 * scale))}:${Math.floor(source.y / (10 * scale))}`, 12);
    expect(groups.length).toBeLessThanOrEqual(12);
    expect(groups.flat().map(source => source.id).sort((a,b) => a-b)).toEqual(sources.map(source => source.id));
  });
  it("partial stale suppression keeps trade Inspector keys and explicit archive counts", () => {
    const analysis = { ...normalizeAnalysis(analysisFixture, "BTCUSDT"), supports: [{ id: "explicit-test-support", lower: 95, upper: 96, anchorPrice: 95, label: "SUPPORT", createdAt: "2025-01-01T00:00:00Z", confirmedAt: null }] }, signal = parseSignalPayload(signalFixture, "BTCUSDT");
    const all = evidenceRecords(analysis, signal), tradeOnly = evidenceRecords(null, signal);
    expect(all.filter(row => ["entry", "tp", "sl"].includes(row.layer)).map(row => row.key)).toEqual(tradeOnly.map(row => row.key));
    const density = emptyDensity(), counts = evidenceCounts(all);
    density.entry = { source: 1, viewport: 1, renderedSource: 1, visuals: 1, clusters: 0, offscreen: 0, unavailable: 0 };
    const archive = archiveDensity(density, counts)!;
    expect(archive.entry.renderedSource).toBe(1);
    expect(archive.entry.staleSuppressed).toBe(0);
    expect(archive.support.source).toBe(counts.support);
    expect(archive.support.unavailable).toBe(counts.support);
    expect(archive.support.staleSuppressed).toBe(counts.support);
    expect(counts.support).toBe(1);
    const analysisOnly = emptyDensity(); analysisOnly.support = { source: 1, viewport: 1, renderedSource: 1, visuals: 1, clusters: 0, offscreen: 0, unavailable: 0 };
    expect(archiveDensity(analysisOnly, counts)!.entry.staleSuppressed).toBe(1);
    expect(archiveDensity(undefined,counts)).toBeUndefined();
  });
  it("pixel budgets adapt to width, height and visible logical span; zoom naturally separates members", () => {
    const desktop = densityCells(1300, 430, 500), mobile = densityCells(240, 330, 500), close = densityCells(1300, 430, 30);
    expect(mobile.markerX).toBeGreaterThan(desktop.markerX);
    expect(close.markerX).toBeLessThan(desktop.markerX);
    expect(densityCells(1300, 100, 500).referenceY).toBeGreaterThan(desktop.referenceY);
    expect(close.referenceY).toBeLessThan(desktop.referenceY);
  });
  it("viewport membership retains zero/subpixel terminal intersections without changing endpoints", () => {
    expect(intersectsViewport(0, 0, 100, 102, 300, 200)).toBe(true);
    expect(intersectsViewport(-20, .25, 100, 102, 300, 200)).toBe(true);
    expect(intersectsViewport(301, 302, 100, 102, 300, 200)).toBe(false);
    expect(intersectsViewport(-20, -1, 100, 102, 300, 200)).toBe(false);
    expect(intersectsViewport(10, 20, 201, 202, 300, 200)).toBe(false);
    expect(intersectsViewport(20, 10, 100, 102, 300, 200)).toBe(false);
  });
  it("compact toolbar resets Decision and reports separate source/viewport/render/cluster counts", () => {
    const onChange = vi.fn(), density = emptyDensity();
    density.support = { source: 7630, viewport: 214, renderedSource: 214, visuals: 18, clusters: 18, offscreen: 100, unavailable: 7316 };
    Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: function (this: HTMLDialogElement) { this.open = true; } });
    render(<ChartEvidenceControls view={presetEvidenceView("All Evidence", 3)} counts={{ ...evidenceCounts([]), support: 7630 }} density={density} onChange={onChange} onInspect={vi.fn()} />);
    expect(screen.queryByLabelText("Support layer")).toBeNull();
    fireEvent.change(screen.getByLabelText("Chart view"), { target: { value: "Structure" } });
    expect(onChange).toHaveBeenCalledWith(presetEvidenceView("Structure", 3));
    fireEvent.click(screen.getByRole("button", { name: "Layers & labels" }));
    expect(document.querySelector('[data-density-layer="support"]')).toHaveTextContent("7630 source · 214 viewport · 214 rendered source · 18 visuals (18 clusters)");
    fireEvent.click(screen.getByLabelText("Support layer"));
    expect(onChange.mock.calls.at(-1)?.[0].visible.support).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Reset View" }));
    expect(onChange).toHaveBeenLastCalledWith(decisionEvidenceView(4));
    vi.restoreAllMocks();
    Reflect.deleteProperty(HTMLDialogElement.prototype, "showModal");
  });
});
