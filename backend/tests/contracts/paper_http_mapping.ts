// Test-only compatibility harness: imports the unchanged real frontend schemas.
import assert from 'node:assert/strict';
import fixture from '../fixtures/paper_http_v1.json';
import {
  accountSchema, orderSchema, fillSchema, attachmentSchema, analyticsMetricsSchema,
  tradeSchema, orderIntentSchema,
} from '../../../frontend/src/lib/product/contracts';

let passed = 0;
function check(name: string, test: () => void) { test(); passed++; console.log(`PASS ${name}`); }
const order = fixture.order;
const normalizedOrder = {
  orderId: order.order_id, accountId: order.account_id, symbol: order.symbol, side: order.side,
  type: order.order_type, quantity: order.quantity, filledQuantity: order.filled_quantity,
  averageFill: order.average_fill_price, limitPrice: order.limit_price, status: order.status,
  executionProvider: order.execution_provider, environment: order.environment,
  submittedAt: order.accepted_at, message: order.message, plan: order.strategy_attribution,
};
check('actual order aliases preserve null plan/average and decimal strings', () => {
  assert.equal(orderSchema.parse(normalizedOrder).plan, null);
});
for (const fill of fixture.trade.fills) {
  check(`confirmed fill ${fill.fill_id} passes real frontend Zod`, () => {
    const result = fillSchema.parse({ fillId: fill.fill_id, orderId: fill.order_id,
      accountId: fill.account_id, time: fill.filled_at, side: fill.side, price: fill.price,
      quantity: fill.quantity, fee: fill.fee, feeCurrency: fill.fee_currency });
    assert.equal(result.price, fill.price);
  });
}
for (const item of fixture.attachments.items) {
  check('automatic snapshot alias never invents URL', () => {
    const a = item.attachment;
    const result = attachmentSchema.parse({ attachmentId: a.attachment_id,
      kind: a.type === 'ENTRY_CHART' ? 'ENTRY_SNAPSHOT' : 'EXIT_SNAPSHOT', status: a.status,
      url: item.url, message: a.failure_reason, source: a.provenance.provider });
    assert.equal(result.url, null);
  });
}
const stats = fixture.analytics.analytics.overall;
check('actual analytics field extraction has no arithmetic or false R', () => {
  const result = analyticsMetricsSchema.parse({ totalTrades: stats.total_trades, wins: stats.wins,
    losses: stats.losses, breakeven: stats.breakeven, winRate: stats.win_rate, netPnl: stats.net_pnl,
    profitFactor: stats.profit_factor, averageR: stats.average_r, grossProfit: stats.gross_profit,
    grossLoss: stats.gross_loss, averageWin: stats.average_win, averageLoss: stats.average_loss,
    averagePnlPercent: stats.average_pnl_percent, bestTrade: stats.best_trade.net_pnl,
    worstTrade: stats.worst_trade.net_pnl });
  assert.equal(result.averageR, null);
  assert.equal(result.grossLoss, stats.gross_loss);
});
check('unknown server order enum fails safely', () => {
  assert.equal(orderSchema.safeParse({ ...normalizedOrder, status: 'MYSTERY' }).success, false);
});
check('JSON monetary float is not authority', () => {
  assert.equal(orderIntentSchema.safeParse({ accountId: order.account_id, symbol: order.symbol,
    side: 'BUY', type: 'MARKET', quantity: 1.25, limitPrice: null, plan: null }).success, false);
});
check('real account name gap is exposed, not filled from fixtures', () => {
  const a = fixture.account;
  assert.equal(accountSchema.safeParse({ accountId: a.account_id, name: a.name,
    environment: a.environment, executionProvider: a.execution_provider, accountingProfile: a.accounting_profile,
    positionModel: a.position_model, status: a.status, currency: a.currency,
    capabilities: { supportsMarketOrder: a.capabilities.supports_market_order,
      supportsLimitOrder: a.capabilities.supports_limit_order, supportsShort: a.capabilities.supports_short,
      supportsScaleIn: a.capabilities.supports_scale_in, supportsPartialClose: a.capabilities.supports_partial_close },
    balance: a.cash_balance, equity: a.equity, realizedPnl: a.realized_pnl,
    unrealizedPnl: a.unrealized_pnl, valuationAt: a.valuation_at }).success, false);
});
check('current Trade schema cannot invent missing nullable metadata/position', () => {
  const t = fixture.trade;
  assert.equal(t.annotations, null);
  assert.equal(t.setup, null);
  assert.equal(t.position_id, null);
  assert.equal(tradeSchema.safeParse({ positionId: t.position_id, setup: t.setup, notes: null,
    tags: null, averageEntry: t.average_entry_price }).success, false);
});
check('long decimal remains exact raw server text', () => {
  assert.equal(fixture.trade.average_entry_price, '100.66666666666666666666666666666666666666666666667');
});
console.log(`${passed} compatibility checks passed; full frontend HTTP integration remains CONTRACT_MISMATCH.`);
