import recordedContract from "./recorded-contract.fixture.json";
import { normalizeHttpAccount, normalizeHttpOrder, normalizeHttpTrade, normalizeHttpAnalytics, normalizeHttpPage, normalizeHttpAttachment } from "./http-contract";
import { normalizeProductSnapshot, tradeSchema, ready, type Account, type Analytics, type AnalyticsMetrics, type Attachment, type Order, type Position, type ProductSnapshot, type StrategyPlan, type Trade, type ResourceStatus } from "./contracts";

export const FIXTURE_SOURCE = "DEV / FIXTURE";
export const fixtureIntentInstructions = "DEV script: BTCUSDT BUY quantity 0.1; MARKET sends no execution price, LIMIT condition is 105. Unsupported combinations receive explicit fixture rejection. B scale in → C partial close → D close; direct close also supported.";
export const fixtureTime = "2026-10-08T02:00:00Z";
export const fixtureAccount: Account = {
  accountId: "dev-paper-01", name: "Paper Account", environment: "PAPER", executionProvider: "PAPER",
  accountingProfile: "PAPER_DIRECTIONAL_V1", positionModel: "ONE_WAY_NET_POSITION", status: "ACTIVE", currency: "USDT",
  capabilities: { supportsMarketOrder: true, supportsLimitOrder: true, supportsShort: true, supportsScaleIn: true, supportsPartialClose: true },
  balance: "10000.00", equity: "10000.00", realizedPnl: "0.00", unrealizedPnl: "0.00", valuationAt: fixtureTime,
};
export const fixtureLongPlan: StrategyPlan = {
  symbol: "BTCUSDT", direction: "LONG", entryMin: "99", entryMax: "100", takeProfit: "106", stopLoss: "95", riskReward: "1.2",
  strategyName: "Deterministic MTF", strategyVersion: "DEV-plan-v1", configIdentity: "dev-config-01", evaluationReference: "dev-evaluation-01",
  cutoff: "2026-10-08T01:45:00Z", signalTimeframe: "15m", source: FIXTURE_SOURCE, fixtureOnly: "FIXTURE_ONLY",
};
export const fixtureShortPlan: StrategyPlan = { ...fixtureLongPlan, direction: "SHORT", takeProfit: "94", stopLoss: "105", evaluationReference: "dev-evaluation-short" };
export const fixtureScenarios = [
  { id: "A", label: "A · LONG plan → confirmed fill" }, { id: "E", label: "E · SHORT plan / actual BUY" },
  { id: "F", label: "F · Rejected order" }, { id: "G", label: "G · Unknown execution" },
  { id: "H", label: "H · Closed trades / snapshot states" }, { id: "I", label: "I · Empty journal" },
  { id: "TECHNICAL", label: "Technical submit error" },
  { id: "K", label: "K · Recorded HTTP contract / nullable evidence" },
] as const;
export type FixtureScenario = typeof fixtureScenarios[number]["id"];
export const emptyMetrics: AnalyticsMetrics = {
  totalTrades: 0, wins: 0, losses: 0, breakeven: 0, winRate: null, netPnl: "0.00", profitFactor: null, averageR: null,
  grossProfit: "0.00", grossLoss: "0.00", averageWin: null, averageLoss: null, averagePnlPercent: null, bestTrade: null, worstTrade: null,
};
const closedMetrics: AnalyticsMetrics = { totalTrades: 1, wins: 1, losses: 0, breakeven: 0, winRate: "100", netPnl: "0.62", profitFactor: null, averageR: "1.24", grossProfit: "0.62", grossLoss: "0.00", averageWin: "0.62", averageLoss: null, averagePnlPercent: "4.0924", bestTrade: "0.62", worstTrade: "0.62" };
const reviewMetrics: AnalyticsMetrics = { totalTrades: 3, wins: 1, losses: 1, breakeven: 1, winRate: "33.3333", netPnl: "0.32", profitFactor: "2.0667", averageR: "0.2133", grossProfit: "0.62", grossLoss: "0.30", averageWin: "0.62", averageLoss: "-0.30", averagePnlPercent: "0.3641", bestTrade: "0.62", worstTrade: "-0.30" };
export function fixtureAnalytics(trades: Trade[], review = false): Analytics {
  // Select pre-authored metric sets, never calculate financial formulas.
  const completed = trades.filter((trade) => trade.status === "CLOSED" && trade.fills.length > 0);
  const directMetrics: Record<string, AnalyticsMetrics> = {
    "0.81": { ...closedMetrics, netPnl: "0.405", grossProfit: "0.405", averageWin: "0.405", averageR: "0.81", averagePnlPercent: "6.8182", bestTrade: "0.405", worstTrade: "0.405" },
    "1.16": { ...closedMetrics, netPnl: "0.58", grossProfit: "0.58", averageWin: "0.58", averageR: "1.16", averagePnlPercent: "5.8", bestTrade: "0.58", worstTrade: "0.58" },
    "1.45": { ...closedMetrics, netPnl: "0.725", grossProfit: "0.725", averageWin: "0.725", averageR: "1.45", averagePnlPercent: "4.7855", bestTrade: "0.725", worstTrade: "0.725" },
  };
  const metrics = completed.length === 0 ? emptyMetrics : review ? reviewMetrics : directMetrics[completed[0].rMultiple ?? ""] ?? closedMetrics;
  const longMetrics = review ? { ...closedMetrics, totalTrades: 2, breakeven: 1, winRate: "50", averageR: "0.62", averagePnlPercent: "2.0462", worstTrade: "0.00" } : metrics;
  const shortMetrics = review ? { ...closedMetrics, wins: 0, losses: 1, winRate: "0", netPnl: "-0.30", profitFactor: "0", averageR: "-0.60", grossProfit: "0.00", grossLoss: "0.30", averageWin: null, averageLoss: "-0.30", averagePnlPercent: "-3.00", bestTrade: "-0.30", worstTrade: "-0.30" } : emptyMetrics;
  return { fixtureOnly: "FIXTURE_ONLY", strategyBreakdownStatus: "READY", accountId: fixtureAccount.accountId, currency: "USDT", includedTradeIds: completed.map((trade) => trade.tradeId), metrics: { ...metrics }, scope: "CLOSED_EXECUTED_TRADES_ONLY", source: FIXTURE_SOURCE,
    breakdowns: [ { dimension: "SIDE", label: "LONG", metrics: longMetrics }, { dimension: "SIDE", label: "SHORT", metrics: shortMetrics },
      { dimension: "STRATEGY", label: "Deterministic MTF · DEV-plan-v1", metrics }, { dimension: "SYMBOL", label: "BTCUSDT", metrics: longMetrics }, { dimension: "SYMBOL", label: "ETHUSDT", metrics: shortMetrics } ],
  };
}
export function fixtureAttachments(): Attachment[] { return [
  { attachmentId: "dev-entry-01", kind: "ENTRY_SNAPSHOT", status: "READY", url: "/fixtures/paper-entry.svg", message: null, source: FIXTURE_SOURCE },
  { attachmentId: "dev-exit-01", kind: "EXIT_SNAPSHOT", status: "PENDING", url: null, message: "Snapshot rendering is pending in the fixture.", source: FIXTURE_SOURCE },
  { attachmentId: "dev-user-01", kind: "USER_UPLOAD", status: "FAILED", url: null, message: "Fixture upload could not be stored. Trade execution remains valid.", source: FIXTURE_SOURCE },
]; }
export const lifecycleOrders: Order[] = [
  { commandId: "dev-command", orderId: "dev-order-entry", accountId: fixtureAccount.accountId, symbol: "BTCUSDT", side: "BUY", type: "MARKET", quantity: "0.1", filledQuantity: "0.1", averageFill: "100", limitPrice: null, status: "FILLED", executionProvider: "PAPER", environment: "PAPER", submittedAt: fixtureTime, message: null, plan: fixtureLongPlan },
  { commandId: "dev-command", orderId: "dev-order-scale", accountId: fixtureAccount.accountId, symbol: "BTCUSDT", side: "BUY", type: "MARKET", quantity: "0.05", filledQuantity: "0.05", averageFill: "103", limitPrice: null, status: "FILLED", executionProvider: "PAPER", environment: "PAPER", submittedAt: "2026-10-08T02:10:00Z", message: null, plan: null },
  { commandId: "dev-command", orderId: "dev-order-partial", accountId: fixtureAccount.accountId, symbol: "BTCUSDT", side: "SELL", type: "MARKET", quantity: "0.05", filledQuantity: "0.05", averageFill: "104", limitPrice: null, status: "FILLED", executionProvider: "PAPER", environment: "PAPER", submittedAt: "2026-10-08T02:20:00Z", message: null, plan: null },
  { commandId: "dev-command", orderId: "dev-order-close", accountId: fixtureAccount.accountId, symbol: "BTCUSDT", side: "SELL", type: "MARKET", quantity: "0.1", filledQuantity: "0.1", averageFill: "106", limitPrice: null, status: "FILLED", executionProvider: "PAPER", environment: "PAPER", submittedAt: "2026-10-08T02:30:00Z", message: null, plan: null },
];
const fills = [
  { fillId: "dev-fill-01", commandId: "dev-command", orderId: "dev-order-entry", accountId: fixtureAccount.accountId, time: fixtureTime, side: "BUY" as const, price: "99", quantity: "0.06", fee: "0.005", feeCurrency: "USDT" },
  { fillId: "dev-fill-02", commandId: "dev-command", orderId: "dev-order-entry", accountId: fixtureAccount.accountId, time: "2026-10-08T02:00:01Z", side: "BUY" as const, price: "101.5", quantity: "0.04", fee: "0.005", feeCurrency: "USDT" },
  { fillId: "dev-fill-03", commandId: "dev-command", orderId: "dev-order-scale", accountId: fixtureAccount.accountId, time: "2026-10-08T02:10:00Z", side: "BUY" as const, price: "102", quantity: "0.025", fee: "0.0025", feeCurrency: "USDT" },
  { fillId: "dev-fill-04", commandId: "dev-command", orderId: "dev-order-scale", accountId: fixtureAccount.accountId, time: "2026-10-08T02:10:01Z", side: "BUY" as const, price: "104", quantity: "0.025", fee: "0.0025", feeCurrency: "USDT" },
  { fillId: "dev-fill-05", commandId: "dev-command", orderId: "dev-order-partial", accountId: fixtureAccount.accountId, time: "2026-10-08T02:20:00Z", side: "SELL" as const, price: "104", quantity: "0.05", fee: "0.005", feeCurrency: "USDT" },
  { fillId: "dev-fill-06", commandId: "dev-command", orderId: "dev-order-close", accountId: fixtureAccount.accountId, time: "2026-10-08T02:30:00Z", side: "SELL" as const, price: "106", quantity: "0.1", fee: "0.01", feeCurrency: "USDT" },
];
export type LifecycleStep = "PARTIAL_FILL" | "OPEN" | "SCALED" | "PARTIAL_CLOSE" | "CLOSED";
export function lifecycleTrade(step: LifecycleStep, plan: StrategyPlan | null = fixtureLongPlan): Trade {
  const snapshot = {
    PARTIAL_FILL: { quantity: "0.06", remainingQuantity: "0.06", averageEntry: "99", realizedPnl: "0", unrealizedPnl: "0.06", fills: fills.slice(0, 1), fees: "0.005" },
    OPEN: { quantity: "0.1", remainingQuantity: "0.1", averageEntry: "100", realizedPnl: "0", unrealizedPnl: "0.40", fills: fills.slice(0, 2), fees: "0.01" },
    SCALED: { quantity: "0.15", remainingQuantity: "0.15", averageEntry: "101", realizedPnl: "0", unrealizedPnl: "0.45", fills: fills.slice(0, 4), fees: "0.015" },
    PARTIAL_CLOSE: { quantity: "0.15", remainingQuantity: "0.1", averageEntry: "101", realizedPnl: "0.16", unrealizedPnl: "0.30", fills: fills.slice(0, 5), fees: "0.02" },
    CLOSED: { quantity: "0.15", remainingQuantity: "0", averageEntry: "101", realizedPnl: "0.65", unrealizedPnl: "0", fills, fees: "0.03" },
  }[step];
  const availableActions: Position["availableActions"] = step === "CLOSED" ? [] : step === "OPEN" ? ["SCALE_IN", "CLOSE"] : step === "SCALED" ? ["PARTIAL_CLOSE", "CLOSE"] : ["CLOSE"];
  const legacy = structuredClone({ ...snapshot, positionId: "dev-position-01", tradeId: "dev-trade-01", accountId: fixtureAccount.accountId, symbol: "BTCUSDT", side: "LONG",
    status: step === "CLOSED" ? "CLOSED" : step === "PARTIAL_CLOSE" ? "PARTIALLY_CLOSED" : "OPEN", valuationPrice: "104", openedAt: fixtureTime, valuationAt: fixtureTime,
    closedAt: step === "CLOSED" ? "2026-10-08T02:30:00Z" : null, averageExit: step === "CLOSED" ? "105.33333333" : step === "PARTIAL_CLOSE" ? "104" : null,
    netPnl: step === "CLOSED" ? "0.62" : null, pnlPercent: step === "CLOSED" ? "4.0924" : null, rMultiple: step === "CLOSED" ? "1.24" : null,
    currency: "USDT", holdingDuration: step === "CLOSED" ? "30m" : null, result: step === "CLOSED" ? "WIN" : null,
    executionProvider: "PAPER", environment: "PAPER", accountingProfile: "PAPER_DIRECTIONAL_V1", plan, attachments: fixtureAttachments(), notes: "", tags: [], setup: "",
    availableActions,
  });
  const { valuationPrice, valuationAt, realizedPnl, unrealizedPnl, attachments, ...facts } = legacy;
  return tradeSchema.parse({ ...facts, grossPnl: { PARTIAL_FILL: "0", OPEN: "0", SCALED: "0", PARTIAL_CLOSE: "0.16", CLOSED: "0.65" }[step], metadataVersion: 0, fixtureOnly: { classification: "FIXTURE_ONLY", valuationPrice, valuationAt, realizedPnl, unrealizedPnl, availableActions, attachments } });
}
export function positionFromTrade(trade: Trade): Position {
  const { positionId, tradeId, accountId, symbol, side, status, quantity, remainingQuantity, averageEntry, openedAt } = trade;
  if (!positionId || !trade.fixtureOnly) throw new Error("Fixture position evidence required.");
  const { valuationPrice, realizedPnl, unrealizedPnl, valuationAt, availableActions } = trade.fixtureOnly;
  return { positionId, tradeId, accountId, symbol, side, status, quantity, remainingQuantity, averageEntry, valuationPrice, realizedPnl, unrealizedPnl, openedAt, valuationAt, availableActions };
}
// Explicit alternative close paths, authored fixtures rather than browser financial formulas.
export function directCloseFixture(trade: Trade, step: "PARTIAL_FILL" | "OPEN" | "SCALED") {
  const values = {
    PARTIAL_FILL: { quantity: "0.06", grossPnl: "0.42", netPnl: "0.405", pnlPercent: "6.8182", rMultiple: "0.81", fees: "0.015", balance: "10000.405" },
    OPEN: { quantity: "0.1", grossPnl: "0.60", netPnl: "0.58", pnlPercent: "5.8", rMultiple: "1.16", fees: "0.02", balance: "10000.58" },
    SCALED: { quantity: "0.15", grossPnl: "0.75", netPnl: "0.725", pnlPercent: "4.7855", rMultiple: "1.45", fees: "0.025", balance: "10000.725" },
  }[step];
  const order: Order = { ...lifecycleOrders[3], commandId: "dev-command", orderId: "dev-order-direct-close", quantity: values.quantity, filledQuantity: values.quantity };
  const closed: Trade = { ...trade, status: "CLOSED", remainingQuantity: "0", fixtureOnly: { ...trade.fixtureOnly!, availableActions: [], realizedPnl: values.grossPnl, unrealizedPnl: "0" }, grossPnl: values.grossPnl, netPnl: values.netPnl, pnlPercent: values.pnlPercent, rMultiple: values.rMultiple, fees: values.fees, averageExit: "106", closedAt: "2026-10-08T02:30:00Z", holdingDuration: "30m", result: "WIN", fills: [...trade.fills, { ...fills[5], orderId: order.orderId, quantity: values.quantity }] };
  return { trade: closed, order, account: { balance: values.balance, equity: values.balance, realizedPnl: values.grossPnl, unrealizedPnl: "0" } };
}
export function baseFixtureSnapshot(scenario: FixtureScenario = "A"): FixtureSnapshot {
  if (scenario === "K") {
    const trade = normalizeHttpTrade(recordedContract.trade);
    return { status: "READY", message: null, account: normalizeHttpAccount(recordedContract.account), orders: [normalizeHttpOrder(recordedContract.order)], positions: [], trades: [trade], analytics: normalizeHttpAnalytics(recordedContract.analytics, FIXTURE_SOURCE),
      source: FIXTURE_SOURCE, scenario, sessionReference: "dev-session-0", environmentLabel: "PAPER / RECORDED CONTRACT FIXTURE_ONLY", notice: "FIXTURE_ONLY · Saved backend TestClient contract evidence. No HTTP Paper runtime or server execution is enabled." };
  }
  const trades: Trade[] = scenario === "H" ? [lifecycleTrade("CLOSED"),
    { ...lifecycleTrade("CLOSED", fixtureShortPlan), tradeId: "dev-trade-loss", positionId: "dev-position-loss", symbol: "ETHUSDT", side: "SHORT", averageEntry: "100", averageExit: "103", quantity: "0.1", grossPnl: "-0.30", netPnl: "-0.30", pnlPercent: "-3.00", rMultiple: "-0.60", fees: "0", result: "LOSS", fills: [ { ...fills[0], fillId: "dev-loss-1", orderId: "dev-loss-entry", side: "SELL", price: "100", quantity: "0.1", fee: "0" }, { ...fills[5], fillId: "dev-loss-2", orderId: "dev-loss-exit", side: "BUY", price: "103", quantity: "0.1", fee: "0" } ] },
    { ...lifecycleTrade("CLOSED"), tradeId: "dev-trade-flat", positionId: "dev-position-flat", averageEntry: "100", averageExit: "100", quantity: "0.1", grossPnl: "0.00", netPnl: "0.00", pnlPercent: "0.00", rMultiple: "0.00", fees: "0", result: "BREAKEVEN", fills: [ { ...fills[0], fillId: "dev-flat-1", orderId: "dev-flat-entry", price: "100", quantity: "0.1", fee: "0" }, { ...fills[5], fillId: "dev-flat-2", orderId: "dev-flat-exit", price: "100", quantity: "0.1", fee: "0" } ] },
  ] : [];
  const reviewOrders: Order[] = scenario === "H" ? [...lifecycleOrders,
    ...trades.slice(1).flatMap((trade) => trade.fills.map((fill) => ({ ...lifecycleOrders[0], orderId: fill.orderId, symbol: trade.symbol, side: fill.side, quantity: fill.quantity, filledQuantity: fill.quantity, averageFill: fill.price, submittedAt: fill.time, plan: trade.plan }))),
    { ...lifecycleOrders[0], orderId: "dev-no-fill", status: "CANCELLED", filledQuantity: "0", averageFill: null },
    { ...lifecycleOrders[0], orderId: "dev-unfilled", status: "ACKNOWLEDGED", filledQuantity: "0", averageFill: null },
  ] : [];
  return { status: "READY", message: null, account: scenario === "H" ? { ...fixtureAccount, balance: "10000.32", equity: "10000.32", realizedPnl: "0.35" } : { ...fixtureAccount }, orders: reviewOrders, positions: trades.map(positionFromTrade), trades, analytics: fixtureAnalytics(trades, scenario === "H"), source: FIXTURE_SOURCE, scenario, sessionReference: "dev-session-0", environmentLabel: "SIMULATED TRADING / PAPER", notice: "Session-only fixture workspace. Financial values are illustrative adapter snapshots. This workspace uses DEV fixtures; backend execution is not connected." };
}

// FIXTURE_ONLY: a complete session script is not the HTTP resource contract.
export interface FixtureSnapshot {
  status: ResourceStatus; message: string | null; account: Account | null; orders: Order[]; positions: Position[]; trades: Trade[]; analytics: Analytics | null;
  source: string; scenario: string; sessionReference: string; environmentLabel: string; notice: string;
}
export function fixturePage<T>(items: T[]) { return { items, nextCursor: null, hasMore: false, asOf: fixtureTime }; }
export function toProductSnapshot(fixture: FixtureSnapshot): ProductSnapshot {
  const resource = <T,>(data: T) => ({ status: fixture.status, message: fixture.message, data });
  return normalizeProductSnapshot({
    accountId: fixture.account?.accountId ?? fixtureAccount.accountId,
    account: resource(fixture.account), orders: resource(fixturePage(fixture.orders)), positions: resource(fixturePage(fixture.positions)),
    trades: resource(fixturePage(fixture.trades)), journal: resource(fixturePage(fixture.trades)), analytics: resource(fixture.analytics),
    tradeDetails: Object.fromEntries(fixture.trades.map(trade => [trade.tradeId, ready(trade)])),
    attachments: Object.fromEntries(fixture.trades.map(trade => [trade.tradeId, ready(fixture.scenario === "K" ? normalizeHttpPage(recordedContract.attachments, normalizeHttpAttachment) : fixturePage(trade.fixtureOnly?.attachments ?? []))])),
    source: fixture.source, environmentLabel: fixture.environmentLabel, notice: fixture.notice,
    journalCapabilities: { metadata: true, setup: fixture.scenario !== "K", userUpload: fixture.scenario !== "K", strategyFilter: fixture.scenario !== "K" },
    fixtureOnly: { classification: "FIXTURE_ONLY", scenario: fixture.scenario, sessionReference: fixture.sessionReference, status: fixture.status },
  });
}
export function baseSnapshot(scenario: FixtureScenario = "A"): ProductSnapshot { return toProductSnapshot(baseFixtureSnapshot(scenario)); }
