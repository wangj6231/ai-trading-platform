"use client";

import { useState, type ReactNode } from "react";
import type { Resource, StrategyPlan, PageQuery } from "@/lib/product/contracts";
import { FixtureControls } from "./fixture-controls";
import { useProduct } from "./product-provider";

export function Value({ value, unit }: { value: string | null; unit?: string }) { return <>{value === null ? "Unavailable" : `${value}${unit ? ` ${unit}` : ""}`}</>; }
export function StatusBadge({ value }: { value: string }) { return <span className={`product-status status-${value.toLowerCase()}`}>{value.replaceAll("_", " ")}</span>; }
export function Metric({ label, value, unit }: { label: string; value: string | null; unit?: string }) { return <div className="product-metric"><span>{label}</span><strong><Value value={value} unit={unit} /></strong></div>; }
export function ProductPage({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  const { snapshot } = useProduct();
  return <main className="product-page"><div className="product-page-heading"><div><span className="section-kicker">{snapshot.environmentLabel}</span><h1>{title}</h1><p>{subtitle}</p></div><span className="product-fixture-badge">{snapshot.source}</span></div><FixtureControls />{children}<footer className="product-note">{snapshot.notice}</footer></main>;
}
export function ResourceGate({ resource, empty, children }: { resource: Resource<unknown>; empty?: string; children: ReactNode }) {
  if (resource.status === "READY" && resource.data !== null) return children;
  const title = resource.status === "LOADING" ? "Loading this resource…" : resource.status === "EMPTY" ? empty ?? "No records yet." : resource.status === "ERROR" ? "Unable to load this module" : resource.status === "NOT_READY" ? "NOT_READY" : "Backend adapter unavailable";
  return <section className="product-state" role={resource.status === "ERROR" ? "alert" : "status"}><StatusBadge value={resource.error?.code ?? resource.status} /><h2>{title}</h2><p>{resource.message ?? "The adapter has not supplied usable records for this state."}</p></section>;
}
export function AccountSummary() {
  const { snapshot } = useProduct(); const account = snapshot.account.data;
  if (snapshot.account.status !== "READY" || !account) return <ResourceGate resource={snapshot.account}><section className="product-state">Account unavailable</section></ResourceGate>;
  return <section className="product-card" aria-label="Account summary"><div className="product-card-heading"><div><h2>{account.name ?? account.accountId}</h2><p>{account.accountId} · {account.accountingProfile}</p></div><StatusBadge value={account.status} /></div><div className="account-context"><span>Environment <b>{account.environment}</b></span><span>Execution provider <b>{account.executionProvider}</b></span><span>{account.positionModel}</span></div><div className="product-metrics"><Metric label="Balance" value={account.balance} unit={account.currency} />{account.reservedCollateral !== undefined && <Metric label="Reserved collateral" value={account.reservedCollateral} unit={account.currency} />}{account.availableBalance !== undefined && <Metric label="Available balance" value={account.availableBalance} unit={account.currency} />}<Metric label="Equity" value={account.equity} unit={account.currency} /><Metric label="Realized PnL · gross" value={account.realizedPnl} unit={account.currency} /><Metric label="Unrealized PnL" value={account.unrealizedPnl} unit={account.currency} /></div><p className="product-note">Valuation: {account.valuationAt ?? "Unavailable"} · Market data and execution providers are independent.</p>{account.valuationStatus && <StatusBadge value={account.valuationStatus} />}{account.valuations?.map(item => <p key={item.symbol}>{item.symbol}: <Value value={item.price} /> · {item.valuationAt}</p>)}</section>;
}
export function StrategyPlanCard({ plan, historical = false }: { plan: StrategyPlan | null; historical?: boolean }) {
  return <section className="product-card strategy-plan" aria-label="Strategy plan"><span className="section-kicker">STRATEGY PLAN · RECOMMENDATION</span>{plan ? <><div className="product-card-heading"><h2>{plan.symbol} · {plan.direction}</h2><span className="product-fixture-badge">{plan.source}</span></div><div className="product-metrics"><Metric label="Planned entry minimum" value={plan.entryMin} /><Metric label="Planned entry maximum" value={plan.entryMax} /><Metric label="Planned TP" value={plan.takeProfit} /><Metric label="Planned SL" value={plan.stopLoss} /></div><p>{plan.strategyName ?? "Name unavailable"} · {plan.strategyVersion ?? "Version unavailable"}</p><p>Signal: closed {plan.signalTimeframe} · {plan.cutoff}</p><details><summary>Strategy attribution</summary><dl className="product-facts"><dt>Config identity</dt><dd>{plan.configIdentity ?? "Unavailable"}</dd><dt>Evaluation reference</dt><dd>{plan.evaluationReference ?? "Unavailable"}</dd><dt>Planned RR</dt><dd>{plan.riskReward ?? "Unavailable"}</dd></dl></details></> : <><h2>No verified strategy attribution</h2><p>{historical ? "The backend has not provided verified strategy attribution for this trade." : "Open Paper Trade from a current Dashboard signal, or select a labeled fixture scenario."}</p></>}<p className="product-note">Planned entry and strategy direction are recommendations. They do not establish actual fills or executed direction.</p></section>;
}

export function PageScope({ page }: { page: { items: unknown[]; hasMore: boolean; asOf: string } | null }) {
  return page ? <p className="product-note">Loaded page: {page.items.length} records · as of {page.asOf}{page.hasMore ? " · More pages available. This is not complete account history." : " · End of this result set."} Filters below apply to the loaded page only.</p> : null;
}

export function PageControls({ page, onLoad, query = {}, label = "records" }: { page: { nextCursor: string | null; hasMore: boolean; asOf: string } | null; onLoad?: (query: PageQuery) => Promise<unknown>; query?: PageQuery; label?: string }) {
  const [busy, setBusy] = useState(false); const [message, setMessage] = useState("");
  async function load(next: boolean) { if (!onLoad || busy) return; setBusy(true); setMessage(""); try { await onLoad(next && page?.nextCursor ? { ...query, cursor: page.nextCursor, asOf: page.asOf } : query); } catch { setMessage("Page request failed. No replacement or fixture fallback was used."); } finally { setBusy(false); } }
  return onLoad ? <div className="product-actions"><button disabled={busy} onClick={() => void load(false)}>Refresh {label}</button>{page?.hasMore && <button disabled={busy} onClick={() => void load(true)}>Next {label} page</button>}{message && <p role="alert">{message}</p>}</div> : null;
}
