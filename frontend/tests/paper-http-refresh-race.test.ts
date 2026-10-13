import { expect, it } from "vitest";
import recorded from "@/lib/product/recorded-contract.fixture.json";
import { createHttpProduct } from "@/lib/product/http-adapter";

function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
const json = (body: unknown) => new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });
const accountId = recorded.account.account_id;
const ack = { ...recorded.order, status: "ACKNOWLEDGED", submission_status: "ACKNOWLEDGED", filled_quantity: "0" };
const page = (items: unknown[]) => ({ items, next_cursor: null, has_more: false, as_of: "2026-10-08T00:08:00Z" });
function resources(path: string) { return json(path === "/analytics" ? recorded.analytics : page(path === "/orders" ? [ack] : [])); }

it("command completion owns its account refresh instead of leaving a stale read racing the next action", async () => {
  const started = deferred<void>(), accountRead = deferred<Response>(); let commandPhase = false, completed = false;
  const fetcher: typeof fetch = async (input, init) => {
    const path = String(input).replace(`/api/paper/accounts/${accountId}`, "");
    if (path === "") { if (commandPhase) { started.resolve(); return accountRead.promise; } return json({ ...recorded.account, cash_balance: "10000" }); }
    if (path === "/orders" && init?.method === "POST") return json(ack);
    if (path === "/orders") return json(page([ack]));
    if (path === "/analytics") return json(recorded.analytics);
    return json(page([]));
  };
  const { store, apis } = createHttpProduct(accountId, fetcher); await store.initialize();
  commandPhase = true;
  const command = apis.execution.submit({ accountId, commandId: "refresh-owner", symbol: "BTCUSDT", side: "BUY", type: "MARKET", quantity: "1", limitPrice: null });
  void command.then(() => { completed = true; });
  await started.promise; await Promise.resolve();
  try { expect(completed).toBe(false); }
  finally { accountRead.resolve(json({ ...recorded.account, cash_balance: "10000" })); }
  expect((await command).kind).toBe("ORDER");
  expect(store.getSnapshot().account.data?.balance).toBe("10000");
});

it("an unrelated order read cannot cancel or supersede the pending account read", async () => {
  const started = deferred<void>(), accountRead = deferred<Response>(); let held = false;
  const signals: (AbortSignal | null | undefined)[] = [];
  const fetcher: typeof fetch = async (input, init) => {
    const path = String(input).replace(`/api/paper/accounts/${accountId}`, "");
    if (held) signals.push(init?.signal);
    if (path === "") { if (held) { started.resolve(); return accountRead.promise; } return json(recorded.account); }
    return resources(path);
  };
  const { store, apis } = createHttpProduct(accountId, fetcher); await store.initialize(); held = true;
  const account = apis.account.getAccount(); await started.promise;
  await apis.execution.getOrders();
  expect(signals[0]).not.toBe(signals[1]); expect(signals.every(signal => signal && !signal.aborted)).toBe(true);
  accountRead.resolve(json({ ...recorded.account, cash_balance: "9999.9" })); await account;
  expect(store.getSnapshot().account.data?.balance).toBe("9999.9");
});

it("an older same-account reply is discarded without discarding the newer account reply", async () => {
  const started = deferred<void>(), oldRead = deferred<Response>(); let accountRequests = 0;
  const fetcher: typeof fetch = async input => {
    const path = String(input).replace(`/api/paper/accounts/${accountId}`, "");
    if (path === "") { if (++accountRequests === 2) { started.resolve(); return oldRead.promise; } return json({ ...recorded.account, cash_balance: "9999.9" }); }
    return resources(path);
  };
  const { store, apis } = createHttpProduct(accountId, fetcher); await store.initialize();
  const old = apis.account.getAccount(); await started.promise; await apis.account.getAccount();
  oldRead.resolve(json({ ...recorded.account, cash_balance: "10000" }));
  await expect(old).rejects.toMatchObject({ code: "REQUEST_CANCELLED" });
  expect(store.getSnapshot().account.data?.balance).toBe("9999.9");
});

it("disposing the account session rejects its late reply and does not republish financial state", async () => {
  const started = deferred<void>(), lateRead = deferred<Response>(); let held = false;
  const fetcher: typeof fetch = async input => {
    const path = String(input).replace(`/api/paper/accounts/${accountId}`, "");
    if (path === "") { if (held) { started.resolve(); return lateRead.promise; } return json(recorded.account); }
    return resources(path);
  };
  const { store, apis } = createHttpProduct(accountId, fetcher); await store.initialize(); held = true;
  const late = apis.account.getAccount(); await started.promise; store.dispose();
  lateRead.resolve(json({ ...recorded.account, cash_balance: "9999.9" }));
  await expect(late).rejects.toMatchObject({ code: "REQUEST_CANCELLED" });
  expect(store.getSnapshot().account.data).toBeNull();
});

it("a failed account reread is explicit unavailability, not a fabricated rejection of the accepted order", async () => {
  let unavailable = false;
  const fetcher: typeof fetch = async (input, init) => {
    const path = String(input).replace(`/api/paper/accounts/${accountId}`, "");
    if (path === "") return unavailable ? new Response(JSON.stringify({ error: { code: "BACKEND_UNAVAILABLE" } }), { status: 503 }) : json(recorded.account);
    if (path === "/orders" && init?.method === "POST") return json(ack);
    return resources(path);
  };
  const { store, apis } = createHttpProduct(accountId, fetcher); await store.initialize(); unavailable = true;
  const result = await apis.execution.submit({ accountId, commandId: "accepted-unavailable-read", symbol: "BTCUSDT", side: "BUY", type: "MARKET", quantity: "1", limitPrice: null });
  expect(result).toMatchObject({ kind: "ORDER", order: { status: "ACKNOWLEDGED", filledQuantity: "0" } });
  expect(store.getSnapshot().account).toMatchObject({ status: "UNAVAILABLE", data: null });
});

it("a fill arriving during the read cohort cannot leave a newer FILLED order paired with a pre-fill account", async () => {
  const started = deferred<void>(), ordersRead = deferred<Response>(); let commandPhase = false, filled = false;
  const fetcher: typeof fetch = async (input, init) => {
    const path = String(input).replace(`/api/paper/accounts/${accountId}`, "");
    if (path === "") return json({ ...recorded.account, cash_balance: filled ? "9999.9" : "10000" });
    if (path === "/orders" && init?.method === "POST") return json(ack);
    if (path === "/orders") { if (commandPhase) { started.resolve(); return ordersRead.promise; } return json(page([ack])); }
    if (path === "/analytics") return json(recorded.analytics);
    return json(page([]));
  };
  const { store, apis } = createHttpProduct(accountId, fetcher); await store.initialize();
  commandPhase = true;
  const command = apis.execution.submit({ accountId, commandId: "fill-in-cohort", symbol: "BTCUSDT", side: "BUY", type: "MARKET", quantity: "1", limitPrice: null });
  await started.promise; filled = true;
  ordersRead.resolve(json(page([{ ...ack, status: "FILLED", filled_quantity: "1" }])));
  expect((await command).kind).toBe("ORDER");
  expect(store.getSnapshot().orders.data?.items[0].status).toBe("FILLED");
  expect(store.getSnapshot().account.data?.balance).toBe("9999.9");
});
