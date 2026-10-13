import { z } from "zod";

// Authoritative economic values stay decimal text. No accounting or rounding here.
export const decimalSchema = z.string().max(2048).regex(/^-?\d+(?:\.\d+)?$/);
const time = z.iso.datetime();
const amount = decimalSchema.nullable();
const id = z.string().min(1).max(256);
export const orderStatusSchema = z.enum(["ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED", "CANCELLED", "REJECTED", "UNKNOWN"]);
export const resourceStatusSchema = z.enum(["LOADING", "EMPTY", "READY", "ERROR", "UNAVAILABLE", "NOT_READY"]);
const actions = z.array(z.enum(["SCALE_IN", "PARTIAL_CLOSE", "CLOSE"]));
export const accountSchema = z.object({
  accountId: id, name: z.string().nullable().optional(), environment: z.string(), executionProvider: z.string(),
  accountingProfile: z.string(), positionModel: z.string(), status: z.string(), currency: z.string(),
  capabilities: z.object({ supportsMarketOrder: z.boolean(), supportsLimitOrder: z.boolean(), supportsShort: z.boolean(), supportsScaleIn: z.boolean(), supportsPartialClose: z.boolean() }),
  balance: amount, equity: amount, realizedPnl: amount, unrealizedPnl: amount, valuationAt: time.nullable(),
  valuationStatus: z.string().optional(), valuations: z.array(z.object({ symbol: z.string(), price: amount, valuationAt: time, receivedAt: time })).optional(),
  initialBalance: amount.optional(), reservedCollateral: amount.optional(), availableBalance: amount.optional(),
  numericPolicyVersion: z.string().optional(), createdAt: time.optional(), updatedAt: time.nullable().optional(),
});
export const strategyPlanSchema = z.object({
  symbol: z.enum(["BTCUSDT", "ETHUSDT"]), direction: z.enum(["LONG", "SHORT"]),
  entryMin: amount, entryMax: amount, takeProfit: amount, stopLoss: amount, riskReward: amount,
  strategyName: z.string().nullable(), strategyVersion: z.string().nullable(), configIdentity: z.string().nullable(),
  evaluationReference: z.string().nullable(), cutoff: time, signalTimeframe: z.literal("15m"),
  source: z.enum(["BACKEND", "DEV / FIXTURE"]), fixtureOnly: z.literal("FIXTURE_ONLY").optional(),
});
export const orderIntentSchema = z.object({
  commandId: id, accountId: id, symbol: z.enum(["BTCUSDT", "ETHUSDT"]), side: z.enum(["BUY", "SELL"]),
  type: z.enum(["MARKET", "LIMIT"]), quantity: decimalSchema.regex(/^(?!0+(?:\.0+)?$)\d+(?:\.\d+)?$/),
  limitPrice: amount, plan: strategyPlanSchema.nullable().optional(),
}).superRefine((value, context) => {
  if (value.type === "LIMIT" && (!value.limitPrice || !/^(?!0+(?:\.0+)?$)\d+(?:\.\d+)?$/.test(value.limitPrice))) context.addIssue({ code: "custom", message: "A positive limit price is required.", path: ["limitPrice"] });
  if (value.type === "MARKET" && value.limitPrice !== null) context.addIssue({ code: "custom", message: "Market orders cannot supply a confirmed price.", path: ["limitPrice"] });
});
export const orderSchema = z.object({
  orderId: id, commandId: id, accountId: id, symbol: z.string(), side: z.enum(["BUY", "SELL"]),
  type: z.enum(["MARKET", "LIMIT"]), quantity: decimalSchema, filledQuantity: decimalSchema, averageFill: amount,
  limitPrice: amount, status: orderStatusSchema, executionProvider: z.string(), environment: z.string(),
  submittedAt: time, message: z.string().nullable(), plan: strategyPlanSchema.nullable().optional(),
  submissionStatus: z.enum(["ACKNOWLEDGED", "REJECTED", "UNKNOWN"]).optional(),
  cancellationStatus: z.enum(["CANCELLED", "UNKNOWN", "REJECTED"]).nullable().optional(),
  cancelledAt: time.nullable().optional(), errorCode: z.string().nullable().optional(),
});
export const fillSchema = z.object({
  fillId: id, orderId: id, accountId: id, time, side: z.enum(["BUY", "SELL"]),
  price: decimalSchema, quantity: decimalSchema, fee: amount, feeCurrency: z.string().nullable(),
  tradeId: id.optional(), symbol: z.string().optional(), receivedAt: time.optional(), role: z.string().optional(),
  executionSource: z.string().optional(), provenance: z.record(z.string(), z.unknown()).nullable().optional(),
});
export const attachmentSchema = z.object({
  attachmentId: id, kind: z.enum(["ENTRY_SNAPSHOT", "EXIT_SNAPSHOT", "USER_UPLOAD"]),
  status: z.enum(["PENDING", "READY", "FAILED"]), url: z.string().nullable(), message: z.string().nullable(),
  source: z.string().nullable(), accountId: id.optional(), tradeId: id.optional(),
  provenance: z.record(z.string(), z.unknown()).nullable().optional(), storageReference: z.string().max(512).nullable().optional(),
  mimeType: z.string().nullable().optional(), fileSize: z.number().int().nonnegative().nullable().optional(),
  createdAt: time.optional(), updatedAt: time.nullable().optional(), snapshotAt: time.nullable().optional(), failureCode: z.string().nullable().optional(),
});
const executionIdentity = {
  tradeId: id, accountId: id, symbol: z.string(), side: z.enum(["LONG", "SHORT"]),
  status: z.enum(["OPEN", "PARTIALLY_CLOSED", "CLOSED"]), quantity: decimalSchema, remainingQuantity: decimalSchema,
  averageEntry: amount, openedAt: time,
};
export const positionSchema = z.object({
  ...executionIdentity, positionId: id, valuationPrice: amount, realizedPnl: amount, unrealizedPnl: amount, valuationAt: time.nullable(), availableActions: actions,
  valuationStatus: z.string().optional(), unrealizedPnlStatus: z.string().optional(), closedAt: time.nullable().optional(),
});
export const tradeSchema = z.object({
  ...executionIdentity, positionId: id.nullable(),
  closedAt: time.nullable(), averageExit: amount, grossPnl: amount.optional(), netPnl: amount, pnlPercent: amount, rMultiple: amount,
  initialRisk: amount.optional(), fees: amount, currency: z.string(), holdingDuration: z.string().nullable(), result: z.enum(["WIN", "LOSS", "BREAKEVEN"]).nullable(),
  executionProvider: z.string(), environment: z.string(), accountingProfile: z.string(), numericPolicyVersion: z.string().optional(),
  fills: z.array(fillSchema), plan: strategyPlanSchema.nullable().optional(),
  notes: z.string().nullable(), tags: z.array(z.string()).nullable(), metadataVersion: z.number().int().nonnegative(),
  metadataCreatedAt: time.nullable().optional(), metadataUpdatedAt: time.nullable().optional(), setup: z.string().nullable().optional(),
  // Legacy demonstration details are explicitly not required historical Trade facts.
  fixtureOnly: z.object({ classification: z.literal("FIXTURE_ONLY"), valuationPrice: amount, valuationAt: time.nullable(), realizedPnl: amount, unrealizedPnl: amount, availableActions: actions, attachments: z.array(attachmentSchema) }).optional(),
}).superRefine((value, context) => {
  if (value.fills.some((fill) => fill.accountId !== value.accountId || fill.tradeId && fill.tradeId !== value.tradeId)) context.addIssue({ code: "custom", message: "Fill scope mismatch." });
  if (value.status !== "CLOSED" && value.result !== null) context.addIssue({ code: "custom", message: "An open trade has no completed result." });
  if (value.status === "CLOSED" && value.closedAt === null) context.addIssue({ code: "custom", message: "Closed timestamp required." });
});
export const analyticsMetricsSchema = z.object({
  totalTrades: z.number().int().nonnegative(), wins: z.number().int().nonnegative(), losses: z.number().int().nonnegative(), breakeven: z.number().int().nonnegative(),
  winRate: amount, netPnl: amount, profitFactor: amount, averageR: amount, grossProfit: amount,
  grossLoss: decimalSchema.regex(/^\d+(?:\.\d+)?$/).nullable(),
  averageWin: amount, averageLoss: amount, averagePnlPercent: amount, bestTrade: amount, worstTrade: amount,
  grossPnl: amount.optional(), totalFees: amount.optional(), rObservations: z.number().int().nonnegative().optional(),
});
export const analyticsSchema = z.object({
  accountId: id, currency: z.string(), includedTradeIds: z.array(id).nullable().optional(), metrics: analyticsMetricsSchema,
  membershipStatus: z.string().optional(), strategyBreakdownStatus: z.enum(["READY", "NOT_READY_NO_VERIFIED_ATTRIBUTION"]),
  breakdowns: z.array(z.object({ dimension: z.enum(["SIDE", "STRATEGY", "SYMBOL"]), label: z.string(), metrics: analyticsMetricsSchema })),
  scope: z.literal("CLOSED_EXECUTED_TRADES_ONLY"), source: z.string(), asOf: time.optional(), query: z.record(z.string(), z.unknown()).optional(),
  fixtureOnly: z.literal("FIXTURE_ONLY").optional(),
}).superRefine((value, context) => {
  if (value.strategyBreakdownStatus !== "READY" && value.breakdowns.some((row) => row.dimension === "STRATEGY")) context.addIssue({ code: "custom", message: "Unverified strategy breakdown." });
});
export function pageSchema<T extends z.ZodType>(item: T) {
  return z.object({ items: z.array(item), nextCursor: z.string().max(4096).nullable(), hasMore: z.boolean(), asOf: time })
    .superRefine((value, context) => { if (value.hasMore !== (value.nextCursor !== null)) context.addIssue({ code: "custom", message: "Pagination continuation mismatch." }); });
}
export function resourceSchema<T extends z.ZodType>(data: T) {
  return z.object({ status: resourceStatusSchema, message: z.string().nullable(), data: data.nullable(), error: z.object({ code: z.string(), httpStatus: z.number().int(), requestId: z.string().nullable() }).optional() });
}
export const productSnapshotSchema = z.object({
  accountId: id,
  account: resourceSchema(accountSchema), orders: resourceSchema(pageSchema(orderSchema)), positions: resourceSchema(pageSchema(positionSchema)),
  trades: resourceSchema(pageSchema(tradeSchema)), journal: resourceSchema(pageSchema(tradeSchema)), analytics: resourceSchema(analyticsSchema),
  tradeDetails: z.record(z.string(), resourceSchema(tradeSchema)), attachments: z.record(z.string(), resourceSchema(pageSchema(attachmentSchema))),
  fills: z.record(z.string(), resourceSchema(pageSchema(fillSchema))).default({}),
  source: z.string(), environmentLabel: z.string(), notice: z.string(),
  journalCapabilities: z.object({ metadata: z.boolean(), setup: z.boolean(), userUpload: z.boolean(), strategyFilter: z.boolean() }),
  fixtureOnly: z.object({ classification: z.literal("FIXTURE_ONLY"), scenario: z.string(), sessionReference: z.string(), status: resourceStatusSchema }).optional(),
}).superRefine((value, context) => {
  const records = [value.account.data, value.analytics.data, ...(value.orders.data?.items ?? []), ...(value.positions.data?.items ?? []), ...(value.trades.data?.items ?? []), ...(value.journal.data?.items ?? []), ...Object.values(value.tradeDetails).flatMap((resource) => resource.data ? [resource.data] : [])];
  if (records.some((record) => record && record.accountId !== value.accountId)) context.addIssue({ code: "custom", message: "Account isolation violated." });
  for (const [tradeId, resource] of Object.entries(value.tradeDetails)) if (resource.data && resource.data.tradeId !== tradeId) context.addIssue({ code: "custom", message: "Trade detail identity mismatch." });
  for (const [tradeId, resource] of Object.entries(value.attachments)) if (resource.data?.items.some((item) => item.accountId && item.accountId !== value.accountId || item.tradeId && item.tradeId !== tradeId)) context.addIssue({ code: "custom", message: "Attachment scope mismatch." });
  for (const [tradeId, resource] of Object.entries(value.fills)) if (resource.data?.items.some((item) => item.accountId !== value.accountId || item.tradeId !== tradeId)) context.addIssue({ code: "custom", message: "Fill page scope mismatch." });
  // A partial Journal page is not Analytics membership authority.
});
export type Account = z.infer<typeof accountSchema>;
export type StrategyPlan = z.infer<typeof strategyPlanSchema>;
export type OrderIntent = z.infer<typeof orderIntentSchema>;
export type Order = z.infer<typeof orderSchema>;
export type Position = z.infer<typeof positionSchema>;
export type Trade = z.infer<typeof tradeSchema>;
export type Attachment = z.infer<typeof attachmentSchema>;
export type Analytics = z.infer<typeof analyticsSchema>;
export type AnalyticsMetrics = z.infer<typeof analyticsMetricsSchema>;
export type ProductSnapshot = z.infer<typeof productSnapshotSchema>;
export type ResourceStatus = z.infer<typeof resourceStatusSchema>;
export type Resource<T> = { status: ResourceStatus; message: string | null; data: T | null; error?: { code: string; httpStatus: number; requestId: string | null } };
export type RuntimeSelection = { mode: "FIXTURE" } | { mode: "HTTP"; accountId: string } | { mode: "UNAVAILABLE"; code: string };
export type Page<T> = { items: T[]; nextCursor: string | null; hasMore: boolean; asOf: string };
export type PageQuery = { limit?: number; cursor?: string; asOf?: string; symbol?: string; side?: string; result?: string; closedFrom?: string; closedTo?: string; tag?: string };
export type MetadataPatch = { notes: string; tags: string[]; expectedVersion: number; setup?: string };
export type MetadataResult = { kind: "SAVED"; metadataVersion: number } | { kind: "CONFLICT"; message: string } | { kind: "ERROR"; message: string };
export type ExecutionResponse = { kind: "ORDER"; order: Order } | { kind: "ERROR"; message: string; code?: string };
export interface AccountApi { getAccount(): Promise<Account | null> }
export interface ExecutionApi {
  submit(intent: OrderIntent): Promise<ExecutionResponse>;
  refreshOrder(orderId: string): Promise<ExecutionResponse>;
  cancel(orderId: string): Promise<ExecutionResponse>;
  // FIXTURE_ONLY convenience: V1 HTTP has no position-action endpoint.
  positionAction?(positionId: string, action: "SCALE_IN" | "PARTIAL_CLOSE" | "CLOSE"): Promise<ExecutionResponse>;
  getOrders(query?: PageQuery): Promise<Page<Order>>; getPositions(): Promise<Page<Position>>;
}
export interface JournalApi {
  getTrades(query?: PageQuery): Promise<Page<Trade>>; getJournal(query?: PageQuery): Promise<Page<Trade>>;
  getTrade(tradeId: string): Promise<Trade | null>; getAttachments(tradeId: string, query?: PageQuery): Promise<Page<Attachment>>;
  getFills?(tradeId: string, query?: PageQuery): Promise<Page<z.infer<typeof fillSchema>>>;
  saveMetadata(tradeId: string, metadata: MetadataPatch): Promise<MetadataResult>;
  addUpload(tradeId: string, file: File): Promise<void>;
}
export interface AnalyticsApi { getAnalytics(): Promise<Analytics | null> }
export interface ProductApis { account: AccountApi; execution: ExecutionApi; journal: JournalApi; analytics: AnalyticsApi }
export function normalizeProductSnapshot(input: unknown): ProductSnapshot { return productSnapshotSchema.parse(input); }
export function unloaded<T>(status: ResourceStatus = "LOADING", message: string | null = null): Resource<T> { return { status, message, data: null }; }
export function ready<T>(data: T): Resource<T> { return { status: "READY", message: null, data }; }
export function createProductSnapshot(accountId: string, presentation: Pick<ProductSnapshot, "source" | "environmentLabel" | "notice">): ProductSnapshot {
  return normalizeProductSnapshot({ accountId, ...presentation, account: unloaded(), orders: unloaded(), positions: unloaded(), trades: unloaded(), journal: unloaded(), analytics: unloaded(), tradeDetails: {}, attachments: {}, journalCapabilities: { metadata: false, setup: false, userUpload: false, strategyFilter: false } });
}
