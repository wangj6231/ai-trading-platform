import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { acceptLabel, cleanEvidenceView, evidenceCounts, evidenceRecords, EVIDENCE_LAYERS, FOCUS_MODES, layerVisible, rawEvidenceDetail } from "@/lib/chart-evidence";
import { ChartEvidenceControls } from "@/components/chart-evidence-controls";
import { ChartEvidenceInspector } from "@/components/chart-evidence-inspector";
import { normalizeAnalysis, parseSignalPayload } from "@/lib/api";
import { analysisFixture, signalFixture } from "./fixtures/mtf-contract";

describe("Evidence presentation retains authority and complete data", () => {
  it("retains the exact original validated response reference including unprojected fields", () => {
    const payload = { ...structuredClone(analysisFixture), evaluation: { ...structuredClone(analysisFixture.evaluation), market_structure_snapshot: { "15m": { confirmed_swings: [{ swing_id: "server-original", kind: "HIGH", pivot_timestamp: "2025-01-01T00:00:00Z", confirmed_at: "2025-01-01T00:15:00Z", price: 105, untouched_backend_field: "preserved" }], structure_events: [], support_candidates: [], resistance_candidates: [] } } } };
    const original = JSON.stringify(payload);
    const analysis = normalizeAnalysis(payload, "BTCUSDT");
    const signal = parseSignalPayload(signalFixture, "BTCUSDT");
    expect(analysis.sourceEvidence).toBe(payload);
    expect(signal.sourceEvidence).toBe(signalFixture);
    expect(JSON.stringify(payload)).toBe(original);
    const rows = evidenceRecords(analysis, signal);
    const counts = evidenceCounts(rows);
    expect(counts.swing).toBe(analysis.swings.length);
    expect(counts.fvg).toBe(analysis.zones.filter((zone) => zone.kind === "FVG").length);
    expect(counts.bos + counts.mss).toBe(analysis.structures.length);
    expect(counts.entry).toBe(1);
    expect(EVIDENCE_LAYERS.reduce((sum, layer) => sum + counts[layer], 0)).toBe(rows.length);
    const swing = rows.find((row) => row.layer === "swing")!;
    expect(rawEvidenceDetail(swing, payload)).toBe(payload.evaluation.market_structure_snapshot["15m"].confirmed_swings[0]);
  });
  it("Clean View hides secondary text while each layer remains enabled", () => {
    const view = cleanEvidenceView();
    expect(view.labels.swing).toBe(false);
    expect(view.labels.fvg).toBe(false);
    expect(view.labels.ob).toBe(false);
    expect(view.labels.bos && view.labels.mss && view.labels.entry && view.labels.tp && view.labels.sl).toBe(true);
    expect(EVIDENCE_LAYERS.every((layer) => layerVisible(layer, view))).toBe(true);
  });
  it.each(FOCUS_MODES)("%s focus retains enabled trade and supports independent layer toggles", (focus) => {
    const view = { ...cleanEvidenceView(), focus };
    for (const layer of ["entry", "tp", "sl"] as const) expect(layerVisible(layer, view)).toBe(true);
    for (const layer of EVIDENCE_LAYERS) expect(layerVisible(layer, { ...view, visible: { ...view.visible, [layer]: false } })).toBe(false);
    if (focus === "Structure") { expect(layerVisible("mss", view)).toBe(true); expect(layerVisible("fvg", view)).toBe(false); }
    if (focus === "Liquidity") { expect(layerVisible("swing", view)).toBe(true); expect(layerVisible("bos", view)).toBe(false); }
    if (focus === "Zones") { expect(layerVisible("ob", view)).toBe(true); expect(layerVisible("swing", view)).toBe(false); }
    if (focus === "Trade") expect(layerVisible("support", view)).toBe(false);
  });
  it("rejects overlapping/offscreen text boxes and permits newly separated labels after zoom", () => {
    const boxes: { x: number; y: number; width: number; height: number }[] = [];
    expect(acceptLabel({ x: 10, y: 10, width: 80, height: 20 }, boxes, 300, 200)).toBe(true);
    expect(acceptLabel({ x: 40, y: 10, width: 80, height: 20 }, boxes, 300, 200)).toBe(false);
    expect(acceptLabel({ x: 110, y: 10, width: 80, height: 20 }, boxes, 300, 200)).toBe(true);
    expect(acceptLabel({ x: 290, y: 10, width: 80, height: 20 }, boxes, 300, 200)).toBe(false);
  });
  it("controls report original item counts and reset exact Clean View", () => {
    const onChange = vi.fn();
    const view = { ...cleanEvidenceView(), focus: "Trade" as const, reset: 4 };
    render(<ChartEvidenceControls view={view} counts={{ ...evidenceCounts([]), swing: 500 }} onChange={onChange} onInspect={vi.fn()} />);
    fireEvent.click(screen.getByText(/Layers & labels/));
    expect(screen.getByLabelText("Swing H/L layer").closest("label")).toHaveTextContent("500");
    fireEvent.click(screen.getByRole("button", { name: "Reset View" }));
    expect(onChange).toHaveBeenCalledWith(cleanEvidenceView(5));
  });
  it("missing evaluation data shows unknown counts rather than inventing zero evidence", () => {
    render(<ChartEvidenceControls view={cleanEvidenceView()} counts={evidenceCounts([])} available={false} onChange={vi.fn()} onInspect={vi.fn()} />);
    fireEvent.click(screen.getByText(/Layers & labels/));
    expect(screen.getByLabelText("Swing H/L layer").closest("label")).toHaveTextContent("—");
    expect(screen.getByRole("button", { name: "Browse all evidence" })).toBeDisabled();
  });
  it("all cluster members and the last original archive entry are reachable by pagination", () => {
    const rows = Array.from({ length: 51 }, (_, index) => ({ key: `swing:${index}`, layer: "swing" as const, label: `server-${index}`, detail: { id: `server-${index}`, confirmedAt: "2025-01-01T00:15:00Z" } }));
    render(<ChartEvidenceInspector rows={rows} selection={rows.map((row) => row.key)} source={{ untouched: Array.from({ length: 51 }, (_, index) => ({ original_field: `last-${index}` })) }} stale onClose={vi.fn()} />);
    expect(screen.getByText("Selected evidence · 51")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Next evidence" }));
    fireEvent.click(screen.getByRole("button", { name: "Next evidence" }));
    expect(document.querySelector('[data-evidence-key="swing:50"] > summary')).toHaveTextContent("server-50");
    fireEvent.click(screen.getByText(/Complete original API evidence/));
    fireEvent.click(screen.getByText("untouched", { exact: true }));
    fireEvent.click(screen.getByRole("button", { name: "Next fields" }));
    fireEvent.click(screen.getByRole("button", { name: "Next fields" }));
    fireEvent.click(screen.getByText("50", { exact: true }));
    fireEvent.click(screen.getByText("original_field", { exact: true }));
    expect(screen.getByText('"last-50"')).toBeVisible();
  });
});
