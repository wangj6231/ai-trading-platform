import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SignalPanel } from "@/components/signal-panel";
import type { SignalViewModel } from "@/types/trading";

const signal: SignalViewModel = {
  symbol: "BTCUSDT",
  timeframe: "5m",
  decisionMode: "DETERMINISTIC_ONLY",
  aiValidationStatus: "NOT_REQUESTED",
  algorithmDecision: "LONG",
  aiDecision: null,
  finalDecision: "LONG",
  entryMin: 100,
  entryMax: 102,
  takeProfit: 108,
  stopLoss: 98,
  confidence: null,
  riskReward: 1.6,
  reason: ["Deterministic candidate"],
  factors: { MACD: "confirmed", SMC: "confirmed", ICT: "mixed", "S/R": "confirmed" },
  validatedAt: "2025-01-01T00:00:00Z",
};

describe("SignalPanel", () => {
  it("does not label a deterministic-only candidate as AI validated", () => {
    render(
      <SignalPanel
        state={{ status: "ready", data: signal }}
        symbol="BTCUSDT"
        timeframe="5m"
        onRetry={() => undefined}
      />,
    );

    expect(screen.getByText("DETERMINISTIC CANDIDATE")).toBeInTheDocument();
    expect(screen.getByText("AI NOT REQUESTED")).toBeInTheDocument();
    expect(screen.queryByText("AI SIGNAL")).not.toBeInTheDocument();
    expect(screen.queryByText("SECONDARY VALIDATION")).not.toBeInTheDocument();
  });

  it("renders one take profit and never multi-target labels", () => {
    render(<SignalPanel state={{ status: "ready", data: signal }} symbol="BTCUSDT" timeframe="5m" onRetry={() => undefined} />);

    expect(screen.getByText("BUY")).toBeInTheDocument();
    expect(screen.getAllByText("TAKE PROFIT")).toHaveLength(1);
    expect(screen.queryByText(/TP1|TP2|TP3/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\d+%/)).not.toBeInTheDocument();
    expect(screen.getByText("1 : 1.6")).toBeInTheDocument();
  });

  it("renders explicit no-signal state without fabricated levels", () => {
    render(<SignalPanel state={{ status: "empty" }} symbol="XAUUSD" timeframe="5m" onRetry={() => undefined} />);

    expect(screen.getByText("NO DETERMINISTIC SIGNAL")).toBeInTheDocument();
    expect(screen.queryByText("TAKE PROFIT")).not.toBeInTheDocument();
    expect(screen.queryByText("STOP LOSS")).not.toBeInTheDocument();
  });

  it("renders a validated NO_TRADE without BUY or SELL", () => {
    const noTrade: SignalViewModel = {
      ...signal,
      algorithmDecision: "NO_TRADE",
      aiDecision: null,
      finalDecision: "NO_TRADE",
      entryMin: null,
      entryMax: null,
      takeProfit: null,
      stopLoss: null,
      riskReward: null,
      reason: ["Risk engine rejected the setup"],
    };
    render(<SignalPanel state={{ status: "ready", data: noTrade }} symbol="BTCUSDT" timeframe="5m" onRetry={() => undefined} />);

    expect(screen.getAllByText("NO TRADE").length).toBeGreaterThan(0);
    expect(screen.queryByText("BUY")).not.toBeInTheDocument();
    expect(screen.queryByText("SELL")).not.toBeInTheDocument();
    expect(screen.queryByText("TAKE PROFIT")).not.toBeInTheDocument();
  });

  it("renders loading and retryable error states", () => {
    const retry = vi.fn();
    const { rerender } = render(<SignalPanel state={{ status: "loading" }} symbol="ETHUSDT" timeframe="15m" onRetry={retry} />);
    expect(screen.getByLabelText("Loading signal")).toBeInTheDocument();

    rerender(<SignalPanel state={{ status: "error", message: "Backend unavailable" }} symbol="ETHUSDT" timeframe="15m" onRetry={retry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Backend unavailable");
    fireEvent.click(screen.getByRole("button", { name: "RETRY" }));
    expect(retry).toHaveBeenCalledOnce();
  });
});
