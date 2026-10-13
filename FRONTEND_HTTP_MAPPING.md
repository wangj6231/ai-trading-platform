# Paper HTTP mapping — pre-implementation GRILL inventory

Inspected actual frontend contracts/fixture adapters, execution/Journal/Analytics
and AttachmentReader on 2026-10-09, before HTTP implementation. Frontend remains
unchanged. HTTP is transport, not financial authority.

Legend: E=EXISTING, D=DERIVABLE_READ_ONLY, N=NULL_BY_CURRENT_EVIDENCE,
G=BACKEND_GAP, U=UNSUPPORTED. Financial serialization always uses existing
decimal_text to fixed-point strings; times are UTC ISO. Never browser arithmetic.

## Account

| Frontend field | HTTP field | Authority | Nullability / class / transformation |
|---|---|---|---|
| accountId | account_id | Account | required E alias |
| name | name | none | null G NOT_READY; fixture name not copied |
| environment/executionProvider | environment/execution_provider | Account | required E |
| accountingProfile | accounting_profile | Account.accounting_profile_version | required E |
| positionModel/status/currency | position_model/status/currency | Account, reporting_currency | required E |
| capabilities.supportsMarketOrder/supportsLimitOrder/supportsShort/supportsScaleIn/supportsPartialClose | capabilities snake_case fields | explicit server capability binding | required D; unknown provider has no implicit capability |
| balance | cash_balance | Account | required E cash, not available balance |
| equity/unrealizedPnl | equity/unrealized_pnl | AccountView | nullable E |
| realizedPnl | realized_pnl | Account.realized_pnl | required E **gross**, fixture net example not authority |
| valuationAt | valuation_at | no aggregate scalar time | null N; retain plural symbol valuations |

Additional HTTP facts: initial_balance,reserved_collateral,available_balance,
numeric_policy_version,created_at,updated_at,valuation_status. Scalar
valuation_price null: cannot arbitrarily choose a symbol from multiple valuations.

## Order intent / Order

| Frontend field | HTTP field | Authority | Nullability / class / transformation |
|---|---|---|---|
| intent.accountId | scoped route account_id | server principal grant | required D, body never authorizes |
| intent.symbol/side/type/quantity/limitPrice | symbol/side/order_type/quantity/limit_price | validated OrderIntent | E; LIMIT requires price, MARKET null |
| intent.plan | not accepted | no verified attribution | null U; opaque reference not StrategyPlan |
| orderId/accountId | order_id/account_id | Order | required E |
| symbol/side/type/quantity/limitPrice | symbol/side/order_type/quantity/limit_price | Order.intent | E, nullable limit price |
| filledQuantity | filled_quantity | Order | required E |
| averageFill | average_fill_price | no canonical order-average output | null N NOT_READY |
| status | status | fill/cancellation/submission state | required D; confirmed fills preserved; no invented PENDING |
| executionProvider/environment | execution_provider/environment | scoped Account | required E |
| submittedAt | accepted_at | Order | required E |
| message | message | explicit safe error taxonomy | nullable D, never raw provider strings |
| plan | strategy_attribution | no resolver | null N |

command_id additionally required in HTTP; current frontend intent lacks it.
Future adapter retains stable command on retry. SUBMITTING is local UI only.
Submission and cancellation statuses remain separate; UNKNOWN never means reject.

## Fill / TradeFill

| Frontend field | HTTP field | Authority | Nullability / class / transformation |
|---|---|---|---|
| fillId/orderId/accountId | fill_id/order_id/account_id | ExecutionEvent.event_id/internal_order_id/trading_account_id | required E aliases |
| time | filled_at | ExecutionEvent | required E |
| side/price/quantity | same | ExecutionEvent | required E |
| fee/feeCurrency | fee/fee_currency | ExecutionEvent.total_fee / Fee.currency | required E existing property, USDT |

HTTP additionally preserves trade_id,received_at,role,execution_source,bounded
canonical provenance. All multiple fills remain; no raw broker object.

## Position / inherited Trade fields

| Frontend field | HTTP field | Authority | Nullability / class / transformation |
|---|---|---|---|
| positionId | position_id | actual (account_id,symbol) key | position required D opaque composite; historical trade nullable |
| tradeId/accountId | trade_id/account_id | Position / JournalTrade | required E |
| symbol/side/status | Position.symbol/direction/status; Trade.symbol/side/status | Position + bound JournalTrade | required E |
| quantity | total_quantity | JournalTrade.quantity | required E lifetime entered, not remaining Position.quantity |
| remainingQuantity | remaining_quantity | JournalTrade / Position.quantity | required E |
| averageEntry | average_entry_price | Position inventory basis average / JournalTrade lifetime VWAP | inventory nullable E; never interchange |
| valuationPrice/valuationAt | Position.valuation_price/valuation_at; absent on TradeDTO | matched AccountView symbol valuation | nullable E for Position; Trade NOT_READY G |
| realizedPnl | Position.realized_pnl; absent on TradeDTO (gross_pnl/net_pnl are separate) | bound trade.gross_pnl for position | D explicitly gross; inherited Trade field ambiguous G |
| unrealizedPnl | Position.unrealized_pnl; absent on TradeDTO | no per-position output | null G NOT_READY; never repeat account total |
| openedAt | opened_at | bound JournalTrade | required E |
| availableActions | Position.allowed_actions; absent on TradeDTO | server capability + actual open state | D for Position; historical Trade NOT_READY G |

## Trade additional / Journal

| Frontend field | HTTP field | Authority | Nullability / class / transformation |
|---|---|---|---|
| closedAt/averageExit | closed_at/average_exit_price | JournalTrade | nullable E |
| netPnl/pnlPercent/rMultiple/fees | net_pnl/pnl_percent/r_multiple/total_fees | JournalTrade | E except R=N; pct/R nullable |
| currency | currency | Account.reporting_currency | required E |
| holdingDuration | holding_duration | JournalTrade.timedelta | nullable E duration serialization only |
| result | result | JournalTrade | nullable unless CLOSED E WIN/LOSS/BREAKEVEN |
| executionProvider/environment/accountingProfile | execution_provider/environment/accounting_profile | Account / JournalTrade | required E |
| fills | fills | JournalTrade.fills | required E complete multi-fill structure |
| plan | strategy_attribution | no resolver | null N |
| attachments | separate attachment page | AttachmentReader | E; no unbounded embedded page |
| notes/tags | annotations.notes/tags | actual annotations | nullable container E; absence not fabricated empty annotation |
| setup | setup | AnnotationPatch lacks field | null U NOT_READY |

JournalApi uses Trade, no separate schema. Metadata requires expected_version,
returns version/times; frontend seam lacks token and includes unsupported setup.
Future adapter must retain versions. Filters: symbol,side,result,closed date range,
actual tag; strategy NOT_READY. initial_risk/R null. Whole StrategyPlan is null:
symbol,direction,entryMin/Max,takeProfit,stopLoss,riskReward,strategyName/Version,
configIdentity,evaluationReference,cutoff,signalTimeframe,source in fixtures are
FIXTURE_ONLY_REMOVE_ON_HTTP_INTEGRATION, not resolved from opaque plan_reference.

## Attachment

| Frontend field | HTTP field | Authority | Nullability / class / transformation |
|---|---|---|---|
| attachmentId | attachment_id | AttachmentRead | required E |
| kind | type | AttachmentRead | D ENTRY_CHART→ENTRY_SNAPSHOT, EXIT_CHART→EXIT_SNAPSHOT, USER_UPLOAD unchanged |
| status | status | AttachmentRead | required E |
| url | url | no delivery resolver | null N; object reference is NOT URL |
| message | failure_reason | safe canonical AttachmentRead text | nullable E |
| source | provenance.provider | SnapshotOrigin | nullable G for frontend required string; upload NOT_READY |

HTTP preserves safe reference/MIME/size/times/provenance/failure. No renderer or
upload endpoint. READY metadata is not a browser delivery URL.

## Analytics

| Frontend field | HTTP field | Authority | Nullability / class / transformation |
|---|---|---|---|
| accountId/currency | scope.trading_account_id/currency | JournalAnalytics | required E |
| includedTradeIds | absent | no verified membership list | G NOT_READY; do not independently guess |
| metrics | overall | AnalyticsStats | required E |
| totalTrades/wins/losses/breakeven | total_trades/wins/losses/breakeven | AnalyticsStats | required E integer counts |
| winRate/netPnl/profitFactor/grossProfit/grossLoss/averageWin/averageLoss/averagePnlPercent | corresponding snake_case fields | AnalyticsStats | E; rates/PF/averages nullable; gross_loss positive magnitude, not fixture negative sign |
| averageR | average_r | AnalyticsStats | null N |
| bestTrade/worstTrade | best_trade.net_pnl/worst_trade.net_pnl | TradeSummary | nullable D extraction only |
| breakdowns.dimension/label/metrics | long_stats,short_stats,by_symbol | JournalAnalytics | D SIDE/SYMBOL only |
| STRATEGY rows | by_strategy + strategy_breakdown_status | no verified attribution | U NOT_READY |
| scope | CLOSED_EXECUTED_TRADES_ONLY | verified query semantics | D; preserve as_of/query separately |
| source | transport provenance | server HTTP read boundary | D, not financial evidence |

No extra expectancy/drawdown/session/setup/deviation formulas. ProductSnapshot:
status/message are resource state; account/orders/positions/trades/analytics are
scoped data; source/environmentLabel/notice presentation only. scenario and
sessionReference are FIXTURE_ONLY_REMOVE_ON_HTTP_INTEGRATION, never credentials.
Paginated datasets cannot pretend completeness for includedTradeIds validation.

## Compatibility verdict before implementation

BACKEND_FRONTEND_CONTRACT_MISMATCH: required Account.name, Trade.setup/positionId/
notes/tags, inherited Trade valuation/actions/realized fields, upload source,
Analytics.includedTradeIds, metadata version and
snapshot completeness lack a compatible current contract. Preserve null and
NOT_READY, not fixtures. Full frontend HTTP integration is NOT_READY. Order/Fill/
automatic Attachment/AnalyticsStats subsets can normalize by aliases/extraction
without economic calculations. Test those and explicit mismatch in this phase.

No frontend files/Next proxies modified. Current centralized Next proxy forwards
body/status, not ETag/idempotency/auth headers. Future HTTP adapter work must
address that; current default provider stays DEV/FIXTURE.
