"use client";

import Link from "next/link";
import { useRef, useState, type FormEvent } from "react";
import { orderIntentSchema, type ExecutionResponse, type Order, type Position, type OrderIntent } from "@/lib/product/contracts";
import { useProduct } from "./product-provider";
import { AccountSummary, ProductPage, ResourceGate, StatusBadge, StrategyPlanCard, Value, PageScope, PageControls } from "./product-ui";

function useCommandResponse() {
  const { snapshot } = useProduct();
  const [state, setState] = useState<{ response: ExecutionResponse; session: string } | null>(null);
  return [state?.session === (snapshot.fixtureOnly?.sessionReference ?? snapshot.accountId) ? state.response : null, (response: ExecutionResponse | null) => setState(response ? { response, session: (snapshot.fixtureOnly?.sessionReference ?? snapshot.accountId) } : null)] as const;
}
function ResponseMessage({ response }: { response: ExecutionResponse | null }) {
  if (!response) return null;
  return <div className={`product-message ${response.kind === "ERROR" ? "error" : ""}`} role="status">{response.kind === "ERROR" ? <><strong>Technical / intent error</strong><br />{response.message}</> : <><StatusBadge value={response.order.status} /> <span>{response.order.message ?? "Adapter response received."}</span></>}</div>;
}
export function PaperTradingPage() {
  const { snapshot, plan } = useProduct();
  return <ProductPage title="Paper Trading" subtitle="Review a plan. Create an intent. Inspect confirmed execution separately."><ResourceGate resource={snapshot.account}><AccountSummary /><div className="product-two-columns"><StrategyPlanCard plan={plan} /><OrderTicket key={`${plan?.evaluationReference ?? "manual"}:${(snapshot.fixtureOnly?.sessionReference ?? snapshot.accountId)}`} /></div><ResourceGate resource={snapshot.orders}><OrdersView /></ResourceGate></ResourceGate></ProductPage>;
}
function OrderTicket() {
  const { snapshot, plan, apis } = useProduct(); const account = snapshot.account.data;
  const [symbol, setSymbol] = useState<"BTCUSDT" | "ETHUSDT">(plan?.symbol ?? "BTCUSDT");
  const [side, setSide] = useState<"BUY" | "SELL">(plan?.direction === "SHORT" ? "SELL" : "BUY");
  const [type, setType] = useState<"MARKET" | "LIMIT">("MARKET");
  const [quantity, setQuantity] = useState(""); const [limitPrice, setLimitPrice] = useState(plan?.entryMin ?? "");
  const [response, setResponse] = useCommandResponse(); const [busy, setBusy] = useState(false);
  const pending = useRef<{ fingerprint: string; intent: OrderIntent } | null>(null);
  async function submit(event: FormEvent) {
    event.preventDefault(); if (!account || busy) return;
    const fingerprint = JSON.stringify({ accountId: account.accountId, symbol, side, type, quantity, limitPrice: type === "LIMIT" ? limitPrice : null });
    const commandId = pending.current?.fingerprint === fingerprint ? pending.current.intent.commandId : crypto.randomUUID();
    const parsed = orderIntentSchema.safeParse({ commandId, accountId: account.accountId, symbol, side, type, quantity, limitPrice: type === "LIMIT" ? limitPrice : null, plan });
    if (!parsed.success) { setResponse({ kind: "ERROR", message: parsed.error.issues[0].message }); return; }
    pending.current = { fingerprint, intent: parsed.data };
    setBusy(true); setResponse(null);
    try { const result = await apis.execution.submit(parsed.data); setResponse(result); if (result.kind === "ORDER") pending.current = null; } catch { setResponse({ kind: "ERROR", message: "Unable to obtain an execution response. Outcome has not been established." }); } finally { setBusy(false); }
  }
  return <section className="product-card" aria-label="Paper order ticket"><span className="section-kicker">PAPER ORDER · USER INTENT</span><h2>Order ticket</h2><p>No order is created by opening this ticket.</p><form onSubmit={submit}><div className="product-form-grid">
    <label>Symbol<select value={symbol} onChange={(e) => setSymbol(e.target.value as "BTCUSDT" | "ETHUSDT")}><option>BTCUSDT</option><option>ETHUSDT</option></select></label>
    <label>Order side<select value={side} onChange={(e) => setSide(e.target.value as "BUY" | "SELL")}><option>BUY</option><option disabled={!account?.capabilities.supportsShort}>SELL</option></select></label>
    <label>Order type<select value={type} onChange={(e) => setType(e.target.value as "MARKET" | "LIMIT")}><option disabled={!account?.capabilities.supportsMarketOrder}>MARKET</option><option disabled={!account?.capabilities.supportsLimitOrder}>LIMIT</option></select></label>
    <label>Quantity<input value={quantity} onChange={(e) => setQuantity(e.target.value)} inputMode="decimal" placeholder="Enter quantity" required /></label>
    {type === "LIMIT" && <label>Limit price · intent only<input value={limitPrice} onChange={(e) => setLimitPrice(e.target.value)} inputMode="decimal" required /></label>}
  </div><p className="product-note">MARKET sends no fill price. LIMIT price is an order condition, never a confirmed execution price.</p><p className="product-note">Review account capabilities before submitting. In DEV mode, supported intent details are in the fixture controls.</p><button type="submit" disabled={busy || !account || snapshot.account.status !== "READY"}>{busy ? "Submitting intent…" : "Submit paper intent"}</button></form><ResponseMessage response={response} />{busy && <StatusBadge value="SUBMITTING" />}</section>;
}
export function OrdersPage() { const { snapshot } = useProduct(); return <ProductPage title="Orders" subtitle="Order acknowledgment, partial fills and terminal outcomes remain distinct."><ResourceGate resource={snapshot.orders} empty="No orders yet."><OrdersView /></ResourceGate></ProductPage>; }
export function OrdersView() {
  const { snapshot, apis, fixtureControls } = useProduct(); const [response, setResponse] = useCommandResponse(); const [busy, setBusy] = useState<string | null>(null);
  async function action(orderId: string, operation: "confirm" | "cancel") {
    if (busy) return; setBusy(orderId);
    try { setResponse(await (operation === "confirm" ? apis.execution.refreshOrder(orderId) : apis.execution.cancel(orderId))); } catch { setResponse({ kind: "ERROR", message: "Execution response unavailable; no new outcome confirmed." }); } finally { setBusy(null); }
  }
  const orders = snapshot.orders.data?.items ?? [];
  const actions = (order: Order) => <div className="product-actions">{["ACKNOWLEDGED", "PARTIALLY_FILLED", "UNKNOWN"].includes(order.status) && <><button disabled={busy !== null} onClick={() => void action(order.orderId, "confirm")}>{fixtureControls && order.status !== "UNKNOWN" ? "Advance DEV fills" : "Refresh order"}</button><button disabled={busy !== null} onClick={() => void action(order.orderId, "cancel")}>Cancel order</button></>}</div>;
  return <section className="product-card" aria-label="Orders"><div className="product-card-heading"><h2>Order lifecycle</h2><span className="product-fixture-badge">{snapshot.source}</span></div><PageScope page={snapshot.orders.data} /><PageControls page={snapshot.orders.data} onLoad={apis.execution.getOrders} label="orders" /><p>Acknowledged ≠ filled. Unknown requires reconciliation; it is neither rejection nor a loss.</p>{orders.length === 0 ? <div className="product-state">No orders yet. Opening a ticket does not submit an order.</div> : <><div className="product-table-wrap product-desktop-table"><table className="product-table"><thead><tr>{["Order / account", "Symbol / side", "Type / quantity", "Filled / average", "Status", "Provider / environment", "Submitted UTC", "Actions"].map((label) => <th key={label}>{label}</th>)}</tr></thead><tbody>{orders.map((order) => <tr key={order.orderId}><td className="product-id">{order.orderId}<small>{order.accountId}</small></td><td>{order.symbol}<small>{order.side}</small></td><td>{order.type} · {order.quantity}<small>Limit: {order.limitPrice ?? "—"}</small></td><td>{order.filledQuantity}<small><Value value={order.averageFill} /></small></td><td><StatusBadge value={order.status} /><small>Submit: {order.submissionStatus ?? order.status} · Cancel: {order.cancellationStatus ?? "—"}</small><small>{order.message}</small></td><td>{order.executionProvider}<small>{order.environment}</small></td><td>{order.submittedAt}</td><td>{actions(order)}</td></tr>)}</tbody></table></div><div className="product-mobile-records">{orders.map((order) => <article className="product-record" key={order.orderId}><div className="product-card-heading"><h3>{order.symbol} · {order.side}</h3><StatusBadge value={order.status} /></div><dl className="product-facts"><dt>Order / account</dt><dd>{order.orderId}<br />{order.accountId}</dd><dt>Type / quantity</dt><dd>{order.type} · {order.quantity}</dd><dt>Submission / cancellation</dt><dd>{order.submissionStatus ?? order.status} / {order.cancellationStatus ?? "—"}</dd><dt>Filled quantity</dt><dd>{order.filledQuantity}</dd><dt>Average fill</dt><dd><Value value={order.averageFill} /></dd><dt>Limit intent</dt><dd>{order.limitPrice ?? "—"}</dd><dt>Provider / environment</dt><dd>{order.executionProvider} / {order.environment}</dd><dt>Submitted UTC</dt><dd>{order.submittedAt}</dd></dl><p>{order.message}</p>{actions(order)}</article>)}</div></>}<ResponseMessage response={response} /></section>;
}
export function PositionsPage() {
  const { snapshot, apis } = useProduct(); const [response, setResponse] = useCommandResponse(); const [busy, setBusy] = useState(false);
  async function action(position: Position, operation: "SCALE_IN" | "PARTIAL_CLOSE" | "CLOSE") {
    if (busy) return; setBusy(true);
    try { if (!apis.execution.positionAction) { setResponse({ kind: "ERROR", message: "Position action ticket NOT_READY. No HTTP position-action operation is enabled." }); return; } setResponse(await apis.execution.positionAction(position.positionId, operation)); } catch { setResponse({ kind: "ERROR", message: "Position command response unavailable. No fill confirmed." }); } finally { setBusy(false); }
  }
  return <ProductPage title="Positions" subtitle="Actual direction and quantities come from confirmed adapter fills."><ResourceGate resource={snapshot.positions} empty="No positions yet."><AccountSummary /><PageScope page={snapshot.positions.data} />{(snapshot.positions.data?.items ?? []).length === 0 ? <div className="product-state">No positions yet. An acknowledged order is not a position.</div> : <div className="product-record-grid">{(snapshot.positions.data?.items ?? []).map((position) => <article className="product-record" key={position.positionId}><div className="product-card-heading"><h2>{position.symbol} · {position.side}</h2><StatusBadge value={position.status} /></div><dl className="product-facts"><dt>Position / account</dt><dd>{position.positionId}<br />{position.accountId}</dd><dt>Total quantity</dt><dd>{position.quantity}</dd><dt>Remaining quantity</dt><dd>{position.remainingQuantity}</dd><dt>Average entry</dt><dd><Value value={position.averageEntry} /></dd><dt>Valuation price</dt><dd><Value value={position.valuationPrice} /></dd><dt>Realized PnL · gross</dt><dd><Value value={position.realizedPnl} unit={snapshot.account.data?.currency} /></dd><dt>Unrealized PnL</dt><dd><Value value={position.unrealizedPnl} unit={snapshot.account.data?.currency} />{position.unrealizedPnlStatus && <small>{position.unrealizedPnlStatus}</small>}</dd><dt>Opened UTC</dt><dd>{position.openedAt}</dd><dt>Valuation UTC</dt><dd>{position.valuationAt ?? "Unavailable"}</dd></dl>{position.status !== "CLOSED" && <><p className="product-note">Available actions are supplied by the adapter. Each action obtains confirmed lifecycle data; the browser does not calculate a fill.</p><div className="product-actions"><button disabled={busy || !apis.execution.positionAction || !position.availableActions.includes("SCALE_IN") || !snapshot.account.data?.capabilities.supportsScaleIn} onClick={() => void action(position, "SCALE_IN")}>Add Position / Scale In</button><button disabled={busy || !apis.execution.positionAction || !position.availableActions.includes("PARTIAL_CLOSE") || !snapshot.account.data?.capabilities.supportsPartialClose} onClick={() => void action(position, "PARTIAL_CLOSE")}>Partial Close</button><button disabled={busy || !apis.execution.positionAction || !position.availableActions.includes("CLOSE")} onClick={() => void action(position, "CLOSE")}>Close</button></div></>}<div className="product-actions"><Link className="product-link-button" href={`/journal/${position.tradeId}`}>Review trade & fills</Link></div></article>)}</div>}<ResponseMessage response={response} /></ResourceGate></ProductPage>;
}
