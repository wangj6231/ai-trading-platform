import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import recorded from "@/lib/product/recorded-contract.fixture.json";
import { accountSchema, analyticsSchema, attachmentSchema, orderSchema, normalizeProductSnapshot, ready, type OrderIntent, type MetadataPatch } from "@/lib/product/contracts";
import { normalizeHttpAccount, normalizeHttpAnalytics, normalizeHttpAttachment, normalizeHttpFill, normalizeHttpOrder, normalizeHttpPage, normalizeHttpPosition, normalizeHttpTrade, httpOrderBody, httpMetadataBody } from "@/lib/product/http-contract";
import { ProductResourceStore } from "@/lib/product/resource-store";
import { createFixtureProduct } from "@/lib/product/fixture-adapters";
import { fixturePage, fixtureTime, baseSnapshot } from "@/lib/product/fixtures";
import { ProductProvider, type ProductRuntime } from "@/components/product/product-provider";
import { AccountSummary } from "@/components/product/product-ui";
import { AnalyticsPage } from "@/components/product/analytics-page";
import { PaperTradingPage, OrdersPage } from "@/components/product/execution-pages";
import { TradeDetail, AttachmentView } from "@/components/product/journal-pages";

const trade = () => normalizeHttpTrade(recorded.trade);
const account = () => normalizeHttpAccount(recorded.account);
function resourceRuntime() {
  const store = new ProductResourceStore(recorded.account.account_id, { source: "RECORDED / FIXTURE_ONLY", environmentLabel: "PAPER / TEST", notice: "TestClient evidence; no deployed HTTP runtime." });
  const apis = createFixtureProduct(0).apis;
  return { store, apis } satisfies ProductRuntime;
}
const intent: OrderIntent = { commandId: "stable-command-01", accountId: "dev-paper-01", symbol: "BTCUSDT", side: "BUY", type: "MARKET", quantity: "0.1", limitPrice: null };

describe("PAPER_HTTP_API_V1 reconciliation without runtime activation", () => {
  it("accepts absent account display name and preserves gross realized / cash balance / null scalar valuation", () => {
    const result = account(); expect(result.name).toBeNull(); expect(accountSchema.parse({ ...result, name: undefined }).name).toBeUndefined();
    expect(result.balance).toBe(recorded.account.cash_balance); expect(result.realizedPnl).toBe("6"); expect(result.valuationAt).toBeNull();
    expect(result.availableBalance).toBe(recorded.account.available_balance); expect(result.numericPolicyVersion).toBe("PAPER_DECIMAL_V1");
  });
  it("preserves plural symbol valuations and a null equity without choosing one aggregate scalar", () => {
    const result = normalizeHttpAccount({ ...recorded.account, equity: null, unrealized_pnl: null, valuation_status: "NOT_READY", valuations: [{ symbol: "BTCUSDT", valuation_price: "100.01234567890123456789", valuation_at: fixtureTime, received_at: fixtureTime }] });
    expect(result.equity).toBeNull(); expect(result.valuationAt).toBeNull(); expect(result.valuations?.[0].price).toBe("100.01234567890123456789");
  });
  it("Trade does not require live Position facts; null attribution, annotations, positionId and R remain null", () => {
    const result = trade(); expect(result.positionId).toBeNull(); expect(result.plan).toBeNull(); expect(result.rMultiple).toBeNull(); expect(result.setup).toBeNull();
    expect(result.notes).toBeNull(); expect(result.tags).toBeNull(); expect(result.metadataVersion).toBe(0);
    expect(result).not.toHaveProperty("valuationPrice"); expect(result).not.toHaveProperty("unrealizedPnl"); expect(result).not.toHaveProperty("availableActions");
    expect(result.grossPnl).toBe("6"); expect(result.netPnl).toBe("5.39"); expect(result.averageEntry).toBe(recorded.trade.average_entry_price); expect(result.fills).toHaveLength(4);
  });
  it("Position keeps null per-position PnL independently of symbol valuation and supplied actions", () => {
    const result = normalizeHttpPosition({ position_id: "server-position", trade_id: recorded.trade.trade_id, account_id: recorded.account.account_id, symbol: "BTCUSDT", direction: "LONG", status: "OPEN", total_quantity: "3", remaining_quantity: "2", average_entry_price: "101", valuation_price: null, valuation_at: null, valuation_status: "NOT_READY", realized_pnl: "1", unrealized_pnl: null, unrealized_status: "NOT_READY_NO_POSITION_PROJECTION", opened_at: fixtureTime, closed_at: null, allowed_actions: ["CLOSE"] });
    expect(result.unrealizedPnl).toBeNull(); expect(result.valuationPrice).toBeNull(); expect(result.unrealizedPnlStatus).toBe("NOT_READY_NO_POSITION_PROJECTION"); expect(result.availableActions).toEqual(["CLOSE"]);
  });
  it("preserves received-time/source/provenance and every confirmed fill's exact decimal text", () => {
    const result = normalizeHttpFill(recorded.trade.fills[1]); expect(result.price).toBe("101"); expect(result.tradeId).toBe(recorded.trade.trade_id); expect(result.provenance).toEqual(recorded.trade.fills[1].provenance);
  });
  it("SUBMITTING is rejected as a canonical server order state; cancel outcome is separate", () => {
    const result = normalizeHttpOrder({ ...recorded.order, cancellation_status: "UNKNOWN", status: "ACKNOWLEDGED" });
    expect(result.submissionStatus).toBe("ACKNOWLEDGED"); expect(result.cancellationStatus).toBe("UNKNOWN");
    expect(orderSchema.safeParse({ ...result, status: "SUBMITTING" }).success).toBe(false);
  });
  it("stable command identity is serialized; ownership and frontend recommendation are never sent", () => {
    const body = httpOrderBody(intent); expect(body.command_id).toBe(intent.commandId); expect(body).not.toHaveProperty("accountId"); expect(body).not.toHaveProperty("plan"); expect(httpOrderBody(intent)).toEqual(body);
  });
  it("fixture duplicate retries reuse the same order; changed intent under the command conflicts", async () => {
    const { store, apis } = createFixtureProduct(0); await store.initialize(); const first = await apis.execution.submit(intent); const repeat = await apis.execution.submit(intent);
    expect(repeat).toEqual(first); expect(store.getSnapshot().orders.data?.items).toHaveLength(1);
    const conflict = await apis.execution.submit({ ...intent, quantity: "0.2" }); expect(conflict.kind === "ERROR" && conflict.code).toBe("CONFLICT");
  });
  it("metadata expected version follows actual body contract; setup is unsupported", () => {
    expect(httpMetadataBody({ notes: "Review", tags: ["entry"], expectedVersion: 3 })).toEqual({ notes: "Review", tags: ["entry"], expected_version: 3 });
    expect(() => httpMetadataBody({ notes: "", tags: [], expectedVersion: 0, setup: "fake" })).toThrow("NOT_READY");
  });
  it("fixture optimistic concurrency never overwrites a newer annotation", async () => {
    const { store, apis } = createFixtureProduct(0); store.scenario("K"); const id = trade().tradeId;
    expect((await apis.journal.saveMetadata(id, { notes: "new", tags: [], expectedVersion: 0 })).kind).toBe("SAVED");
    expect((await apis.journal.saveMetadata(id, { notes: "stale", tags: [], expectedVersion: 0 })).kind).toBe("CONFLICT"); expect((await apis.journal.getTrade(id))?.notes).toBe("new");
    expect((await apis.journal.saveMetadata(id, { notes: "bad", tags: [], expectedVersion: 1, setup: "not supported" })).kind).toBe("ERROR");
  });
  it.each(["PENDING", "FAILED", "READY"])("%s attachment can have no browser URL or provider provenance", status => {
    const result = normalizeHttpAttachment({ ...recorded.attachments.items[0], attachment: { ...recorded.attachments.items[0].attachment, status, type: "USER_UPLOAD", snapshot_at: null, provenance: null, storage_reference: status === "READY" ? "objects/private/snapshot.png" : null, mime_type: status === "READY" ? "image/png" : null, file_size: status === "READY" ? 123 : null } });
    expect(result.url).toBeNull(); expect(result.source).toBeNull(); expect(result.storageReference).toBe(status === "READY" ? "objects/private/snapshot.png" : null); expect(attachmentSchema.parse(result)).toEqual(result);
  });
  it("Analytics accepts absent verified membership, null R and unavailable strategy rows", () => {
    const result = normalizeHttpAnalytics(recorded.analytics, "FIXTURE_ONLY"); expect(result.includedTradeIds).toBeNull(); expect(result.metrics.averageR).toBeNull(); expect(result.breakdowns.some(row => row.dimension === "STRATEGY")).toBe(false);
    expect(result.strategyBreakdownStatus).toBe("NOT_READY_NO_VERIFIED_ATTRIBUTION"); expect(analyticsSchema.parse({ ...result, includedTradeIds: undefined }).includedTradeIds).toBeUndefined();
    expect(analyticsSchema.safeParse({ ...result, breakdowns: [{ dimension: "STRATEGY", label: "invented", metrics: result.metrics }] }).success).toBe(false);
  });
  it("grossLoss is positive magnitude, not the old negative fixture convention", () => {
    const input = { ...recorded.analytics, analytics: { ...recorded.analytics.analytics, overall: { ...recorded.analytics.analytics.overall, gross_loss: "0.30" } } };
    expect(normalizeHttpAnalytics(input, "FIXTURE_ONLY").metrics.grossLoss).toBe("0.30"); expect(() => normalizeHttpAnalytics({ ...input, analytics: { ...input.analytics, overall: { ...input.analytics.overall, gross_loss: "-0.30" } } }, "FIXTURE_ONLY")).toThrow(); expect(baseSnapshot("H").analytics.data?.metrics.grossLoss).toBe("0.30");
  });
  it("each resource retains its own opaque cursor/cutoff/loading state; Analytics may load before Account", () => {
    const { store } = resourceRuntime(); const page = normalizeHttpPage({ items: [recorded.order], has_more: true, next_cursor: "opaque-signed-cursor", as_of: fixtureTime }, normalizeHttpOrder);
    store.update({ orders: ready(page), analytics: ready(normalizeHttpAnalytics(recorded.analytics, "FIXTURE_ONLY")) }); const result = store.getSnapshot();
    expect(result.account.data).toBeNull(); expect(result.account.status).toBe("LOADING"); expect(result.journal.data).toBeNull(); expect(result.orders.data?.nextCursor).toBe("opaque-signed-cursor"); expect(result.analytics.status).toBe("READY");
    expect(() => normalizeProductSnapshot(result)).not.toThrow(); expect(() => normalizeHttpPage({ items: [], has_more: true, next_cursor: null, as_of: fixtureTime }, normalizeHttpOrder)).toThrow();
  });
  it("account isolation is enforced even before the Account resource is loaded", () => {
    const { store } = resourceRuntime(); expect(() => store.update({ orders: ready(fixturePage([{ ...normalizeHttpOrder(recorded.order), accountId: "other" }])) })).toThrow("Account isolation");
  });
});

describe("real nullable contract presentation", () => {
  it("unknown provider and absent account name render generically", () => {
    const runtime = resourceRuntime(); runtime.store.update({ account: ready({ ...account(), name: undefined, executionProvider: "UNKNOWN_PROVIDER" }) });
    render(<ProductProvider runtime={runtime}><AccountSummary /></ProductProvider>); expect(screen.getByRole("heading", { name: recorded.account.account_id })).toBeVisible(); expect(screen.getByText("UNKNOWN_PROVIDER")).toBeVisible();
  });
  it("null attribution/R/position data and no setup/upload capability render explicitly", () => {
    render(<TradeDetail trade={trade()} onSave={vi.fn()} attachments={ready(normalizeHttpPage(recorded.attachments, normalizeHttpAttachment))} />);
    expect(screen.getByText("No verified strategy attribution")).toBeVisible(); expect(screen.getByText(/Position reference unavailable/)).toBeVisible(); expect(screen.getByLabelText("Setup metadata")).toBeDisabled(); expect(screen.getByText("USER_UPLOAD · NOT_READY")).toBeVisible(); expect(screen.getByText(/No saved annotations/)).toBeVisible(); expect(screen.getByText("Fill history · 4 fills")).toBeVisible();
  });
  it("READY storage metadata does not create a fake image URL", () => {
    render(<AttachmentView attachment={{ attachmentId: "attachment", kind: "ENTRY_SNAPSHOT", status: "READY", url: null, source: null, message: null }} />);
    expect(screen.queryByRole("img")).not.toBeInTheDocument(); expect(screen.getByText(/Delivery URL NOT_READY/)).toBeVisible(); expect(screen.getByText("Source unavailable")).toBeVisible();
  });
  it("metadata conflict preserves draft, blocks overwrite and reloads a verified newer version", async () => {
    const onSave = vi.fn<(patch: MetadataPatch) => Promise<{ kind: "CONFLICT"; message: string } | { kind: "SAVED"; metadataVersion: number }>>().mockResolvedValueOnce({ kind: "CONFLICT", message: "changed" }).mockResolvedValue({ kind: "SAVED", metadataVersion: 3 });
    render(<TradeDetail trade={trade()} onSave={onSave} onReload={async () => ({ ...trade(), notes: "Newer server notes", tags: ["newer"], metadataVersion: 2 })} />);
    fireEvent.change(screen.getByLabelText("Notes"), { target: { value: "My draft" } }); fireEvent.click(screen.getByRole("button", { name: "Save notes & tags" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Metadata conflict"); expect(screen.getByLabelText("Notes")).toHaveValue("My draft"); expect(screen.getByRole("button", { name: "Save notes & tags" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Reload latest metadata" })); await waitFor(() => expect(screen.getByLabelText("Notes")).toHaveValue("Newer server notes")); fireEvent.click(screen.getByRole("button", { name: "Save notes & tags" }));
    await waitFor(() => expect(onSave).toHaveBeenLastCalledWith({ notes: "Newer server notes", tags: ["newer"], expectedVersion: 2 }));
  });
  it("network retry uses identical command/body; local SUBMITTING never creates an order", async () => {
    const runtime = resourceRuntime(); runtime.store.update({ account: ready(account()), orders: ready(fixturePage([])) });
    let reject: (error: Error) => void = () => { throw new Error("not initialized"); };
    const submit = vi.fn().mockImplementationOnce(() => new Promise((_resolve, rejectPromise) => { reject = rejectPromise; })).mockResolvedValue({ kind: "ERROR", message: "still unavailable" }); runtime.apis.execution.submit = submit;
    render(<ProductProvider runtime={runtime}><PaperTradingPage /></ProductProvider>); fireEvent.change(screen.getByLabelText("Quantity"), { target: { value: "0.1" } }); fireEvent.click(screen.getByRole("button", { name: "Submit paper intent" }));
    expect(screen.getByText("SUBMITTING")).toBeVisible(); expect(runtime.store.getSnapshot().orders.data?.items).toEqual([]);
    await act(async () => reject(new Error("Disconnected"))); fireEvent.click(screen.getByRole("button", { name: "Submit paper intent" })); await waitFor(() => expect(submit).toHaveBeenCalledTimes(2));
    expect(submit.mock.calls[0][0]).toEqual(submit.mock.calls[1][0]); expect(submit.mock.calls[0][0].commandId).toBeTruthy();
  });
  it("Orders render without Account loaded and show partial history scope", () => {
    const runtime = resourceRuntime(); runtime.store.update({ orders: ready({ ...fixturePage([normalizeHttpOrder(recorded.order)]), nextCursor: "opaque", hasMore: true }) });
    render(<ProductProvider runtime={runtime}><OrdersPage /></ProductProvider>); expect(screen.getByText(/This is not complete account history/)).toBeVisible(); expect(screen.getAllByText(recorded.order.order_id).length).toBeGreaterThan(0);
  });
  it("Analytics renders supplied stats independently of partial Journal and missing membership", () => {
    const runtime = resourceRuntime(); runtime.store.update({ analytics: ready(normalizeHttpAnalytics(recorded.analytics, "FIXTURE_ONLY")) });
    render(<ProductProvider runtime={runtime}><AnalyticsPage /></ProductProvider>); expect(screen.getByText(/No verified membership list/)).toBeVisible(); expect(screen.getByText(/Strategy analytics unavailable/)).toBeVisible(); expect(screen.getByText("Overall performance")).toBeVisible();
  });
});
