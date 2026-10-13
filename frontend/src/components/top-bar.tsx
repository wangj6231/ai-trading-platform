import type { SymbolCode, Timeframe } from "@/types/trading";
import { SYMBOLS, TIMEFRAMES } from "@/types/trading";
import { formatTimeframe } from "@/lib/format";

interface TopBarProps {
  symbol: SymbolCode;
  displayTimeframe: Timeframe;
  onSymbolChange: (symbol: SymbolCode) => void;
  onDisplayTimeframeChange: (timeframe: Timeframe) => void;
  isLoading: boolean;
  source?: string;
  feedStatus?: "CURRENT" | "STALE" | "UNKNOWN" | "UNAVAILABLE";
}

export function TopBar({
  symbol,
  displayTimeframe,
  onSymbolChange,
  onDisplayTimeframeChange,
  isLoading,
  source,
  feedStatus = "UNKNOWN",
}: TopBarProps) {
  return (
    <header className="top-bar">
      <div className="brand-lockup">
        <div className="brand-mark" aria-hidden="true"><span /></div>
        <div>
          <div className="brand-name">AXIOM</div>
          <div className="brand-subtitle">BINANCE SPOT · PRODUCT V1</div>
        </div>
      </div>

      <div className="instrument-controls" aria-label="Market controls">
        <label className="select-shell">
          <span className="control-eyebrow">SYMBOL</span>
          <select
            aria-label="Symbol"
            value={symbol}
            onChange={(event) => {
              const next = SYMBOLS.find((value) => value === event.target.value);
              if (next) onSymbolChange(next);
            }}
          >
            {SYMBOLS.map((item) => <option key={item}>{item}</option>)}
          </select>
        </label>

        <div className="timeframe-control" role="group" aria-label="Chart timeframe">
          <span className="control-eyebrow">CHART · DISPLAY ONLY</span>
          <div className="timeframe-buttons">
            {TIMEFRAMES.map((item) => (
              <button
                type="button"
                key={item}
                className={item === displayTimeframe ? "active" : ""}
                aria-pressed={item === displayTimeframe}
                onClick={() => onDisplayTimeframeChange(item)}
              >
                {formatTimeframe(item)}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="terminal-status">
        <div className="feed-status">
          <span className={`status-dot ${isLoading ? "pulse" : feedStatus.toLowerCase()}`} />
          <span>{isLoading ? "SYNCING" : source ? `${source.toUpperCase()} · ${feedStatus}` : "FEED UNAVAILABLE"}</span>
        </div>
        <div className="analysis-only">ANALYSIS ONLY</div>
      </div>
    </header>
  );
}
