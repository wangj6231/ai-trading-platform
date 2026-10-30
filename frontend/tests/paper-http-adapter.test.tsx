import { act, render, screen, waitFor, fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import recorded from "@/lib/product/recorded-contract.fixture.json";
import { createHttpProduct, unavailableHttpProduct } from "@/lib/product/http-adapter";
import { PaperHttpError } from "@/lib/product/http-errors";
import { ProductProvider, useProduct } from "@/components/product/product-provider";
import { PaperTradingPage } from "@/components/product/execution-pages";
import { TradeDetailPage } from "@/components/product/journal-pages";
import type { OrderIntent } from "@/lib/product/contracts";

afterEach(() => vi.unstubAllGlobals());
const accountId = recorded.account.account_id;
const tradeId = recorded.trade.trade_id;
const page = (items: unknown[], cursor: string | null = null) => ({ items, next_cursor: cursor, has_more: !!cursor, as_of: "2026-10-08T00:08:00Z" });
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
function transport(override?: (path: string, init?: RequestInit) => Promise<Response> | Response | undefined) {
  return vi.fn<typeof fetch>(async (input, init) => {
    const path = String(input).replace(`/api/paper/accounts/${accountId}`, ""); const custom = override?.(path, init); if (custom) return custom;
    if (path === "") return json(recorded.account);
    if (path.startsWith("/analytics")) return json(recorded.analytics);
    if (path.startsWith(`/trades/${tradeId}/attachments`)) return json(page(recorded.attachments.items));
    if (path.startsWith(`/trades/${tradeId}/fills`)) return json(page(recorded.trade.fills));
    if (path === `/trades/${tradeId}`) return json(recorded.trade);
    if (path.startsWith("/orders")) return json(page([recorded.order]));
    if (path.startsWith("/positions")) return json(page([]));
    return json(page([recorded.trade]));
  });
}
const intent: OrderIntent = { accountId, commandId: "retry-one", symbol: "BTCUSDT", side: "BUY", type: "MARKET", quantity: "1", limitPrice: null };
function SnapshotProbe() { const { snapshot } = useProduct(); return <pre data-testid="snapshot">{JSON.stringify(snapshot)}</pre>; }

describe("authenticated HTTP product transport without fixture financial state", () => {
  it("refreshing a filled HTTP order also refreshes the canonical account balance", async () => {
    let filled = false;
    const fetcher = transport(path => path === "" ? json({ ...recorded.account, cash_balance: filled ? "9999.9" : "10000" }) : path === `/orders/${recorded.order.order_id}` ? json({ ...recorded.order, status: "FILLED", filled_quantity: "1" }) : undefined);
    const { store, apis } = createHttpProduct(accountId, fetcher);
    await store.initialize(); expect(store.getSnapshot().account.data?.balance).toBe("10000");
    filled = true;
    expect((await apis.execution.refreshOrder(recorded.order.order_id)).kind).toBe("ORDER");
    await waitFor(() => expect(store.getSnapshot().account.data?.balance).toBe("9999.9"));
  });
  it("default browser fetch is invoked without an adapter receiver", async () => {
    const base = transport(); vi.stubGlobal("fetch", function(this: unknown, input: Parameters<typeof fetch>[0], init?: RequestInit) { expect(this === undefined || this === globalThis).toBe(true); return base(input, init); });
    const { store } = createHttpProduct(accountId); await store.initialize(); expect(store.getSnapshot().account.data?.accountId).toBe(accountId);
  });
  it("loads independent actual DTO resources, never embeds credentials or fixture values", async () => {
    const fetcher = transport(); const { store } = createHttpProduct(accountId, fetcher); await store.initialize();
    expect(store.getSnapshot().account.data?.name).toBeNull(); expect(store.getSnapshot().account.data?.realizedPnl).toBe("6");
    expect(store.getSnapshot().journal.data?.items[0].fills).toHaveLength(4); expect(store.getSnapshot().analytics.data?.includedTradeIds).toBeNull();
    expect(store.getSnapshot().fixtureOnly).toBeUndefined(); expect(JSON.stringify(store.getSnapshot())).not.toContain("dev-paper-01");
    for (const [, init] of fetcher.mock.calls) { expect(init?.credentials).toBe("omit"); expect(new Headers(init?.headers).has("Authorization")).toBe(false); }
  });
  it("MARKET/LIMIT bodies preserve command identity and never send ownership or a strategy plan", async () => {
    const bodies: unknown[] = []; const fetcher = transport((path, init) => { if (path === "/orders" && init?.method === "POST") { bodies.push(JSON.parse(String(init.body))); return json({ ...recorded.order, command_id: JSON.parse(String(init.body)).command_id }); } });
    const { apis } = createHttpProduct(accountId, fetcher);
    await apis.execution.submit(intent); await apis.execution.submit(intent); await apis.execution.submit({ ...intent, commandId: "new-intent", type: "LIMIT", limitPrice: "99" });
    expect(bodies[0]).toEqual(bodies[1]); expect(bodies[0]).toEqual({ command_id: "retry-one", symbol: "BTCUSDT", side: "BUY", order_type: "MARKET", quantity: "1", limit_price: null });
    expect(bodies[2]).toMatchObject({ command_id: "new-intent", order_type: "LIMIT", limit_price: "99" });
  });
  it("network retry keeps the same command in the actual ticket; new successful submission gets a new identity", async () => {
    const bodies: { command_id: string }[] = []; const fetcher = transport((path, init) => { if (path === "/orders" && init?.method === "POST") { const body = JSON.parse(String(init.body)); bodies.push(body); if (bodies.length === 1) return Promise.reject(new Error("private failure secret")); return json({ ...recorded.order, command_id: body.command_id, status: "ACKNOWLEDGED", submission_status: "ACKNOWLEDGED", filled_quantity: "0" }); } });
    const runtime = createHttpProduct(accountId, fetcher); render(<ProductProvider runtime={runtime}><PaperTradingPage /></ProductProvider>);
    await screen.findByLabelText("Quantity"); fireEvent.change(screen.getByLabelText("Quantity"), { target: { value: "1" } }); fireEvent.click(screen.getByRole("button", { name: "Submit paper intent" }));
    await screen.findByText(/No fixture fallback/); await waitFor(() => expect(screen.getByRole("button", { name: "Submit paper intent" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Submit paper intent" })); await waitFor(() => expect(bodies).toHaveLength(2));
    await screen.findByRole("button", { name: "Submit paper intent" }); fireEvent.change(screen.getByLabelText("Quantity"), { target: { value: "1" } }); fireEvent.click(screen.getByRole("button", { name: "Submit paper intent" })); await waitFor(() => expect(bodies).toHaveLength(3));
    expect(bodies[0].command_id).toBe(bodies[1].command_id); expect(bodies[2].command_id).not.toBe(bodies[1].command_id);
    expect(screen.queryByText("private failure secret")).not.toBeInTheDocument();
  });
  it.each(["ACKNOWLEDGED", "UNKNOWN", "REJECTED"] as const)("%s remains a backend outcome and never a fabricated fill", async status => {
    const fetcher = transport((path, init) => path === "/orders" && init?.method === "POST" ? json({ ...recorded.order, status, submission_status: status, filled_quantity: "0", error_code: status === "UNKNOWN" ? "EXECUTION_UNKNOWN" : status === "REJECTED" ? "INSUFFICIENT_BALANCE" : null }) : undefined);
    const { apis } = createHttpProduct(accountId, fetcher); const result = await apis.execution.submit(intent); expect(result.kind).toBe("ORDER"); if (result.kind === "ORDER") { expect(result.order.status).toBe(status); expect(result.order.filledQuantity).toBe("0"); }
  });
  it.each([401, 403])("%i clears every protected resource and discards racing late responses", async status => {
    let resolveLate!: (response: Response) => void; let fail = false;
    const fetcher = transport((path) => fail && path === "/analytics" ? new Promise<Response>(resolve => { resolveLate = resolve; }) : fail && path === "/orders" ? json({ error: { code: "UNSAFE", message: "secret" } }, status) : undefined);
    const { store, apis } = createHttpProduct(accountId, fetcher); await store.initialize(); await apis.journal.getTrade(tradeId); await apis.journal.getAttachments(tradeId);
    fail = true; const late = apis.analytics.getAnalytics(); await expect(apis.execution.getOrders()).rejects.toBeInstanceOf(PaperHttpError); resolveLate(json(recorded.analytics)); await expect(late).rejects.toBeInstanceOf(PaperHttpError);
    const snapshot = store.getSnapshot(); expect(snapshot.account.data).toBeNull(); expect(snapshot.analytics.data).toBeNull(); expect(snapshot.tradeDetails[tradeId].data).toBeNull(); expect(snapshot.attachments[tradeId].data).toBeNull(); expect(snapshot.account.error?.code).toBe(status === 401 ? "AUTH_REQUIRED" : "FORBIDDEN");
    expect(JSON.stringify(snapshot)).not.toContain("secret");
  });
  it.each([404, 409, 422, 500, 503])("typed safe %i failure affects the resource without fallback", async status => {
    const { apis, store } = createHttpProduct(accountId, transport(path => path === "/orders" ? json({ error: { message: "raw exception TOKEN" } }, status) : undefined)); await store.initialize();
    expect(store.getSnapshot().orders.data).toBeNull(); expect(store.getSnapshot().account.data?.accountId).toBe(accountId); expect(JSON.stringify(store.getSnapshot())).not.toContain("TOKEN"); await expect(apis.execution.getOrders()).rejects.toBeInstanceOf(PaperHttpError);
  });
  it("opaque cursor, frozen cutoff and filters travel unchanged; pages are not mistaken for all history", async () => {
    const cursor = "opaque.DO_NOT_DECODE/+=="; const fetcher = transport(path => path.startsWith("/journal") ? json(page([recorded.trade], path.includes("cursor=") ? null : cursor)) : undefined);
    const { apis } = createHttpProduct(accountId, fetcher); const first = await apis.journal.getJournal({ limit: 1, tag: "review" }); const next = await apis.journal.getJournal({ limit: 1, tag: "review", cursor: first.nextCursor!, asOf: first.asOf }); expect(next.hasMore).toBe(false);
    const url = new URL(String(fetcher.mock.calls.at(-1)?.[0]), "http://local"); expect(url.searchParams.get("cursor")).toBe(cursor); expect(url.searchParams.get("as_of")).toBe(first.asOf); expect(url.searchParams.get("tag")).toBe("review");
  });
  it("detail/complete fills and attachment metadata load separately without deriving delivery URLs", async () => {
    const { apis, store } = createHttpProduct(accountId, transport()); await apis.journal.getTrade(tradeId); await apis.journal.getFills!(tradeId, { limit: 1 }); await apis.journal.getAttachments(tradeId);
    expect(store.getSnapshot().tradeDetails[tradeId].data?.fills).toHaveLength(4); expect(store.getSnapshot().fills[tradeId].data?.items[0].price).toBe("100"); expect(store.getSnapshot().attachments[tradeId].data?.items.every(item => item.url === null)).toBe(true);
  });
  it("metadata conflict fetches latest while preserving draft; explicit reload permits a reviewed retry", async () => {
    let newer = false; const annotations = { notes: "server newer", tags: ["latest"], version: 2, created_at: "2026-10-08T00:08:00Z", updated_at: "2026-10-08T00:09:00Z" };
    const fetcher = transport((path, init) => { if (path.endsWith("/metadata")) { expect(JSON.parse(String(init?.body)).expected_version).toBe(0); newer = true; return json({ error: { code: "CONFLICT" } }, 409); } if (newer && path === `/trades/${tradeId}`) return json({ ...recorded.trade, annotations }); });
    render(<ProductProvider runtime={createHttpProduct(accountId, fetcher)}><TradeDetailPage tradeId={tradeId} /></ProductProvider>);
    await screen.findByLabelText("Notes", { exact: true }); fireEvent.change(screen.getByLabelText("Notes", { exact: true }), { target: { value: "my unsaved draft" } }); fireEvent.click(screen.getByRole("button", { name: "Save notes & tags" }));
    await screen.findByRole("button", { name: "Reload latest metadata" }); expect(screen.getByLabelText("Notes", { exact: true })).toHaveValue("my unsaved draft"); expect(screen.getByRole("button", { name: "Save notes & tags" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Reload latest metadata" })); await waitFor(() => expect(screen.getByLabelText("Notes", { exact: true })).toHaveValue("server newer")); expect(screen.getByRole("button", { name: "Save notes & tags" })).toBeEnabled();
  });
  it("HTTP failure never selects fixture; runtime/account switch immediately removes old financial records", async () => {
    vi.stubGlobal("fetch", transport()); const view = render(<ProductProvider selection={{ mode: "HTTP", accountId }}><SnapshotProbe /></ProductProvider>); await waitFor(() => expect(screen.getByTestId("snapshot")).toHaveTextContent('"balance":"10005.39"'));
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("secret")))); await act(async () => view.rerender(<ProductProvider selection={{ mode: "HTTP", accountId: "another-account" }}><SnapshotProbe /></ProductProvider>));
    await waitFor(() => expect(screen.getByTestId("snapshot")).toHaveTextContent("UNAVAILABLE")); expect(screen.getByTestId("snapshot")).not.toHaveTextContent("10005.39"); expect(screen.getByTestId("snapshot")).not.toHaveTextContent("dev-paper");
  });
  it("disposed requests cannot repopulate resources; development effect remount can initialize afresh", async () => {
    const runtime = createHttpProduct(accountId, transport()); await runtime.store.initialize(); runtime.store.dispose(); expect(runtime.store.getSnapshot().account.data).toBeNull(); await runtime.store.initialize(); expect(runtime.store.getSnapshot().account.data?.accountId).toBe(accountId);
  });
  it("missing bootstrap detail shows UNAVAILABLE without any network or fixture data", async () => {
    const runtime = unavailableHttpProduct("BOOTSTRAP_REQUIRED"); render(<ProductProvider runtime={runtime}><TradeDetailPage tradeId="not-provisioned" /></ProductProvider>);
    await waitFor(() => expect(runtime.store.getSnapshot().tradeDetails["not-provisioned"]?.status).toBe("UNAVAILABLE")); expect(runtime.store.getSnapshot().account.data).toBeNull(); await screen.findByText("BOOTSTRAP REQUIRED");
  });
});
