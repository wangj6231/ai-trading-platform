import { z } from "zod";
import { accountSchema, analyticsMetricsSchema, analyticsSchema, attachmentSchema, fillSchema, orderIntentSchema, orderSchema, pageSchema, positionSchema, tradeSchema, type AnalyticsMetrics, type MetadataPatch, type OrderIntent, type Page } from "./contracts";

// Pure contract reconciliation only. No fetch, authentication, runtime switch or financial calculation.
const record = z.record(z.string(), z.unknown());
const records = z.array(z.unknown());
const metadata = z.object({ notes: z.string().max(4000), tags: z.array(z.string().max(40)).max(20), version: z.number().int().positive(), created_at: z.iso.datetime(), updated_at: z.iso.datetime() });
const absent = z.null();
export function normalizeHttpAccount(input: unknown) {
  const dto = record.parse(input); const capabilities = record.parse(dto.capabilities);
  return accountSchema.parse({
    accountId: dto.account_id, name: dto.name, environment: dto.environment, executionProvider: dto.execution_provider,
    accountingProfile: dto.accounting_profile, numericPolicyVersion: dto.numeric_policy_version, positionModel: dto.position_model, status: dto.status, currency: dto.currency,
    balance: dto.cash_balance, initialBalance: dto.initial_balance, reservedCollateral: dto.reserved_collateral, availableBalance: dto.available_balance,
    equity: dto.equity, realizedPnl: dto.realized_pnl, unrealizedPnl: dto.unrealized_pnl, valuationAt: dto.valuation_at, valuationStatus: dto.valuation_status,
    valuations: records.parse(dto.valuations).map(input => { const item = record.parse(input); return { symbol: item.symbol, price: item.valuation_price, valuationAt: item.valuation_at, receivedAt: item.received_at }; }),
    createdAt: dto.created_at, updatedAt: dto.updated_at,
    capabilities: { supportsMarketOrder: capabilities.supports_market_order, supportsLimitOrder: capabilities.supports_limit_order, supportsShort: capabilities.supports_short, supportsScaleIn: capabilities.supports_scale_in, supportsPartialClose: capabilities.supports_partial_close },
  });
}
export function httpOrderBody(input: OrderIntent) {
  const intent = orderIntentSchema.parse(input);
  // Account is scoped by the route, never a client owner grant. Plan is not accepted by SubmitOrder.
  return { command_id: intent.commandId, symbol: intent.symbol, side: intent.side, order_type: intent.type, quantity: intent.quantity, limit_price: intent.limitPrice };
}
export function httpMetadataBody(input: MetadataPatch) {
  if (input.setup !== undefined) throw new Error("Setup is NOT_READY in PAPER_HTTP_API_V1.");
  return z.object({ notes: z.string().max(4000), tags: z.array(z.string().min(1).max(40)).max(20), expected_version: z.number().int().nonnegative() }).parse({ notes: input.notes, tags: input.tags, expected_version: input.expectedVersion });
}
export function normalizeHttpOrder(input: unknown) {
  const dto = record.parse(input);
  return orderSchema.parse({ orderId: dto.order_id, commandId: dto.command_id, accountId: dto.account_id, symbol: dto.symbol, side: dto.side, type: dto.order_type,
    quantity: dto.quantity, filledQuantity: dto.filled_quantity, averageFill: dto.average_fill_price, limitPrice: dto.limit_price, status: dto.status,
    submissionStatus: dto.submission_status, cancellationStatus: dto.cancellation_status, cancelledAt: dto.cancelled_at,
    executionProvider: dto.execution_provider, environment: dto.environment, submittedAt: dto.accepted_at, message: dto.message, errorCode: dto.error_code,
    plan: absent.parse(dto.strategy_attribution) });
}
export function normalizeHttpFill(input: unknown) {
  const dto = record.parse(input);
  return fillSchema.parse({ fillId: dto.fill_id, orderId: dto.order_id, tradeId: dto.trade_id, accountId: dto.account_id,
    symbol: dto.symbol, side: dto.side, price: dto.price, quantity: dto.quantity, fee: dto.fee, feeCurrency: dto.fee_currency,
    time: dto.filled_at, receivedAt: dto.received_at, role: dto.role, executionSource: dto.execution_source, provenance: dto.provenance });
}
export function normalizeHttpPosition(input: unknown) {
  const dto = record.parse(input);
  return positionSchema.parse({ positionId: dto.position_id, tradeId: dto.trade_id, accountId: dto.account_id, symbol: dto.symbol, side: dto.direction,
    status: dto.status, quantity: dto.total_quantity, remainingQuantity: dto.remaining_quantity, averageEntry: dto.average_entry_price,
    valuationPrice: dto.valuation_price, valuationAt: dto.valuation_at, valuationStatus: dto.valuation_status,
    realizedPnl: dto.realized_pnl, unrealizedPnl: dto.unrealized_pnl, unrealizedPnlStatus: dto.unrealized_status,
    openedAt: dto.opened_at, closedAt: dto.closed_at, availableActions: dto.allowed_actions });
}
export function normalizeHttpTrade(input: unknown) {
  const dto = record.parse(input); const annotations = dto.annotations === null ? null : metadata.parse(dto.annotations);
  return tradeSchema.parse({ tradeId: dto.trade_id, accountId: dto.account_id, positionId: dto.position_id,
    symbol: dto.symbol, side: dto.side, status: dto.status, openedAt: dto.opened_at, closedAt: dto.closed_at,
    averageEntry: dto.average_entry_price, averageExit: dto.average_exit_price, quantity: dto.total_quantity, remainingQuantity: dto.remaining_quantity,
    grossPnl: dto.gross_pnl, netPnl: dto.net_pnl, fees: dto.total_fees, pnlPercent: dto.pnl_percent, initialRisk: dto.initial_risk, rMultiple: dto.r_multiple,
    holdingDuration: dto.holding_duration, result: dto.result, currency: dto.currency, executionProvider: dto.execution_provider,
    environment: dto.environment, accountingProfile: dto.accounting_profile, numericPolicyVersion: dto.numeric_policy_version,
    plan: absent.parse(dto.strategy_attribution), fills: records.parse(dto.fills).map(normalizeHttpFill), setup: absent.parse(dto.setup),
    notes: annotations?.notes ?? null, tags: annotations?.tags ?? null, metadataVersion: annotations?.version ?? 0,
    metadataCreatedAt: annotations?.created_at ?? null, metadataUpdatedAt: annotations?.updated_at ?? null });
}
export function normalizeHttpAttachment(input: unknown) {
  const wrapper = record.parse(input); const dto = record.parse(wrapper.attachment);
  const provenance = dto.provenance === null ? null : record.parse(dto.provenance);
  const kind = z.enum(["ENTRY_CHART", "EXIT_CHART", "USER_UPLOAD"]).parse(dto.type);
  return attachmentSchema.parse({ attachmentId: dto.attachment_id, accountId: dto.account_id, tradeId: dto.trade_id,
    kind: kind === "ENTRY_CHART" ? "ENTRY_SNAPSHOT" : kind === "EXIT_CHART" ? "EXIT_SNAPSHOT" : kind,
    status: dto.status, url: absent.parse(wrapper.url), source: provenance?.provider ?? null, provenance,
    storageReference: dto.storage_reference, mimeType: dto.mime_type, fileSize: dto.file_size,
    message: dto.failure_reason, failureCode: dto.failure_code, createdAt: dto.created_at, updatedAt: dto.updated_at, snapshotAt: dto.snapshot_at });
}
function normalizeMetrics(input: unknown): AnalyticsMetrics {
  const dto = record.parse(input);
  return analyticsMetricsSchema.parse({ totalTrades: dto.total_trades, wins: dto.wins, losses: dto.losses, breakeven: dto.breakeven,
    winRate: dto.win_rate, netPnl: dto.net_pnl, profitFactor: dto.profit_factor, averageR: dto.average_r,
    grossProfit: dto.gross_profit, grossLoss: dto.gross_loss, averageWin: dto.average_win, averageLoss: dto.average_loss,
    averagePnlPercent: dto.average_pnl_percent, bestTrade: dto.best_trade === null ? null : record.parse(dto.best_trade).net_pnl,
    worstTrade: dto.worst_trade === null ? null : record.parse(dto.worst_trade).net_pnl,
    grossPnl: dto.gross_pnl, totalFees: dto.total_fees, rObservations: dto.r_observations });
}
export function normalizeHttpAnalytics(input: unknown, source: string) {
  const wrapper = record.parse(input); const dto = record.parse(wrapper.analytics); const scope = record.parse(dto.scope);
  // By-strategy is unavailable in V1. Reject unexpected strategy rows, do not fabricate them.
  z.array(z.never()).parse(dto.by_strategy);
  return analyticsSchema.parse({ accountId: scope.trading_account_id, currency: dto.currency, metrics: normalizeMetrics(dto.overall),
    includedTradeIds: absent.parse(wrapper.included_trade_ids), membershipStatus: wrapper.membership_status,
    strategyBreakdownStatus: dto.strategy_breakdown_status, scope: "CLOSED_EXECUTED_TRADES_ONLY", source, asOf: dto.as_of, query: scope.query,
    breakdowns: [ { dimension: "SIDE", label: "LONG", metrics: normalizeMetrics(dto.long_stats) }, { dimension: "SIDE", label: "SHORT", metrics: normalizeMetrics(dto.short_stats) },
      ...records.parse(dto.by_symbol).map(input => { const row = record.parse(input); return { dimension: "SYMBOL", label: row.symbol, metrics: normalizeMetrics(row.stats) }; }) ] });
}
export function normalizeHttpPage<T>(input: unknown, normalizeItem: (input: unknown) => T): Page<T> {
  const dto = z.object({ items: records, next_cursor: z.string().max(4096).nullable(), has_more: z.boolean(), as_of: z.iso.datetime() }).parse(input);
  const page = pageSchema(z.unknown()).parse({ items: dto.items, nextCursor: dto.next_cursor, hasMore: dto.has_more, asOf: dto.as_of });
  return { ...page, items: dto.items.map(normalizeItem) };
}
