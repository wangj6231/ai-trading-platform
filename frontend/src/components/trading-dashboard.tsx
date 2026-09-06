"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchAnalysis, fetchCandles, fetchLatestSignal } from "@/lib/api";
import { errorMessage, formatPrice, formatTimeframe } from "@/lib/format";
import type { AnalysisViewModel, LoadState, MacdPoint, MarketDataResponse, SignalViewModel, SymbolCode, Timeframe } from "@/types/trading";
import { MacdChart } from "./macd-chart";
import { OverlayLegend } from "./overlay-legend";
import { PriceChart } from "./price-chart";
import { SignalPanel } from "./signal-panel";
import { TopBar } from "./top-bar";

export function TradingDashboard() {
  const [symbol, setSymbol] = useState<SymbolCode>("BTCUSDT");
  const [timeframe, setTimeframe] = useState<Timeframe>("5m");
  const [market, setMarket] = useState<LoadState<MarketDataResponse>>({ status: "loading" });
  const [analysis, setAnalysis] = useState<LoadState<AnalysisViewModel>>({ status: "loading" });
  const [signal, setSignal] = useState<LoadState<SignalViewModel>>({ status: "loading" });
  const [requestVersion, setRequestVersion] = useState(0);

  const showLoading = useCallback(() => {
    setMarket({ status: "loading" });
    setAnalysis({ status: "loading" });
    setSignal({ status: "loading" });
  }, []);
  const retry = useCallback(() => {
    showLoading();
    setRequestVersion((value) => value + 1);
  }, [showLoading]);
  const selectSymbol = useCallback((next: SymbolCode) => {
    showLoading();
    setSymbol(next);
  }, [showLoading]);
  const selectTimeframe = useCallback((next: Timeframe) => {
    showLoading();
    setTimeframe(next);
  }, [showLoading]);

  useEffect(() => {
    const controller = new AbortController();

    void fetchLatestSignal(symbol, timeframe, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setSignal({ status: "ready", data });
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setSignal({ status: "error", message: errorMessage(error, "Signal service unavailable.") });
      });

    void fetchCandles(symbol, timeframe, controller.signal)
      .then(async (data) => {
        if (controller.signal.aborted) return;
        setMarket(data.candles.length ? { status: "ready", data } : { status: "empty" });
        if (!data.candles.length) { setAnalysis({ status: "empty" }); return; }
        try {
          const result = await fetchAnalysis(symbol, timeframe, controller.signal);
          if (!controller.signal.aborted) setAnalysis({ status: "ready", data: result });
        } catch (error) {
          if (!controller.signal.aborted) setAnalysis({ status: "error", message: errorMessage(error, "Analysis service unavailable.") });
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setMarket({ status: "error", message: errorMessage(error, "Market data unavailable.") });
          setAnalysis({ status: "error", message: "MACD requires valid closed candles." });
        }
      });
    return () => controller.abort();
  }, [symbol, timeframe, requestVersion]);

  const candles = market.status === "ready" ? market.data.candles : [];
  const latest = candles.length ? candles[candles.length - 1] : null;
  const previous = candles.length > 1 ? candles[candles.length - 2] : null;
  const lastPrice = latest ? Number(latest.close) : null;
  const change = latest && previous ? Number(latest.close) - Number(previous.close) : null;
  const changePercent = change !== null && previous ? (change / Number(previous.close)) * 100 : null;
  const analysisData = analysis.status === "ready" ? analysis.data : null;
  const signalData = signal.status === "ready" ? signal.data : null;
  const macdState = useMemo<LoadState<MacdPoint[]>>(() => {
    if (analysis.status === "loading") return { status: "loading" };
    if (analysis.status === "error") return { status: "error", message: analysis.message };
    if (analysis.status === "empty" || analysis.data.macd.length === 0) return { status: "empty" };
    return { status: "ready", data: analysis.data.macd };
  }, [analysis]);

  return (
    <main className="terminal-shell">
      <TopBar
        symbol={symbol}
        timeframe={timeframe}
        onSymbolChange={selectSymbol}
        onTimeframeChange={selectTimeframe}
        isLoading={market.status === "loading"}
        source={market.status === "ready" ? market.data.source : undefined}
      />

      <div className="workspace-grid">
        <section className="market-workspace">
          <div className="chart-header">
            <div className="instrument-summary">
              <div><h1>{symbol}</h1><span>{formatTimeframe(timeframe)} · SPOT MARKET</span></div>
              <strong>{formatPrice(lastPrice, lastPrice ?? undefined)}</strong>
              {change !== null && changePercent !== null && (
                <span className={change >= 0 ? "price-up" : "price-down"}>{change >= 0 ? "+" : ""}{formatPrice(change, lastPrice ?? undefined)} ({changePercent >= 0 ? "+" : ""}{changePercent.toFixed(2)}%)</span>
              )}
            </div>
            <div className="chart-meta">
              {latest && <><span>O <b>{formatPrice(Number(latest.open), lastPrice ?? undefined)}</b></span><span>H <b>{formatPrice(Number(latest.high), lastPrice ?? undefined)}</b></span><span>L <b>{formatPrice(Number(latest.low), lastPrice ?? undefined)}</b></span><span>C <b>{formatPrice(Number(latest.close), lastPrice ?? undefined)}</b></span></>}
            </div>
          </div>
          <OverlayLegend analysisAvailable={analysisData !== null} signalAvailable={signalData?.finalDecision !== "NO_TRADE" && signalData != null} />

          <div className="primary-chart">
            {market.status === "ready" && <PriceChart candles={market.data.candles} analysis={analysisData} signal={signalData} />}
            {market.status === "loading" && <WorkspaceState loading title="LOADING MARKET DATA" detail={`Fetching closed ${symbol} ${formatTimeframe(timeframe)} candles…`} />}
            {market.status === "empty" && <WorkspaceState title="NO CANDLES AVAILABLE" detail="The provider returned no closed candles for this selection." action={retry} />}
            {market.status === "error" && <WorkspaceState error title="MARKET DATA UNAVAILABLE" detail={market.message} action={retry} />}
          </div>
          <MacdChart state={macdState} />
        </section>

        <SignalPanel state={signal} symbol={symbol} timeframe={timeframe} onRetry={retry} />
      </div>

      <footer className="terminal-footer">
        <span>UTC · CLOSED-CANDLE ANALYSIS</span>
        <span className="footer-separator" />
        <span>{analysis.status === "error" ? "ANALYSIS MODULES OFFLINE" : "DETERMINISTIC ENGINE"}</span>
        <span className="footer-spacer" />
        <span>NO ORDER EXECUTION</span>
      </footer>
    </main>
  );
}

function WorkspaceState({ title, detail, loading = false, error = false, action }: { title: string; detail: string; loading?: boolean; error?: boolean; action?: () => void }) {
  return (
    <div className={`workspace-state ${error ? "error" : ""}`} role={error ? "alert" : undefined}>
      <div className={`state-glyph ${loading ? "loading" : ""}`}>{error ? "!" : loading ? "" : "—"}</div>
      <strong>{title}</strong><span>{detail}</span>
      {action && <button type="button" onClick={action}>TRY AGAIN</button>}
    </div>
  );
}
