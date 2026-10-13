"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { BackendContractError, fetchCandles } from "@/lib/api";
import { fetchEvaluation } from "@/lib/evaluations";
import type { EvaluationJob } from "@/lib/evaluations";
import { EvaluationProgress } from "./evaluation-progress";
import { errorMessage, formatPrice, formatTimeframe } from "@/lib/format";
import { snapshotStatus } from "@/lib/freshness";
import { DataProvenance } from "./data-provenance";
import { MTFEvidencePanel } from "./mtf-evidence-panel";
import type { AnalysisViewModel, LoadState, MacdPoint, MarketDataResponse, SignalViewModel, SymbolCode, Timeframe } from "@/types/trading";
import { MacdChart } from "./macd-chart";
import { ChartEvidenceControls } from "./chart-evidence-controls";
import { ChartEvidenceInspector } from "./chart-evidence-inspector";
import { decisionEvidenceView, evidenceCounts, evidenceRecords } from "@/lib/chart-evidence";
import { archiveDensity, type EvidenceDensity, type EvidenceProjection } from "@/lib/chart-density";
import { PriceChart } from "./price-chart";
import { SignalPanel } from "./signal-panel";
import { TopBar } from "./top-bar";
import type { StrategyPlan } from "@/lib/product/contracts";

export function TradingDashboard({ onPaperTrade }: { onPaperTrade?: (plan: StrategyPlan) => void } = {}) {
  const [symbol, setSymbol] = useState<SymbolCode>("BTCUSDT");
  const [displayTimeframe, setDisplayTimeframe] = useState<Timeframe>("15m");
  const [now, setNow] = useState(0);
  const [market, setMarket] = useState<LoadState<MarketDataResponse>>({ status: "loading" });
  const [analysis, setAnalysis] = useState<LoadState<AnalysisViewModel>>({ status: "loading" });
  const [signal, setSignal] = useState<LoadState<SignalViewModel>>({ status: "loading" });
  const [chartRequestVersion, setChartRequestVersion] = useState(0);
  const [strategyRequestVersion, setStrategyRequestVersion] = useState(0);
  const [evaluation, setEvaluation] = useState<EvaluationJob | null>(null);
  const [evidenceView, setEvidenceView] = useState(decisionEvidenceView);
  const [evidenceDensity, setEvidenceDensity] = useState<EvidenceDensity>();
  const [evidenceProjection, setEvidenceProjection] = useState<EvidenceProjection>();
  const updateDensity = useCallback((density: EvidenceDensity, projection: EvidenceProjection) => { setEvidenceDensity(density); setEvidenceProjection(projection); }, []);
  const [evidenceSelection, setEvidenceSelection] = useState<string[] | null>(null);
  const inspectEvidence = useCallback((keys: string[]) => setEvidenceSelection((current) => current?.join("|") === keys.join("|") ? current : keys), []);

  useEffect(() => {
    const update = () => setNow(Date.now());
    update();
    const timer = window.setInterval(update, 30_000);
    window.addEventListener("focus", update);
    return () => { window.clearInterval(timer); window.removeEventListener("focus", update); };
  }, []);

  const showLoading = useCallback(() => {
    setMarket({ status: "loading" });
    setAnalysis({ status: "loading" });
    setSignal({ status: "loading" });
    setEvaluation(null);
    setEvidenceSelection(null);
  }, []);
  const retryChart = useCallback(() => {
    setMarket({ status: "loading" });
    setChartRequestVersion((value) => value + 1);
  }, []);
  const retryStrategy = useCallback(() => {
    setAnalysis({ status: "loading" });
    setSignal({ status: "loading" });
    setEvaluation(null);
    setEvidenceSelection(null);
    setStrategyRequestVersion((value) => value + 1);
  }, []);
  const selectSymbol = useCallback((next: SymbolCode) => {
    if (next === symbol) return;
    showLoading();
    setSymbol(next);
  }, [showLoading, symbol]);
  const selectTimeframe = useCallback((next: Timeframe) => {
    if (next === displayTimeframe) return;
    setMarket({ status: "loading" });
    setDisplayTimeframe(next);
  }, [displayTimeframe]);

  useEffect(() => {
    const controller = new AbortController();

    void fetchEvaluation(symbol, controller.signal, (job) => {
      if (!controller.signal.aborted) setEvaluation(job);
    })
      .then((data) => {
        if (!controller.signal.aborted) {
          setNow(Date.now());
          setSignal({ status: "ready", data: data.signal });
          setAnalysis({ status: "ready", data: data.analysis });
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          const state = { status: "error" as const, kind: error instanceof BackendContractError ? "contract" as const : "unavailable" as const,
            message: errorMessage(error, "Evaluation service unavailable.") };
          setSignal(state); setAnalysis(state);
        }
      });
    return () => controller.abort();
  }, [symbol, strategyRequestVersion]);

  useEffect(() => {
    const controller = new AbortController();
    void fetchCandles(symbol, displayTimeframe, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setMarket(data.candles.length ? { status: "ready", data } : { status: "empty" });
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setMarket({ status: "error", message: errorMessage(error, "Chart market data unavailable.") });
      });
    return () => controller.abort();
  }, [symbol, displayTimeframe, chartRequestVersion]);

  const candles = market.status === "ready" ? market.data.candles : [];
  const latest = candles.length ? candles[candles.length - 1] : null;
  const previous = candles.length > 1 ? candles[candles.length - 2] : null;
  const lastPrice = latest ? Number(latest.close) : null;
  const change = latest && previous ? Number(latest.close) - Number(previous.close) : null;
  const changePercent = change !== null && previous ? (change / Number(previous.close)) * 100 : null;
  const analysisData = analysis.status === "ready" && snapshotStatus(analysis.data.strategy?.data, now) !== "STALE" ? analysis.data : null;
  const signalData = signal.status === "ready" && snapshotStatus(signal.data.provenance, now) !== "STALE" ? signal.data : null;
  const strategyEvidence = analysis.status === "ready" ? analysis.data.strategy : undefined;
  const evidenceRows = useMemo(() => evidenceRecords(analysis.status === "ready" ? analysis.data : null, signal.status === "ready" ? signal.data : null), [analysis, signal]);
  const layerCounts = useMemo(() => evidenceCounts(evidenceRows), [evidenceRows]);
  const archiveCounts = useMemo(() => archiveDensity(evidenceDensity, layerCounts), [evidenceDensity, layerCounts]);
  const matchingEvidence = signal.status === "ready" && strategyEvidence?.symbol === signal.data.symbol &&
    Date.parse(strategyEvidence.dataCutoffAt) === Date.parse(signal.data.dataCutoffAt) ? strategyEvidence : undefined;
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
        displayTimeframe={displayTimeframe}
        onSymbolChange={selectSymbol}
        onDisplayTimeframeChange={selectTimeframe}
        isLoading={market.status === "loading"}
        source={market.status === "ready" ? market.data.source : undefined}
        feedStatus={market.status === "ready" ? snapshotStatus(market.data.provenance, now) : "UNAVAILABLE"}
      />

      <div className="dashboard-intro"><div><span className="section-kicker">MARKET WORKSPACE</span><p>Explore price. Inspect the server decision.</p></div><span>One strategy · closed 15M<br />Chart periods change the view only</span></div>
      <EvaluationProgress key={evaluation?.evaluation_id ?? "new"} job={evaluation} loadingResults={signal.status === "loading"}
        onCancelled={(job) => setEvaluation((current) => current?.evaluation_id === job.evaluation_id ? job : current)} />

      <div className="workspace-grid">
        <section className="market-workspace">
          <div className="chart-header">
            <div className="instrument-summary">
              <div><h1>{symbol}</h1><span>{formatTimeframe(displayTimeframe)} · DISPLAY ONLY · CLOSED SPOT CANDLES</span></div>
              <strong>{formatPrice(lastPrice, lastPrice ?? undefined)}</strong>
              {change !== null && changePercent !== null && (
                <span className={change >= 0 ? "price-up" : "price-down"}>{change >= 0 ? "+" : ""}{formatPrice(change, lastPrice ?? undefined)} ({changePercent >= 0 ? "+" : ""}{changePercent.toFixed(2)}%)<small>vs previous {formatTimeframe(displayTimeframe)} close</small></span>
              )}
            </div>
            <div className="chart-meta">
              {latest && <><span>O <b>{formatPrice(Number(latest.open), lastPrice ?? undefined)}</b></span><span>H <b>{formatPrice(Number(latest.high), lastPrice ?? undefined)}</b></span><span>L <b>{formatPrice(Number(latest.low), lastPrice ?? undefined)}</b></span><span>C <b>{formatPrice(Number(latest.close), lastPrice ?? undefined)}</b></span></>}
            </div>
          </div>
          <div className="chart-toolbar"><span>15M strategy overlays · pan / zoom to inspect</span><button className="refresh-button" type="button" onClick={retryChart} disabled={market.status === "loading"}>Refresh chart</button></div>
          <ChartEvidenceControls view={evidenceView} counts={layerCounts} density={market.status === "ready" ? archiveCounts : undefined} available={analysis.status === "ready" && signal.status === "ready"} onChange={setEvidenceView} onInspect={() => setEvidenceSelection([])} />

          <div className="primary-chart">
            {market.status === "ready" && <PriceChart candles={market.data.candles} analysis={analysisData} signal={signalData} view={evidenceView} onInspect={inspectEvidence} onDensity={updateDensity} />}
            {market.status === "loading" && <WorkspaceState loading title="LOADING MARKET DATA" detail={`Fetching closed ${symbol} ${formatTimeframe(displayTimeframe)} candles…`} />}
            {market.status === "empty" && <WorkspaceState title="NO CANDLES AVAILABLE" detail="The provider returned no closed candles for this selection." action={retryChart} />}
            {market.status === "error" && <WorkspaceState error title="CHART DATA UNAVAILABLE" detail={market.message} action={retryChart} />}
          </div>
          <MacdChart state={macdState} />
          {market.status === "ready" && <DataProvenance data={market.data.provenance} now={now} label="Chart data" />}
          {evidenceSelection !== null && <ChartEvidenceInspector key={evidenceSelection.join("|")} rows={evidenceRows} selection={evidenceSelection} projection={market.status === "ready" ? evidenceProjection : undefined} source={analysis.status === "ready" ? analysis.data.sourceEvidence : undefined} stale={(analysis.status === "ready" && analysisData === null) || (signal.status === "ready" && signalData === null)} onClose={() => setEvidenceSelection(null)} />}
        </section>

        <SignalPanel state={signal} symbol={symbol} analysis={analysis} onRetry={retryStrategy} now={now}
          onPaperTrade={onPaperTrade && signalData && matchingEvidence && snapshotStatus(signalData.provenance, now) === "CURRENT" && signalData.finalDecision !== "NO_TRADE" ? () => onPaperTrade({
            symbol: signalData.symbol, direction: signalData.finalDecision as "LONG" | "SHORT",
            entryMin: signalData.entryMin === null ? null : String(signalData.entryMin), entryMax: signalData.entryMax === null ? null : String(signalData.entryMax),
            takeProfit: signalData.takeProfit === null ? null : String(signalData.takeProfit), stopLoss: signalData.stopLoss === null ? null : String(signalData.stopLoss), riskReward: signalData.riskReward === null ? null : String(signalData.riskReward),
            strategyName: null, strategyVersion: matchingEvidence.identity.strategy_version, configIdentity: matchingEvidence.identity.config_hash,
            evaluationReference: evaluation?.status === "COMPLETED" ? evaluation.evaluation_id : null, cutoff: signalData.dataCutoffAt, signalTimeframe: "15m", source: "BACKEND",
          }) : undefined} />
      </div>

      <div className="mtf-workspace">
        {matchingEvidence ? <MTFEvidencePanel provenance={matchingEvidence} now={now} /> : <section className="mtf-evidence" aria-label="MTF evidence">
          <div className="evidence-heading"><h3>MTF EVIDENCE</h3><span>{analysis.status === "loading" || signal.status === "loading" ? "LOADING" : "UNAVAILABLE"}</span></div>
          <p className="policy-note">Waiting for validated strategy evidence at the same signal cutoff.</p>
        </section>}
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
