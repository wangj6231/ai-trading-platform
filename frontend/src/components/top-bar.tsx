import type { SymbolCode, Timeframe } from "@/types/trading";
import { SYMBOLS, TIMEFRAMES } from "@/types/trading";
import { formatTimeframe } from "@/lib/format";

interface TopBarProps {
  symbol: SymbolCode;
  timeframe: Timeframe;
  onSymbolChange: (symbol: SymbolCode) => void;
  onTimeframeChange: (timeframe: Timeframe) => void;
  isLoading: boolean;
  source?: string;
}

export function TopBar({
  symbol,
  timeframe,
  onSymbolChange,
  onTimeframeChange,
  isLoading,
  source,
}: TopBarProps) {
  return (
    <header className="top-bar">
      <div className="brand-lockup">
        <div className="brand-mark" aria-hidden="true"><span /></div>
        <div>
          <div className="brand-name">AXIOM</div>
          <div className="brand-subtitle">MARKET INTELLIGENCE</div>
        </div>
      </div>

      <div className="instrument-controls" aria-label="Market controls">
        <label className="select-shell">
          <span className="control-eyebrow">SYMBOL</span>
          <select
            aria-label="Symbol"
            value={symbol}
            onChange={(event) => onSymbolChange(event.target.value as SymbolCode)}
          >
            {SYMBOLS.map((item) => <option key={item}>{item}</option>)}
          </select>
        </label>

        <div className="timeframe-control" role="group" aria-label="Timeframe">
          <span className="control-eyebrow">INTERVAL</span>
          <div className="timeframe-buttons">
            {TIMEFRAMES.map((item) => (
              <button
                type="button"
                key={item}
                className={item === timeframe ? "active" : ""}
                aria-pressed={item === timeframe}
                onClick={() => onTimeframeChange(item)}
              >
                {formatTimeframe(item)}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="terminal-status">
        <div className="feed-status">
          <span className={`status-dot ${isLoading ? "pulse" : ""}`} />
          <span>{isLoading ? "SYNCING" : source ? `${source.toUpperCase()} FEED` : "FEED IDLE"}</span>
        </div>
        <div className="analysis-only">ANALYSIS ONLY</div>
      </div>
    </header>
  );
}
