export const SYMBOLS = ["XAUUSD", "BTCUSDT", "ETHUSDT"] as const;
export type SymbolCode = (typeof SYMBOLS)[number];

export const TIMEFRAMES = ["1m", "3m", "5m", "15m", "1h"] as const;
export type Timeframe = (typeof TIMEFRAMES)[number];

export type Decision = "LONG" | "SHORT" | "NO_TRADE";

export interface Candle {
  timestamp: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
}

export interface MarketDataProvenance {
  provider: string;
  data_mode: "SERVER_PROVIDER";
  symbol: SymbolCode;
  timeframe: Timeframe;
  first_candle_at: string;
  last_candle_at: string;
  data_cutoff_at: string;
  expected_latest_closed_candle_at: string;
  retrieved_at: string;
  requested_candles: number;
  received_candles: number;
  lag_seconds: number;
  market_schedule_mode: "CONTINUOUS_24_7" | "SESSION_CALENDAR";
  session_calendar_id: string | null;
  session_calendar_version: string | null;
  session_calendar_hash: string | null;
  validated: true;
}

export interface MarketDataResponse {
  symbol: SymbolCode;
  timeframe: Timeframe;
  source: string;
  retrieved_at: string;
  candles: Candle[];
  provenance: MarketDataProvenance;
}

export interface LevelOverlay {
  id: string;
  lower: number;
  upper: number;
  anchorPrice: number;
  label: string;
  createdAt: string;
  confirmedAt: string | null;
}

export interface SwingOverlay {
  id: string;
  kind: "HIGH" | "LOW";
  pivotAt: string;
  confirmedAt: string;
  price: number;
}

export interface StructureOverlay {
  id: string;
  type: "BOS" | "MSS";
  direction: "bullish" | "bearish";
  createdAt: string;
  confirmedAt: string;
  price: number;
}

export type GapLifecycleState =
  | "ACTIVE"
  | "PARTIALLY_FILLED"
  | "FILLED"
  | "INVERTED"
  | "INVALIDATED"
  | "EXPIRED";

export type OrderBlockLifecycleState =
  | "CANDIDATE"
  | "VALIDATED"
  | "MITIGATED"
  | "INVALIDATED"
  | "EXPIRED";

export type ZoneLifecycleState = GapLifecycleState | OrderBlockLifecycleState;

export type ZoneLifecycleEventType =
  | "FVG_CREATED"
  | "FVG_RETEST"
  | "FVG_FILLED"
  | "FVG_INVERTED"
  | "FVG_EXPIRED"
  | "IFVG_CREATED"
  | "IFVG_RETEST"
  | "IFVG_FILLED"
  | "IFVG_INVALIDATED"
  | "IFVG_EXPIRED"
  | "OB_CREATED"
  | "OB_VALIDATED"
  | "OB_MITIGATED"
  | "OB_INVALIDATED"
  | "OB_EXPIRED";

export interface ZoneLifecycleEvent {
  type: ZoneLifecycleEventType;
  occurredAt: string;
  fromState: ZoneLifecycleState | null;
  toState: ZoneLifecycleState;
}

export interface ZoneOverlay {
  id: string;
  kind: "FVG" | "ORDER_BLOCK";
  direction: "bullish" | "bearish";
  lower: number;
  upper: number;
  createdAt: string;
  confirmedAt: string | null;
  validatedAt: string | null;
  updatedAt: string;
  mitigatedAt: string | null;
  invalidatedAt: string | null;
  status: "OPEN" | "PARTIAL" | "FILLED" | "INVALIDATED" | OrderBlockLifecycleState;
  lifecycleState: ZoneLifecycleState;
  lifecycle: ZoneLifecycleEvent[];
  terminalAt: string | null;
  isTerminal: boolean;
}

export interface MacdPoint {
  timestamp: string;
  macd: number | null;
  signal: number | null;
  histogram: number | null;
}

export interface AnalysisViewModel {
  supports: LevelOverlay[];
  resistances: LevelOverlay[];
  swings: SwingOverlay[];
  structures: StructureOverlay[];
  zones: ZoneOverlay[];
  macd: MacdPoint[];
}

export interface SignalViewModel {
  symbol: SymbolCode;
  timeframe: Timeframe;
  decisionMode: "DETERMINISTIC_ONLY";
  aiValidationStatus: "NOT_REQUESTED";
  algorithmDecision: Decision;
  aiDecision: Decision | null;
  finalDecision: Decision;
  entryMin: number | null;
  entryMax: number | null;
  takeProfit: number | null;
  stopLoss: number | null;
  confidence: number | null;
  riskReward: number | null;
  reason: string[];
  factors: Partial<Record<"MACD" | "SMC" | "ICT" | "S/R", "confirmed" | "mixed" | "unavailable">>;
  validatedAt: string;
}

export type LoadState<T> =
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "empty" }
  | { status: "error"; message: string };
