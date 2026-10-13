# Market Observation Lifecycle V1

Server-owned delivery lifecycle, separate from order and trade lifecycles.

1. Lifespan reads explicit worker opt-in and existing InstrumentProfile/provider
   registries. Starts the single owned task; HTTP startup does not await candles.
2. Resolve symbol capability. Missing provider/profile/range capability is
   NOT_READY, with no fallback. No eligible pending order/open position is IDLE.
3. Acquire source/symbol PostgreSQL advisory session lock. Another owner is BUSY.
4. Read per-order last_observation_at/accepted_at and delivered checkpoint. Set
   earliest required open. Cutoff is the current UTC closed-minute boundary.
5. Fetch one shared exact contiguous range, using existing provider pagination and
   trust validator. Provider failure/429 leaves orders pending; honor Retry-After.
6. Reject incomplete/gapped/duplicate/reordered/partial/future/stale evidence.
   Persist immutable canonical observations before any financial delivery.
7. For each stable account ID, call existing ExecutionGateway.observe with the
   same current-cutoff batch. Existing command order, acceptance eligibility,
   MARKET close price, LIMIT exact touch price, fee and reducer rules apply.
8. After that account's gateway commit, append delivery checkpoint. Failure at one
   account retains retry state but allows remaining accounts to receive the batch.
9. READY means valid current-cutoff delivery completed; UNAVAILABLE means bounded
   technical/capture/delivery failure, NOT_READY means capability/freshness/capacity
   refusal. None is a strategy recommendation or a rejection of an existing order.
10. Release stream lock. Wait configured polling interval. On shutdown cancel
    provider waiting, finish owned finite DB work and release resource before
    market client/database disposal.

## Recovery matrix

| Last durable state | Next runtime behavior | Economic safety |
|---|---|---|
| Nothing delivered | Fetch first wholly post-acceptance candle through current cutoff | No earlier interval skipped |
| Captured candle only | Revalidate fresh range against immutable capture | Changed same candle conflicts |
| Gateway committed, checkpoint missing | Retry; gateway cursor/fill identity/mark prevent reapplication | No duplicate fee/fill/Journal |
| Checkpoint committed | Skip same cutoff; derive next required open from order state | No browser/volatile watermark authority |
| Untouched LIMIT | Retained next-open cursor; fetch every later required interval | A touch during outage is not skipped |
| Filled position, no pending order | Fetch latest closed candle for gateway valuation | Worker never computes unrealized PnL |
| Closed/flat account, no order | No market delivery required | No invented Journal/Analytics update |
| Data gap / malformed provider | Quarantine cycle, repeat exact range on recovery | No forward fill or optimistic fill |
| Backlog over configured cap | NOT_READY; preserve earliest required open | No history truncation |

Opening/closing a Paper trade still requires explicit authorized order intent.
The worker does not auto-close TP/SL, submit strategy signals or decide quantities.
Canonical fills alone drive Journal/Analytics through the existing ledger path.
The E2E private observation driver remains test-only and is not imported here.
