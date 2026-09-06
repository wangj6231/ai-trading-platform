import { formatPrice, formatTimeframe } from "@/lib/format";
import type { LoadState, SignalViewModel, SymbolCode, Timeframe } from "@/types/trading";

interface SignalPanelProps {
  state: LoadState<SignalViewModel>;
  symbol: SymbolCode;
  timeframe: Timeframe;
  onRetry: () => void;
}

const FACTORS = ["MACD", "SMC", "ICT", "S/R"] as const;

export function SignalPanel({ state, symbol, timeframe, onRetry }: SignalPanelProps) {
  const displayedSymbol = state.status === "ready" ? state.data.symbol : symbol;
  const displayedTimeframe = state.status === "ready" ? state.data.timeframe : timeframe;
  return (
    <aside className="signal-panel" aria-label="Deterministic signal panel">
      <div className="panel-heading">
        <div>
          <span className="section-kicker">DETERMINISTIC ANALYSIS</span>
          <h2>DETERMINISTIC CANDIDATE</h2>
        </div>
        <span className="ai-orbit" aria-hidden="true"><i /></span>
      </div>

      <div className="signal-market">
        <strong>{displayedSymbol}</strong>
        <span>{formatTimeframe(displayedTimeframe)}</span>
      </div>

      {state.status === "loading" && <SignalLoading />}
      {state.status === "error" && (
        <div className="signal-state signal-error" role="alert">
          <span className="state-icon">!</span>
          <h3>ANALYSIS UNAVAILABLE</h3>
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
  const action = signal.finalDecision === "LONG" ? "BUY" : signal.finalDecision === "SHORT" ? "SELL" : "NO TRADE";
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
          <p>{signal.reason[0] ?? "The deterministic engine did not issue a candidate."}</p>
        </div>
      )}

      <div className="factor-section">
        <span className="metric-label">CONFLUENCE</span>
        <div className="factor-grid">
          {FACTORS.map((factor) => {
            const status = signal.factors[factor] ?? "unavailable";
            return <span className={`factor ${status}`} key={factor}><i />{factor}</span>;
          })}
        </div>
      </div>

      <div className="decision-audit">
        <AuditItem label="ALGO" value={signal.algorithmDecision} />
        <span className="audit-arrow">→</span>
        <AuditItem label="AI STATE" value="AI NOT REQUESTED" />
        <span className="audit-arrow">→</span>
        <AuditItem label="FINAL" value={signal.finalDecision} />
      </div>
    </div>
  );
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
