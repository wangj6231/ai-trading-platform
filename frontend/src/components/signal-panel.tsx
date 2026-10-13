import { formatPrice, formatTimeframe } from "@/lib/format";
import { STRATEGY_EVALUATION_CLOCK } from "@/types/trading";
import { DataProvenance } from "./data-provenance";
import type { AnalysisViewModel, LoadState, SignalViewModel, StrategyProvenance, SymbolCode } from "@/types/trading";

interface SignalPanelProps {
  state: LoadState<SignalViewModel>;
  symbol: SymbolCode;
  analysis?: LoadState<AnalysisViewModel>;
  onRetry: () => void;
  now?: number;
  onPaperTrade?: () => void;
}

export function SignalPanel({ state, symbol, analysis, onRetry, now = 0, onPaperTrade }: SignalPanelProps) {
  const displayedSymbol = state.status === "ready" ? state.data.symbol : symbol;
  const displayedTimeframe = state.status === "ready" ? state.data.strategyEvaluationClock : STRATEGY_EVALUATION_CLOCK;
  const provenance = analysis?.status === "ready" ? analysis.data.strategy : undefined;
  const matchingProvenance = state.status === "ready" && provenance?.symbol === state.data.symbol &&
    Date.parse(provenance.dataCutoffAt) === Date.parse(state.data.dataCutoffAt) ? provenance : undefined;
  return (
    <aside className="signal-panel" aria-label="Deterministic signal panel">
      <div className="panel-heading">
        <div>
          <span className="section-kicker">DETERMINISTIC ANALYSIS</span>
          <h2>DETERMINISTIC CANDIDATE</h2>
        </div>
        <button className="refresh-button" type="button" onClick={onRetry} disabled={state.status === "loading"}>Refresh strategy</button>
      </div>

      <div className="signal-market">
        <strong>{displayedSymbol}</strong>
        <span>{formatTimeframe(displayedTimeframe)}</span>
      </div>
      <div className="strategy-clock-label">SERVER STRATEGY CLOCK · CLOSED 15M</div>

      {state.status === "loading" && <SignalLoading />}
      {state.status === "error" && (
        <div className="signal-state signal-error" role="alert">
          <span className="state-icon">!</span>
          <h3>{state.kind === "contract" ? "BACKEND CONTRACT INVALID" : "ANALYSIS UNAVAILABLE"}</h3>
          <p>{state.message}</p>
          <button type="button" onClick={onRetry}>RETRY</button>
        </div>
      )}
      {state.status === "empty" && (
        <div className="signal-state signal-empty">
          <span className="state-icon">—</span>
          <h3>NO DETERMINISTIC SIGNAL</h3>
          <p>The deterministic engine has not produced a candidate for this market.</p>
        </div>
      )}
      {state.status === "ready" && <SignalDetails signal={state.data} />}
      <div className="paper-trade-action"><button type="button" disabled={!onPaperTrade} onClick={onPaperTrade}>Paper Trade</button><span>Open an order ticket · no order submitted</span></div>
      {state.status === "ready" && <DataProvenance data={state.data.provenance} now={now} label="Strategy data" showCutoff={false} />}
      {state.status === "ready" && (
        <section className="strategy-provenance" aria-label="Strategy provenance">
          <span className="metric-label">DATA CUTOFF · UTC</span>
          <time dateTime={state.data.dataCutoffAt}>{state.data.dataCutoffAt}</time>
          {matchingProvenance ? <StrategyEvidence provenance={matchingProvenance} /> : (
            <p>{analysis?.status === "error" ?
              `${analysis.kind === "contract" ? "BACKEND CONTRACT INVALID" : "STRATEGY EVIDENCE UNAVAILABLE"}: ${analysis.message}` :
              provenance ? "Analysis cutoff differs; identity/MTF evidence not attached to this signal." :
              "Strategy identity / MTF evidence not available yet."}</p>
          )}
          {!matchingProvenance && analysis?.status === "error" && <button className="refresh-button" type="button" onClick={onRetry}>Retry evidence</button>}
        </section>
      )}

      <div className="panel-safety">
        <span className="shield-icon" aria-hidden="true">◇</span>
        <div><strong>DECISION SUPPORT</strong><br />No broker execution</div>
      </div>
    </aside>
  );
}

function SignalLoading() {
  return (
    <div className="signal-loading" aria-label="Loading signal">
      <div className="skeleton skeleton-decision" />
      <div className="skeleton-grid">
        {Array.from({ length: 6 }, (_, index) => <div className="skeleton" key={index} />)}
      </div>
    </div>
  );
}

function SignalDetails({ signal }: { signal: SignalViewModel }) {
  const action = signal.finalDecision;
  const tone = signal.finalDecision === "LONG" ? "long" : signal.finalDecision === "SHORT" ? "short" : "neutral";
  const reference = signal.entryMax ?? signal.entryMin ?? signal.takeProfit ?? undefined;

  return (
    <div className="signal-details">
      <div className={`decision-banner ${tone}`}>
        <span>DETERMINISTIC DECISION</span>
        <strong>{action}</strong>
      </div>

      {signal.finalDecision !== "NO_TRADE" ? (
        <div className="level-grid">
          <SignalMetric
            label="ENTRY"
            value={`${formatPrice(signal.entryMin, reference)} – ${formatPrice(signal.entryMax, reference)}`}
            wide
          />
          <SignalMetric label="TAKE PROFIT" value={formatPrice(signal.takeProfit, reference)} accent="target" />
          <SignalMetric label="STOP LOSS" value={formatPrice(signal.stopLoss, reference)} accent="stop" />
          <SignalMetric label="RISK REWARD" value={signal.riskReward === null ? "—" : `1 : ${signal.riskReward}`} />
        </div>
      ) : (
        <div className="no-trade-reason">
          <span>NO LEVELS ISSUED</span>
          <p>The backend did not issue entry, TP, SL or RR for this snapshot.</p>
        </div>
      )}

      <div className="factor-section">
        <span className="metric-label">ALGORITHM SCORE: {signal.algorithmScore ?? "UNAVAILABLE"}</span>
        <dl className="score-breakdown">{Object.entries(signal.scoreBreakdown).map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}</dl>
        {Object.keys(signal.scoreBreakdown).length === 0 && <p className="policy-note">No score breakdown returned.</p>}
        <span className="metric-label">SERVER REASON CODES</span>
        <ul className="reason-codes">{signal.reason.map((reason, index) => <li key={`${index}:${reason}`}>{reason}</li>)}</ul>
      </div>

      <div className="decision-audit">
        <AuditItem label="SOURCE" value="BACKEND" />
        <span className="audit-arrow">→</span>
        <AuditItem label="MODE" value="DETERMINISTIC ONLY" />
        <AuditItem label="FINAL" value="SERVER OWNED" />
      </div>
    </div>
  );
}

function StrategyEvidence({ provenance }: { provenance: StrategyProvenance }) {
  return <>
    <span className="metric-label">STRATEGY VERSION</span>
    <strong>{provenance.identity.strategy_version}</strong>
    <details><summary>Identity hashes</summary>
      <span>Config hash</span><code>{provenance.identity.config_hash}</code>
      <span>Algorithm build hash</span><code>{provenance.identity.algorithm_build_hash}</code>
    </details>
    <span className="metric-label">STRATEGY EVALUATION · UTC</span>
    <span>As of: {provenance.asOf ?? provenance.dataCutoffAt}</span>
  </>;
}

function SignalMetric({ label, value, wide = false, accent }: { label: string; value: string; wide?: boolean; accent?: string }) {
  return (
    <div className={`signal-metric ${wide ? "wide" : ""} ${accent ?? ""}`}>
      <span className="metric-label">{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function AuditItem({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong>{value.replace("_", " ")}</strong></div>;
}
