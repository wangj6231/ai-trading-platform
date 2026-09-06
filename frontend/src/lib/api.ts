import { z } from "zod";
import type {
  AnalysisViewModel,
  Decision,
  MarketDataResponse,
  SignalViewModel,
  SymbolCode,
  Timeframe,
} from "@/types/trading";

const SymbolSchema = z.enum(["XAUUSD", "BTCUSDT", "ETHUSDT"]);
const TimeframeSchema = z.enum(["1m", "3m", "5m", "15m", "1h"]);
const DecisionSchema = z.enum(["LONG", "SHORT", "NO_TRADE"]);
const DirectionSchema = z.enum(["bullish", "bearish"]);
const ApiErrorEnvelopeSchema = z
  .object({
    error: z
      .object({
        code: z.string().min(1),
        message: z.string().min(1),
        details: z.unknown().optional(),
        request_id: z.string().min(1).optional(),
      })
      .strict(),
  })
  .strict();
const TimestampSchema = z.string().refine(
  (value) =>
    !Number.isNaN(Date.parse(value)) &&
    (value.endsWith("Z") || /[+-]\d{2}:\d{2}$/.test(value)),
  "Expected a timezone-aware ISO timestamp",
);
const FiniteNumberSchema = z
  .union([z.number(), z.string().min(1)])
  .transform((value) => Number(value))
  .refine(Number.isFinite, "Expected a finite number");
const PositiveNumberSchema = FiniteNumberSchema.refine(
  (value) => value > 0,
  "Expected a positive number",
);
const NullablePositiveNumberSchema = z.union([z.null(), PositiveNumberSchema]);
const ProvenanceSchema = z
  .object({
    provider: z.string().min(1),
    data_mode: z.literal("SERVER_PROVIDER"),
    symbol: SymbolSchema,
    timeframe: TimeframeSchema,
    first_candle_at: TimestampSchema,
    last_candle_at: TimestampSchema,
    data_cutoff_at: TimestampSchema,
    expected_latest_closed_candle_at: TimestampSchema,
    retrieved_at: TimestampSchema,
    requested_candles: z.number().int().positive(),
    received_candles: z.number().int().positive(),
    lag_seconds: z.number().int().nonnegative(),
    market_schedule_mode: z.enum(["CONTINUOUS_24_7", "SESSION_CALENDAR"]),
    session_calendar_id: z.string().min(1).nullable(),
    session_calendar_version: z.string().min(1).nullable(),
    session_calendar_hash: z.string().regex(/^[0-9a-f]{64}$/).nullable(),
    validated: z.literal(true),
  })
  .strict()
  .superRefine((provenance, context) => {
    const calendarIdentity = [
      provenance.session_calendar_id,
      provenance.session_calendar_version,
      provenance.session_calendar_hash,
    ];
    if (
      provenance.market_schedule_mode === "SESSION_CALENDAR" &&
      calendarIdentity.some((value) => value === null)
    ) {
      context.addIssue({
        code: "custom",
        message: "Session-calendar provenance requires complete calendar identity",
      });
    }
    if (
      provenance.market_schedule_mode === "CONTINUOUS_24_7" &&
      calendarIdentity.some((value) => value !== null)
    ) {
      context.addIssue({
        code: "custom",
        message: "Continuous provenance cannot include calendar identity",
      });
    }
  });

const CandleSchema = z
  .object({
    timestamp: TimestampSchema,
    open: FiniteNumberSchema,
    high: FiniteNumberSchema,
    low: FiniteNumberSchema,
    close: FiniteNumberSchema,
    volume: FiniteNumberSchema,
  })
  .strict()
  .superRefine((candle, context) => {
    if (candle.high < Math.max(candle.open, candle.close)) {
      context.addIssue({ code: "custom", message: "Candle high is invalid" });
    }
    if (candle.low > Math.min(candle.open, candle.close) || candle.low > candle.high) {
      context.addIssue({ code: "custom", message: "Candle low is invalid" });
    }
    if (candle.volume < 0) {
      context.addIssue({ code: "custom", message: "Candle volume is invalid" });
    }
  });

const MarketDataSchema = z
  .object({
    symbol: SymbolSchema,
    timeframe: TimeframeSchema,
    source: z.string().min(1),
    retrieved_at: TimestampSchema,
    candles: z.array(CandleSchema),
    provenance: ProvenanceSchema,
  })
  .strict()
  .superRefine((data, context) => {
    if (
      data.symbol !== data.provenance.symbol ||
      data.timeframe !== data.provenance.timeframe ||
      data.source !== data.provenance.provider ||
      data.retrieved_at !== data.provenance.retrieved_at ||
      data.candles.length !== data.provenance.received_candles
    ) {
      context.addIssue({ code: "custom", message: "Market-data provenance mismatch" });
    }
  });

const SignalPayloadSchema = z
  .object({
    symbol: SymbolSchema,
    timeframe: TimeframeSchema,
    source: z.string().min(1),
    retrieved_at: TimestampSchema,
    data_cutoff_at: TimestampSchema,
    provenance: ProvenanceSchema,
    decision_mode: z.literal("DETERMINISTIC_ONLY"),
    ai_validation_status: z.literal("NOT_REQUESTED"),
    decision: DecisionSchema,
    algorithm_decision: DecisionSchema,
    ai_decision: z.null(),
    final_decision: DecisionSchema,
    confidence: z.null(),
    validated_at: TimestampSchema,
    entry_min: NullablePositiveNumberSchema,
    entry_max: NullablePositiveNumberSchema,
    take_profit: NullablePositiveNumberSchema,
    stop_loss: NullablePositiveNumberSchema,
    risk_reward: NullablePositiveNumberSchema,
    algorithm_score: z.number().int().nullable(),
    score_breakdown: z.record(z.string(), z.number().int()),
    reason_codes: z.array(z.string().min(1)).min(1),
  })
  .strict()
  .superRefine((signal, context) => {
    if (
      signal.symbol !== signal.provenance.symbol ||
      signal.timeframe !== signal.provenance.timeframe ||
      signal.source !== signal.provenance.provider ||
      signal.retrieved_at !== signal.provenance.retrieved_at ||
      signal.data_cutoff_at !== signal.provenance.data_cutoff_at
    ) {
      context.addIssue({ code: "custom", message: "Signal provenance mismatch" });
    }
    if (signal.decision !== signal.final_decision) {
      context.addIssue({ code: "custom", message: "decision alias mismatch" });
    }
    if (signal.final_decision !== signal.algorithm_decision) {
      context.addIssue({
        code: "custom",
        message: "deterministic-only final decision differs from algorithm decision",
      });
    }
    if (
      signal.algorithm_decision === "NO_TRADE" &&
      signal.final_decision !== "NO_TRADE"
    ) {
      context.addIssue({ code: "custom", message: "algorithm NO_TRADE was upgraded" });
    }
    if (
      signal.final_decision !== "NO_TRADE" &&
      (signal.algorithm_decision !== signal.final_decision ||
        (signal.ai_decision !== null && signal.ai_decision !== signal.final_decision))
    ) {
      context.addIssue({ code: "custom", message: "trade decision chain is inconsistent" });
    }
    if (signal.ai_decision === "NO_TRADE" && signal.final_decision !== "NO_TRADE") {
      context.addIssue({ code: "custom", message: "AI rejection was ignored" });
    }

    const levels = [
      signal.entry_min,
      signal.entry_max,
      signal.take_profit,
      signal.stop_loss,
      signal.risk_reward,
    ];
    if (signal.final_decision === "NO_TRADE") {
      if (levels.some((level) => level !== null)) {
        context.addIssue({ code: "custom", message: "NO_TRADE contains actionable levels" });
      }
      return;
    }
    if (levels.some((level) => level === null) || signal.algorithm_score === null) {
      context.addIssue({ code: "custom", message: "trade signal is missing required fields" });
      return;
    }

    const entryMin = signal.entry_min!;
    const entryMax = signal.entry_max!;
    const takeProfit = signal.take_profit!;
    const stopLoss = signal.stop_loss!;
    if (entryMin > entryMax) {
      context.addIssue({ code: "custom", message: "entry range is reversed" });
    } else if (
      signal.final_decision === "LONG" &&
      !(stopLoss < entryMin && entryMax < takeProfit)
    ) {
      context.addIssue({ code: "custom", message: "LONG levels are directionally invalid" });
    } else if (
      signal.final_decision === "SHORT" &&
      !(takeProfit < entryMin && entryMax < stopLoss)
    ) {
      context.addIssue({ code: "custom", message: "SHORT levels are directionally invalid" });
    }
  });

const ConfirmedSwingSchema = z
  .object({
    swing_id: z.string().min(1),
    kind: z.enum(["HIGH", "LOW"]),
    pivot_timestamp: TimestampSchema,
    confirmed_at: TimestampSchema,
    price: PositiveNumberSchema,
  })
  .passthrough();
const PriceZoneSchema = z
  .object({
    zone_id: z.string().min(1),
    kind: z.enum(["SUPPORT", "RESISTANCE"]),
    lower_bound: PositiveNumberSchema,
    upper_bound: PositiveNumberSchema,
    anchor_price: PositiveNumberSchema,
    created_at: TimestampSchema,
  })
  .passthrough();
const StructureEventSchema = z
  .object({
    type: z.enum(["BOS", "MSS", "BREAK"]),
    direction: DirectionSchema,
    timestamp: TimestampSchema,
    confirmed_at: TimestampSchema,
    price: PositiveNumberSchema,
    broken_structure_id: z.string().min(1),
  })
  .passthrough();
const MarketStructureSnapshotSchema = z
  .object({
    confirmed_swings: z.array(ConfirmedSwingSchema),
    support_candidates: z.array(PriceZoneSchema),
    resistance_candidates: z.array(PriceZoneSchema),
    structure_events: z.array(StructureEventSchema),
  })
  .passthrough();
const GapZoneStatusSchema = z.enum(["OPEN", "PARTIAL", "FILLED", "INVALIDATED"]);
const GapLifecycleStateSchema = z.enum([
  "ACTIVE",
  "PARTIALLY_FILLED",
  "FILLED",
  "INVERTED",
  "INVALIDATED",
  "EXPIRED",
]);
const GapLifecycleEventTypeSchema = z.enum([
  "FVG_CREATED",
  "FVG_RETEST",
  "FVG_FILLED",
  "FVG_INVERTED",
  "FVG_EXPIRED",
  "IFVG_CREATED",
  "IFVG_RETEST",
  "IFVG_FILLED",
  "IFVG_INVALIDATED",
  "IFVG_EXPIRED",
]);
const GapLifecycleEventSchema = z
  .object({
    event_type: GapLifecycleEventTypeSchema,
    zone_id: z.string().min(1),
    bar_timestamp: TimestampSchema,
    occurred_at: TimestampSchema,
    from_state: GapLifecycleStateSchema.nullable(),
    to_state: GapLifecycleStateSchema,
    fill_fraction: FiniteNumberSchema.refine(
      (value) => value >= 0 && value <= 1,
      "Expected a fill fraction between zero and one",
    ),
    retest_count: z.number().int().nonnegative(),
  })
  .strict();
const FvgZoneSchema = z
  .object({
    zone_id: z.string().min(1),
    type: z.enum(["FVG", "IFVG"]),
    direction: DirectionSchema,
    lower: PositiveNumberSchema,
    upper: PositiveNumberSchema,
    created_at: TimestampSchema,
    confirmed_at: TimestampSchema,
    status: GapZoneStatusSchema,
    lifecycle_state: GapLifecycleStateSchema,
    last_updated_at: TimestampSchema,
    lifecycle: z.array(GapLifecycleEventSchema).min(1),
  })
  .passthrough()
  .superRefine((zone, context) => {
    const first = zone.lifecycle[0];
    const latest = zone.lifecycle[zone.lifecycle.length - 1];
    const expectedStatus = {
      ACTIVE: "OPEN",
      PARTIALLY_FILLED: "PARTIAL",
      FILLED: "FILLED",
      INVERTED: "INVALIDATED",
      INVALIDATED: "INVALIDATED",
      EXPIRED: "INVALIDATED",
    }[zone.lifecycle_state];
    if (
      zone.lifecycle.some((event) => event.zone_id !== zone.zone_id) ||
      latest.to_state !== zone.lifecycle_state ||
      expectedStatus !== zone.status ||
      first.event_type !== `${zone.type}_CREATED` ||
      first.from_state !== null
    ) {
      context.addIssue({ code: "custom", message: "FVG lifecycle is inconsistent" });
    }
    if (
      zone.lifecycle.some(
        (event, index) =>
          index > 0 &&
          (Date.parse(event.occurred_at) <
            Date.parse(zone.lifecycle[index - 1].occurred_at) ||
            event.from_state !== zone.lifecycle[index - 1].to_state),
      ) ||
      Date.parse(latest.occurred_at) > Date.parse(zone.last_updated_at)
    ) {
      context.addIssue({ code: "custom", message: "FVG lifecycle is not chronological" });
    }
  });
const OrderBlockStatusSchema = z.enum([
  "CANDIDATE",
  "VALIDATED",
  "MITIGATED",
  "INVALIDATED",
  "EXPIRED",
]);
const OrderBlockEventTypeSchema = z.enum([
  "OB_CREATED",
  "OB_VALIDATED",
  "OB_MITIGATED",
  "OB_INVALIDATED",
  "OB_EXPIRED",
]);
const OrderBlockLifecycleEventSchema = z
  .object({
    event_id: z.string().min(1),
    type: OrderBlockEventTypeSchema,
    zone_id: z.string().min(1),
    bar_timestamp: TimestampSchema,
    confirmed_at: TimestampSchema,
    from_status: OrderBlockStatusSchema.nullable(),
    to_status: OrderBlockStatusSchema,
    mean_threshold_held: z.boolean().nullable(),
  })
  .strict();
const OrderBlockZoneSchema = z
  .object({
    zone_id: z.string().min(1),
    direction: DirectionSchema,
    zone_low: PositiveNumberSchema,
    zone_high: PositiveNumberSchema,
    created_at: TimestampSchema,
    validated_at: TimestampSchema.nullable(),
    mitigated_at: TimestampSchema.nullable(),
    invalidated_at: TimestampSchema.nullable(),
    status: OrderBlockStatusSchema,
    lifecycle: z.array(OrderBlockLifecycleEventSchema).min(1),
  })
  .passthrough()
  .superRefine((zone, context) => {
    const first = zone.lifecycle[0];
    const latest = zone.lifecycle[zone.lifecycle.length - 1];
    if (
      zone.lifecycle.some((event) => event.zone_id !== zone.zone_id) ||
      latest.to_status !== zone.status ||
      first.type !== "OB_CREATED" ||
      first.from_status !== null ||
      first.to_status !== "CANDIDATE"
    ) {
      context.addIssue({
        code: "custom",
        message: "Order-block lifecycle is inconsistent",
      });
    }
    if (
      zone.lifecycle.some(
        (event, index) =>
          index > 0 &&
          (Date.parse(event.confirmed_at) <
            Date.parse(zone.lifecycle[index - 1].confirmed_at) ||
            event.from_status !== zone.lifecycle[index - 1].to_status),
      )
    ) {
      context.addIssue({
        code: "custom",
        message: "Order-block lifecycle is not chronological",
      });
    }
  });
const MacdPointSchema = z
  .object({
    timestamp: TimestampSchema,
    macd_line: FiniteNumberSchema.nullable(),
    signal_line: FiniteNumberSchema.nullable(),
    histogram: FiniteNumberSchema.nullable(),
  })
  .passthrough();
const AnalysisPayloadSchema = z
  .object({
    symbol: SymbolSchema,
    timeframe: TimeframeSchema,
    source: z.string().min(1),
    retrieved_at: TimestampSchema,
    data_cutoff_at: TimestampSchema,
    provenance: ProvenanceSchema,
    evaluation: z
      .object({
        indicator_snapshot: z
          .object({ macd: z.object({ points: z.array(MacdPointSchema) }).passthrough() })
          .nullable(),
        market_structure_snapshot: z.record(
          z.string(),
          MarketStructureSnapshotSchema,
        ),
        smc_ict_snapshot: z
          .object({
            fvg: z.object({ zones: z.array(FvgZoneSchema) }).passthrough(),
            order_blocks: z
              .object({ order_blocks: z.array(OrderBlockZoneSchema) })
              .passthrough(),
          })
          .nullable(),
      })
      .passthrough(),
  })
  .passthrough()
  .superRefine((analysis, context) => {
    if (
      analysis.symbol !== analysis.provenance.symbol ||
      analysis.timeframe !== analysis.provenance.timeframe ||
      analysis.source !== analysis.provenance.provider ||
      analysis.retrieved_at !== analysis.provenance.retrieved_at ||
      analysis.data_cutoff_at !== analysis.provenance.data_cutoff_at
    ) {
      context.addIssue({ code: "custom", message: "Analysis provenance mismatch" });
    }
  });

async function parseResponse(response: Response): Promise<unknown> {
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const parsed = ApiErrorEnvelopeSchema.safeParse(payload);
    if (parsed.success) {
      throw new ApiRequestError(
        response.status,
        parsed.data.error.code,
        parsed.data.error.message,
        parsed.data.error.details,
      );
    }
    throw new ApiRequestError(
      response.status,
      "UNSTRUCTURED_ERROR_RESPONSE",
      `Request failed with status ${response.status}`,
    );
  }
  return payload;
}

export class ApiRequestError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details?: unknown,
  ) {
    super(message);
    this.name = "ApiRequestError";
  }
}

export async function fetchCandles(
  symbol: SymbolCode,
  timeframe: Timeframe,
  signal?: AbortSignal,
): Promise<MarketDataResponse> {
  const params = new URLSearchParams({ symbol, timeframe, limit: "500" });
  const response = await fetch(`/api/market/candles?${params}`, { signal, cache: "no-store" });
  const parsed = MarketDataSchema.parse(await parseResponse(response));
  if (parsed.symbol !== symbol || parsed.timeframe !== timeframe) {
    throw new Error("Market-data identity does not match the request.");
  }
  return {
    ...parsed,
    candles: parsed.candles.map((candle) => ({
      ...candle,
      open: String(candle.open),
      high: String(candle.high),
      low: String(candle.low),
      close: String(candle.close),
      volume: String(candle.volume),
    })),
  };
}

export async function fetchAnalysis(
  symbol: SymbolCode,
  timeframe: Timeframe,
  signal?: AbortSignal,
): Promise<AnalysisViewModel> {
  const response = await fetch("/api/analysis", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbol, timeframe }),
    signal,
  });
  return normalizeAnalysis(await parseResponse(response), symbol, timeframe);
}

export async function fetchLatestSignal(
  symbol: SymbolCode,
  timeframe: Timeframe,
  signal?: AbortSignal,
): Promise<SignalViewModel> {
  const response = await fetch("/api/signals", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbol, timeframe }),
    signal,
    cache: "no-store",
  });
  return parseSignalPayload(await parseResponse(response), symbol, timeframe);
}

export function parseSignalPayload(
  payload: unknown,
  requestedSymbol: SymbolCode,
  requestedTimeframe: Timeframe,
): SignalViewModel {
  const parsed = SignalPayloadSchema.safeParse(payload);
  if (!parsed.success) {
    throw new Error("Signal response failed safety validation.");
  }
  if (parsed.data.symbol !== requestedSymbol || parsed.data.timeframe !== requestedTimeframe) {
    throw new Error("Signal response identity does not match the request.");
  }
  return {
    symbol: parsed.data.symbol,
    timeframe: parsed.data.timeframe,
    decisionMode: parsed.data.decision_mode,
    aiValidationStatus: parsed.data.ai_validation_status,
    algorithmDecision: parsed.data.algorithm_decision,
    aiDecision: parsed.data.ai_decision,
    finalDecision: parsed.data.final_decision,
    entryMin: parsed.data.entry_min,
    entryMax: parsed.data.entry_max,
    takeProfit: parsed.data.take_profit,
    stopLoss: parsed.data.stop_loss,
    confidence: parsed.data.confidence,
    riskReward: parsed.data.risk_reward,
    reason: parsed.data.reason_codes,
    factors: {},
    validatedAt: parsed.data.validated_at,
  };
}

export function normalizeAnalysis(
  payload: unknown,
  requestedSymbol: SymbolCode,
  requestedTimeframe: Timeframe,
): AnalysisViewModel {
  const parsed = AnalysisPayloadSchema.parse(payload);
  if (parsed.symbol !== requestedSymbol || parsed.timeframe !== requestedTimeframe) {
    throw new Error("Analysis response identity does not match the request.");
  }
  const structure = parsed.evaluation.market_structure_snapshot[requestedTimeframe];
  const fvgZones = parsed.evaluation.smc_ict_snapshot?.fvg.zones ?? [];
  const orderBlocks = parsed.evaluation.smc_ict_snapshot?.order_blocks.order_blocks ?? [];
  const structures: AnalysisViewModel["structures"] = (
    structure?.structure_events ?? []
  ).flatMap((event) => {
    if (event.type === "BREAK") return [];
    return [{
      id: `${event.type}:${event.broken_structure_id}:${event.confirmed_at}`,
      type: event.type,
      direction: event.direction,
      createdAt: event.timestamp,
      confirmedAt: event.confirmed_at,
      price: event.price,
    }];
  });
  const fvgViewModels: AnalysisViewModel["zones"] = fvgZones.map((zone) => {
    const isTerminal = ["FILLED", "INVERTED", "INVALIDATED", "EXPIRED"].includes(
      zone.lifecycle_state,
    );
    const latest = zone.lifecycle[zone.lifecycle.length - 1];
    return {
      id: zone.zone_id,
      kind: "FVG",
      direction: zone.direction,
      lower: zone.lower,
      upper: zone.upper,
      createdAt: zone.created_at,
      confirmedAt: zone.confirmed_at,
      validatedAt: null,
      updatedAt: zone.last_updated_at,
      mitigatedAt: null,
      invalidatedAt: null,
      status: zone.status,
      lifecycleState: zone.lifecycle_state,
      lifecycle: zone.lifecycle.map((event) => ({
        type: event.event_type,
        occurredAt: event.occurred_at,
        fromState: event.from_state,
        toState: event.to_state,
      })),
      terminalAt: isTerminal ? latest.occurred_at : null,
      isTerminal,
    };
  });
  const orderBlockViewModels: AnalysisViewModel["zones"] = orderBlocks.map(
    (zone) => {
      const isTerminal = ["INVALIDATED", "EXPIRED"].includes(zone.status);
      const latest = zone.lifecycle[zone.lifecycle.length - 1];
      return {
        id: zone.zone_id,
        kind: "ORDER_BLOCK",
        direction: zone.direction,
        lower: zone.zone_low,
        upper: zone.zone_high,
        createdAt: zone.created_at,
        confirmedAt: null,
        validatedAt: zone.validated_at,
        updatedAt: latest.confirmed_at,
        mitigatedAt: zone.mitigated_at,
        invalidatedAt: zone.invalidated_at,
        status: zone.status,
        lifecycleState: zone.status,
        lifecycle: zone.lifecycle.map((event) => ({
          type: event.type,
          occurredAt: event.confirmed_at,
          fromState: event.from_status,
          toState: event.to_status,
        })),
        terminalAt: isTerminal ? latest.confirmed_at : null,
        isTerminal,
      };
    },
  );
  return {
    supports: (structure?.support_candidates ?? []).map((level) => ({
      id: level.zone_id,
      lower: level.lower_bound,
      upper: level.upper_bound,
      anchorPrice: level.anchor_price,
      label: "SUPPORT",
      createdAt: level.created_at,
      confirmedAt: null,
    })),
    resistances: (structure?.resistance_candidates ?? []).map((level) => ({
      id: level.zone_id,
      lower: level.lower_bound,
      upper: level.upper_bound,
      anchorPrice: level.anchor_price,
      label: "RESISTANCE",
      createdAt: level.created_at,
      confirmedAt: null,
    })),
    swings: (structure?.confirmed_swings ?? []).map((swing) => ({
      id: swing.swing_id,
      kind: swing.kind,
      pivotAt: swing.pivot_timestamp,
      confirmedAt: swing.confirmed_at,
      price: swing.price,
    })),
    structures,
    zones: [...fvgViewModels, ...orderBlockViewModels],
    macd:
      parsed.evaluation.indicator_snapshot?.macd.points.map((point) => ({
        timestamp: point.timestamp,
        macd: point.macd_line,
        signal: point.signal_line,
        histogram: point.histogram,
      })) ?? [],
  };
}

export type { Decision };
