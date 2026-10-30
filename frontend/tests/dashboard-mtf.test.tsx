import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TradingDashboard } from "@/components/trading-dashboard";
import { TIMEFRAMES } from "@/types/trading";
import { analysisFixture, signalFixture } from "./fixtures/mtf-contract";
import { evaluationFixture } from "./fixtures/evaluation-job";
import { MTFEvidencePanel } from "@/components/mtf-evidence-panel";
import { normalizeAnalysis } from "@/lib/api";

vi.mock("@/components/price-chart", () => ({ PriceChart: () => <div /> }));
vi.mock("@/components/macd-chart", () => ({ MacdChart: () => <div /> }));

function network(chartFails = false, analysisPayload = analysisFixture, signalPayload = signalFixture) {
  const fetchMock = vi.fn(async (url: string) => {
    if (url === "/api/evaluations") return Response.json(evaluationFixture(), { status: 202 });
    if (url.endsWith("/signal")) return Response.json(signalPayload);
    if (url.endsWith("/analysis")) return Response.json(analysisPayload);
    if (chartFails) return Response.json({ error: { code: "MARKET_DATA_STALE", message: "Chart feed stale." } }, { status: 503 });
    const timeframe = new URL(url, "http://localhost").searchParams.get("timeframe");
    return Response.json({ symbol: "BTCUSDT", timeframe, source: signalFixture.source,
      retrieved_at: signalFixture.retrieved_at,
      provenance: { ...signalFixture.provenance, timeframe, received_candles: 1 },
      candles: [{ timestamp: "2025-01-01T00:15:00Z", open: 100, high: 102, low: 99, close: 101, volume: 1 }],
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("chart-only selection authority", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("all ten display selections retain the same strategy and never refetch it", async () => {
    const requests = network();
    render(<TradingDashboard />);
    const panel = screen.getByLabelText("Deterministic signal panel");
    await waitFor(() => expect(within(panel).getByText("LONG")).toBeInTheDocument());
    await waitFor(() => expect(within(panel).getByText("fixture-strategy-v1")).toBeInTheDocument());
    for (const timeframe of TIMEFRAMES) {
      fireEvent.click(screen.getByRole("button", { name: timeframe.toUpperCase() }));
      await waitFor(() => expect(requests.mock.calls.some(([url]) => url.includes(`timeframe=${timeframe}`))).toBe(true));
      expect(within(panel).getByText("LONG")).toBeInTheDocument();
      expect(panel.querySelector(".signal-market")).toHaveTextContent("15M");
      expect(within(panel).getByText("fixture-strategy-v1")).toBeInTheDocument();
      expect(within(panel).getByText(signalFixture.data_cutoff_at)).toBeInTheDocument();
    }
    expect(requests.mock.calls.filter(([url]) => url === "/api/evaluations")).toHaveLength(1);
    expect(requests.mock.calls.filter(([url]) => url === "/api/signals" || url === "/api/analysis")).toHaveLength(0);
  }, 15_000);
  it("chart failure does not disable independent strategy evidence or invent NO_TRADE", async () => {
    network(true);
    render(<TradingDashboard />);
    await waitFor(() => expect(screen.getByText("LONG")).toBeInTheDocument());
    expect(screen.getByText("Chart feed stale.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("fixture-strategy-v1")).toBeInTheDocument());
    expect(screen.queryByText("NO_TRADE")).not.toBeInTheDocument();
  });
  it("context only displays no authority; unavailable, stale and warmup remain distinct", async () => {
    network();
    render(<TradingDashboard />);
    await waitFor(() => expect(screen.getByText("fixture-strategy-v1")).toBeInTheDocument());
    const context = document.querySelector('[data-mtf-timeframe="1w"]');
    expect(context).toHaveTextContent("CONTEXT ONLY · NO ALIGNMENT / VETO AUTHORITY");
    expect(context).toHaveTextContent("UNAVAILABLE · NOT READY");
    expect(context).not.toHaveTextContent("REQUIRED");
  });
  it("renders stale optional context without inventing a strategy veto", async () => {
    const payload = structuredClone(analysisFixture);
    payload.evaluation.multi_timeframe_result.timeframes["2h"].stale = true;
    payload.evaluation.multi_timeframe_result.timeframes["2h"].reason_codes = ["MTF_STATE_STALE"];
    network(false, payload);
    render(<TradingDashboard />);
    await waitFor(() => expect(document.querySelector('[data-mtf-timeframe="2h"]')).toHaveTextContent("STALE"));
    expect(screen.getByText("LONG")).toBeInTheDocument();
    expect(screen.queryByText("NO_TRADE")).not.toBeInTheDocument();
  });
  it("does not attach identity/MTF from another cutoff", async () => {
    const laterAnalysis = structuredClone(analysisFixture);
    laterAnalysis.data_cutoff_at = "2025-01-01T00:45:00Z";
    laterAnalysis.provenance = { ...laterAnalysis.provenance, data_cutoff_at: laterAnalysis.data_cutoff_at };
    laterAnalysis.evaluation.as_of = laterAnalysis.data_cutoff_at;
    laterAnalysis.evaluation.data_cutoff_at = laterAnalysis.data_cutoff_at;
    laterAnalysis.evaluation.multi_timeframe_result.decision_time = laterAnalysis.data_cutoff_at;
    network(false, laterAnalysis);
    render(<TradingDashboard />);
    await waitFor(() => expect(screen.getAllByText(/Completed results do not match/).length).toBeGreaterThan(0));
    expect(screen.queryByText("LONG")).not.toBeInTheDocument();
    expect(screen.queryByText("fixture-strategy-v1")).not.toBeInTheDocument();
  });
  it("malformed signal is a backend contract error, not an actionable or invented strategy result", async () => {
    network(false, analysisFixture, { ...signalFixture, timeframe: "1m" });
    render(<TradingDashboard />);
    await waitFor(() => expect(screen.getByText("BACKEND CONTRACT INVALID")).toBeInTheDocument());
    expect(screen.queryByText("LONG")).not.toBeInTheDocument();
    expect(screen.queryByText("NO_TRADE")).not.toBeInTheDocument();
  });
  it("absent MTF evidence does not fabricate an unavailable or not-ready server state", () => {
    const strategy = normalizeAnalysis(analysisFixture, "BTCUSDT").strategy!;
    render(<MTFEvidencePanel provenance={{ ...strategy, mtf: null }} />);
    expect(screen.getByLabelText("MTF evidence")).toHaveTextContent("Readiness is unknown");
    expect(document.querySelectorAll("[data-mtf-timeframe]")).toHaveLength(0);
    expect(screen.queryByText(/NOT READY/)).not.toBeInTheDocument();
  });
});
