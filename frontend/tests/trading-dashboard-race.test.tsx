import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchAnalysis, fetchCandles, fetchLatestSignal } from "@/lib/api";
import { TradingDashboard } from "@/components/trading-dashboard";
import type { MarketDataResponse, SignalViewModel } from "@/types/trading";

vi.mock("@/lib/api", () => ({
  fetchAnalysis: vi.fn(),
  fetchCandles: vi.fn(),
  fetchLatestSignal: vi.fn(),
}));

vi.mock("@/components/price-chart", () => ({
  PriceChart: () => <div data-testid="price-chart" />,
}));

vi.mock("@/components/macd-chart", () => ({
  MacdChart: () => <div data-testid="macd-chart" />,
}));

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason?: unknown) => void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, resolve, reject };
}

function signal(symbol: "BTCUSDT" | "ETHUSDT"): SignalViewModel {
  return {
    symbol,
    timeframe: "5m",
    decisionMode: "DETERMINISTIC_ONLY",
    aiValidationStatus: "NOT_REQUESTED",
    algorithmDecision: "LONG",
    aiDecision: null,
    finalDecision: "LONG",
    entryMin: 100,
    entryMax: 101,
    takeProfit: 110,
    stopLoss: 95,
    confidence: null,
    riskReward: 2,
    reason: ["deterministic candidate"],
    factors: {},
    validatedAt: "2025-01-01T00:00:00Z",
  };
}

function noTradeSignal(symbol: "BTCUSDT" | "ETHUSDT"): SignalViewModel {
  return {
    ...signal(symbol),
    algorithmDecision: "NO_TRADE",
    aiDecision: null,
    finalDecision: "NO_TRADE",
    entryMin: null,
    entryMax: null,
    takeProfit: null,
    stopLoss: null,
    riskReward: null,
    reason: ["Deterministic safety rejection"],
  };
}

describe("TradingDashboard request lifecycle", () => {
  beforeEach(() => {
    vi.mocked(fetchAnalysis).mockReset();
    vi.mocked(fetchCandles).mockReset();
    vi.mocked(fetchLatestSignal).mockReset();
  });

  it("ignores a stale signal response after the selection changes", async () => {
    const btcSignal = deferred<SignalViewModel>();
    const ethSignal = deferred<SignalViewModel>();
    const btcMarket = deferred<MarketDataResponse>();
    const ethMarket = deferred<MarketDataResponse>();

    vi.mocked(fetchLatestSignal).mockImplementation((symbolCode) =>
      symbolCode === "BTCUSDT" ? btcSignal.promise : ethSignal.promise,
    );
    vi.mocked(fetchCandles).mockImplementation((symbolCode) =>
      symbolCode === "BTCUSDT" ? btcMarket.promise : ethMarket.promise,
    );

    render(<TradingDashboard />);
    await waitFor(() => expect(fetchLatestSignal).toHaveBeenCalledWith("BTCUSDT", "5m", expect.any(AbortSignal)));
    const staleSignal = vi.mocked(fetchLatestSignal).mock.calls[0][2];
    const staleMarket = vi.mocked(fetchCandles).mock.calls[0][2];

    fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "ETHUSDT" } });
    await waitFor(() => expect(fetchLatestSignal).toHaveBeenCalledWith("ETHUSDT", "5m", expect.any(AbortSignal)));
    expect(staleSignal?.aborted).toBe(true);
    expect(staleMarket?.aborted).toBe(true);

    await act(async () => btcSignal.resolve(signal("BTCUSDT")));

    const panel = screen.getByLabelText("Deterministic signal panel");
    expect(within(panel).getByText("ETHUSDT")).toBeInTheDocument();
    expect(within(panel).getByLabelText("Loading signal")).toBeInTheDocument();
    expect(within(panel).queryByText("BUY")).not.toBeInTheDocument();

    await act(async () => ethSignal.resolve(signal("ETHUSDT")));
    expect(within(panel).getByText("ETHUSDT")).toBeInTheDocument();
    expect(within(panel).getByText("BUY")).toBeInTheDocument();
  });

  it("aborts all active dashboard requests when it unmounts", async () => {
    const pendingSignal = deferred<SignalViewModel>();
    const pendingMarket = deferred<MarketDataResponse>();
    vi.mocked(fetchLatestSignal).mockReturnValue(pendingSignal.promise);
    vi.mocked(fetchCandles).mockReturnValue(pendingMarket.promise);

    const { unmount } = render(<TradingDashboard />);
    await waitFor(() => expect(fetchCandles).toHaveBeenCalledOnce());
    const signalAbort = vi.mocked(fetchLatestSignal).mock.calls[0][2];
    const marketAbort = vi.mocked(fetchCandles).mock.calls[0][2];

    expect(signalAbort?.aborted).toBe(false);
    expect(marketAbort?.aborted).toBe(false);
    unmount();
    expect(signalAbort?.aborted).toBe(true);
    expect(marketAbort?.aborted).toBe(true);
  });

  it("renders a current backend timeout as a technical error, not NO TRADE", async () => {
    vi.mocked(fetchLatestSignal).mockRejectedValue(new Error("Backend request timed out."));
    vi.mocked(fetchCandles).mockReturnValue(new Promise(() => undefined));

    render(<TradingDashboard />);

    const panel = screen.getByLabelText("Deterministic signal panel");
    await waitFor(() => expect(within(panel).getByRole("alert")).toHaveTextContent("Backend request timed out."));
    expect(within(panel).queryByText("BUY")).not.toBeInTheDocument();
    expect(within(panel).queryByText("SELL")).not.toBeInTheDocument();
    expect(within(panel).queryByText("NO TRADE")).not.toBeInTheDocument();
  });

  it("does not let an obsolete timeout replace the newer loading state", async () => {
    const btcSignal = deferred<SignalViewModel>();
    const ethSignal = deferred<SignalViewModel>();
    vi.mocked(fetchLatestSignal).mockImplementation((symbolCode) =>
      symbolCode === "BTCUSDT" ? btcSignal.promise : ethSignal.promise,
    );
    vi.mocked(fetchCandles).mockReturnValue(new Promise(() => undefined));

    render(<TradingDashboard />);
    await waitFor(() => expect(fetchLatestSignal).toHaveBeenCalledWith("BTCUSDT", "5m", expect.any(AbortSignal)));

    fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "ETHUSDT" } });
    await waitFor(() => expect(fetchLatestSignal).toHaveBeenCalledWith("ETHUSDT", "5m", expect.any(AbortSignal)));
    await act(async () => btcSignal.reject(new Error("Backend request timed out.")));

    const panel = screen.getByLabelText("Deterministic signal panel");
    expect(within(panel).getByText("ETHUSDT")).toBeInTheDocument();
    expect(within(panel).getByLabelText("Loading signal")).toBeInTheDocument();
    expect(within(panel).queryByRole("alert")).not.toBeInTheDocument();

    await act(async () => ethSignal.resolve(signal("ETHUSDT")));
    expect(within(panel).getByText("BUY")).toBeInTheDocument();
  });

  it("clears the previous symbol signal when the new symbol request fails", async () => {
    vi.mocked(fetchLatestSignal).mockImplementation((symbolCode) =>
      symbolCode === "BTCUSDT"
        ? Promise.resolve(signal("BTCUSDT"))
        : Promise.reject(new Error("Backend service is unavailable.")),
    );
    vi.mocked(fetchCandles).mockReturnValue(new Promise(() => undefined));

    render(<TradingDashboard />);
    const panel = screen.getByLabelText("Deterministic signal panel");
    await waitFor(() => expect(within(panel).getByText("BUY")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "ETHUSDT" } });

    await waitFor(() => expect(within(panel).getByRole("alert")).toHaveTextContent("Backend service is unavailable."));
    expect(within(panel).getByText("ETHUSDT")).toBeInTheDocument();
    expect(within(panel).queryByText("BUY")).not.toBeInTheDocument();
    expect(within(panel).queryByText("SELL")).not.toBeInTheDocument();
  });

  it("retry starts a new request cycle with a new AbortController", async () => {
    vi.mocked(fetchLatestSignal)
      .mockRejectedValueOnce(new Error("Backend request timed out."))
      .mockResolvedValueOnce(signal("BTCUSDT"));
    vi.mocked(fetchCandles).mockRejectedValue(new Error("Backend service is unavailable."));

    render(<TradingDashboard />);
    const panel = screen.getByLabelText("Deterministic signal panel");
    await waitFor(() => expect(within(panel).getByRole("alert")).toBeInTheDocument());
    const firstSignal = vi.mocked(fetchLatestSignal).mock.calls[0][2];

    fireEvent.click(within(panel).getByRole("button", { name: "RETRY" }));

    await waitFor(() => expect(fetchLatestSignal).toHaveBeenCalledTimes(2));
    const secondSignal = vi.mocked(fetchLatestSignal).mock.calls[1][2];
    expect(firstSignal).not.toBe(secondSignal);
    expect(firstSignal?.aborted).toBe(true);
    expect(secondSignal?.aborted).toBe(false);
    await waitFor(() => expect(within(panel).getByText("BUY")).toBeInTheDocument());
  });

  it("renders successful NO_TRADE as a strategy result rather than an error", async () => {
    vi.mocked(fetchLatestSignal).mockResolvedValue(noTradeSignal("BTCUSDT"));
    vi.mocked(fetchCandles).mockReturnValue(new Promise(() => undefined));

    render(<TradingDashboard />);

    const panel = screen.getByLabelText("Deterministic signal panel");
    await waitFor(() => expect(within(panel).getAllByText("NO TRADE").length).toBeGreaterThan(0));
    expect(within(panel).queryByRole("alert")).not.toBeInTheDocument();
    expect(within(panel).queryByText("BUY")).not.toBeInTheDocument();
    expect(within(panel).queryByText("SELL")).not.toBeInTheDocument();
  });
});
