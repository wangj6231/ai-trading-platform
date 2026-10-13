import { test, expect, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { z } from "zod";
import { normalizeHttpAccount, normalizeHttpAnalytics, normalizeHttpAttachment, normalizeHttpOrder, normalizeHttpPage, normalizeHttpPosition, normalizeHttpTrade } from "../../src/lib/product/http-contract";
import { OwnedPaperStack } from "./owned-stack";

const eventSchema = z.object({ event_id: z.string(), price: z.string(), quantity: z.string(), filled_at: z.string(),
  provenance: z.object({ sequence: z.number().int(), execution_policy_version: z.literal("PAPER_CLOSED_1M_V1"), observation_hash: z.string().length(64) }) });

async function read(page: Page, accountId: string, path = "") {
  return page.evaluate(async ({ accountId, path }) => {
    const response = await fetch(`/api/paper/accounts/${accountId}${path}`);
    if (!response.ok) throw new Error(`Canonical read failed: ${response.status}`);
    const data: unknown = await response.json();
    if (/FIXTURE_ONLY|dev-paper-01|fixtureOnly|fixture-session/.test(JSON.stringify(data))) throw new Error("Fixture contamination in owned HTTP evidence");
    return data;
  }, { accountId, path });
}
async function openTicket(page: Page, accountId: string) {
  await page.goto("/paper-trading");
  await expect(page.getByLabel("Account summary")).toContainText(accountId);
  await expect(page.getByRole("button", { name: "Submit paper intent" })).toBeEnabled();
}
async function submit(page: Page, accountId: string, side: "BUY" | "SELL", quantity: string, limit?: string) {
  await page.getByLabel("Order side").selectOption(side);
  await page.getByLabel("Order type").selectOption(limit ? "LIMIT" : "MARKET");
  await page.getByLabel("Quantity", { exact: true }).fill(quantity);
  if (limit) await page.getByLabel("Limit price · intent only").fill(limit);
  const pending = page.waitForResponse(response => response.request().method() === "POST" && response.url().endsWith(`/accounts/${accountId}/orders`));
  await page.getByRole("button", { name: "Submit paper intent" }).click();
  const response = await pending; expect(response.status()).toBe(200);
  const order = normalizeHttpOrder(await response.json());
  expect(order.status).toBe("ACKNOWLEDGED"); expect(order.filledQuantity).toBe("0");
  await expect(page.getByRole("button", { name: "Submit paper intent" })).toBeEnabled();
  return order;
}
async function observe(stack: OwnedPaperStack, orderId: string, price: string, extra: Record<string, unknown> = {}) {
  const response = await stack.command("observe", { orderId, price, ...extra });
  return z.array(eventSchema).parse(response.events);
}
async function trade(page: Page, accountId: string) {
  const rows = normalizeHttpPage(await read(page, accountId, "/trades"), normalizeHttpTrade).items;
  expect(rows).toHaveLength(1); return rows[0];
}
async function metric(page: Page, label: string, value: string | null, scope = ".analytics-core") {
  const metric = page.locator(`${scope} .product-metric`).filter({ has: page.locator("span", { hasText: new RegExp(`^${label}$`) }) });
  await expect(metric.locator("strong")).toContainText(value ?? "Unavailable");
}
async function analytics(page: Page, accountId: string, count: number) {
  const canonical = normalizeHttpAnalytics(await read(page, accountId, "/analytics"), "HTTP / BACKEND");
  expect(canonical.metrics.totalTrades).toBe(count);
  expect(canonical.metrics.averageR).toBeNull(); expect(canonical.metrics.rObservations).toBe(0);
  expect(canonical.strategyBreakdownStatus).toBe("NOT_READY_NO_VERIFIED_ATTRIBUTION");
  expect(canonical.includedTradeIds).toBeNull();
  await page.goto("/analytics");
  await metric(page, "Total trades", String(canonical.metrics.totalTrades));
  await metric(page, "Net PnL", canonical.metrics.netPnl);
  await metric(page, "Win rate", canonical.metrics.winRate);
  await metric(page, "Profit factor", canonical.metrics.profitFactor);
  await metric(page, "Average R", null);
  for (const [label, value] of [["Wins", String(canonical.metrics.wins)], ["Losses", String(canonical.metrics.losses)], ["Breakeven", String(canonical.metrics.breakeven)], ["Gross profit", canonical.metrics.grossProfit], ["Gross loss · positive magnitude", canonical.metrics.grossLoss]] as const)
    await metric(page, label, value, ".product-page");
  return canonical;
}
async function renderTrade(page: Page, accountId: string) {
  const canonical = await trade(page, accountId);
  await page.goto(`/journal/${canonical.tradeId}`);
  const summary = page.getByLabel("Trade summary");
  await expect(summary).toContainText(`Actual ${canonical.side}`);
  for (const value of [canonical.averageEntry, canonical.averageExit, canonical.netPnl, canonical.pnlPercent, canonical.fees, canonical.result])
    if (value !== null && value !== undefined) await expect(summary).toContainText(value);
  await expect(page.getByText(`Fill history · ${canonical.fills.length} fills`)).toBeVisible();
  const attachments = normalizeHttpPage(await read(page, accountId, `/trades/${canonical.tradeId}/attachments`), normalizeHttpAttachment).items;
  expect(attachments.map(a => a.kind)).toEqual(expect.arrayContaining(["ENTRY_SNAPSHOT", "EXIT_SNAPSHOT"]));
  for (const attachment of attachments) { expect(attachment.url).toBeNull(); expect(["PENDING", "FAILED"]).toContain(attachment.status); }
  await expect(page.getByLabel("Trade charts")).toContainText("PENDING");
  await expect(page.getByLabel("Trade charts").locator("img")).toHaveCount(0);
  return canonical;
}

test("filled-order refresh reads new canonical balance without relying on browser memory", async ({ page }) => {
  const stack = await new OwnedPaperStack().start();
  try {
    await openTicket(page, stack.accountId);
    const order = await submit(page, stack.accountId, "BUY", "1");
    await observe(stack, order.orderId, "100");
    const accountRefresh = page.waitForResponse(response => response.url().endsWith(`/api/paper/accounts/${stack.accountId}`), { timeout: 10_000 });
    await page.getByRole("button", { name: "Refresh order", exact: true }).filter({ visible: true }).first().click();
    const response = await accountRefresh;
    expect(normalizeHttpAccount(await response.json()).balance).toBe("9999.9");
    await expect(page.getByLabel("Account summary")).toContainText("9999.9 USDT");
  } finally { await stack.stop(); }
});

test("equal filled_at uses Paper execution sequence, not browser response order", async ({ page }) => {
  const stack = await new OwnedPaperStack().start();
  try {
    await openTicket(page, stack.accountId);
    const first = await submit(page, stack.accountId, "BUY", "1");
    const second = await submit(page, stack.accountId, "BUY", "2");
    const events = await observe(stack, first.orderId, "100");
    expect(events).toHaveLength(2);
    expect(events[0].filled_at).toBe(events[1].filled_at);
    expect(events.map(event => event.provenance.sequence)).toEqual([1, 2]);
    const open = await trade(page, stack.accountId);
    expect(open.fills.map(fill => fill.orderId)).toEqual([first.orderId, second.orderId]);
    expect(open.fills.map(fill => z.object({ sequence: z.number() }).parse(fill.provenance).sequence)).toEqual([1, 2]);
    const close = await submit(page, stack.accountId, "SELL", "3");
    const closing = await observe(stack, close.orderId, "101");
    expect(closing[0].provenance.sequence).toBe(3);
    const closed = await renderTrade(page, stack.accountId);
    expect(closed.fills).toHaveLength(3); expect(closed.tradeId).toBe(open.tradeId);
    expect(closed.grossPnl).toBe("3"); expect(closed.fees).toBe("0.603"); expect(closed.netPnl).toBe("2.397");
    await analytics(page, stack.accountId, 1);
  } finally { await stack.stop(); }
});

test("owned PostgreSQL browser intent → observation → execution → Journal → Analytics, flows A–H", async ({ page }, info) => {
  const stack = await new OwnedPaperStack().start();
  const errors: string[] = []; const intents: unknown[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => {
    if (request.url().includes("/api/paper/")) expect(request.headers().authorization).toBeUndefined();
    if (request.method() === "POST" && request.url().endsWith("/orders")) intents.push(request.postDataJSON());
  });
  const proof: Record<string, unknown> = { postgresVersion: stack.postgresVersion, browser: info.project.name, preseededFinancialState: false, dependencyOverrides: false, flows: [] };
  try {
    expect(stack.postgresVersion).toMatch(/^16\./);
    await openTicket(page, stack.accountId);
    expect(normalizeHttpAccount(await read(page, stack.accountId)).balance).toBe("10000");
    expect(normalizeHttpPage(await read(page, stack.accountId, "/positions"), normalizeHttpPosition).items).toEqual([]);
    expect(normalizeHttpPage(await read(page, stack.accountId, "/journal"), normalizeHttpTrade).items).toEqual([]);

    // A/F: real server accepted first intent, but its response is lost. Retry UI
    // must retain command_id. We fault the network boundary, not domain logic.
    let dropped = false; let firstBody: unknown; let firstOrder: ReturnType<typeof normalizeHttpOrder> | undefined;
    let release: (() => void) | undefined;
    const held = new Promise<void>(resolve => { release = resolve; });
    await page.route("**/api/paper/accounts/*/orders", async route => {
      if (route.request().method() === "POST" && !dropped) {
        dropped = true; firstBody = route.request().postDataJSON();
        const response = await route.fetch(); firstOrder = normalizeHttpOrder(await response.json());
        await held; await route.abort("failed");
      } else await route.continue();
    });
    await page.getByLabel("Quantity", { exact: true }).fill("1");
    await page.getByRole("button", { name: "Submit paper intent" }).click();
    await expect.poll(() => firstOrder?.status).toBe("ACKNOWLEDGED");
    await expect(page.getByRole("button", { name: "Submitting intent…" })).toBeVisible();
    expect(z.record(z.string(), z.unknown()).parse(firstBody)).not.toHaveProperty("status");
    release?.();
    await expect(page.getByRole("button", { name: "Submit paper intent" })).toBeEnabled();
    const entry = await submit(page, stack.accountId, "BUY", "1");
    expect(entry.orderId).toBe(firstOrder?.orderId);
    expect(z.object({ command_id: z.string() }).parse(firstBody).command_id).toBe(entry.commandId);
    await page.unroute("**/api/paper/accounts/*/orders");
    expect(normalizeHttpPage(await read(page, stack.accountId, "/orders"), normalizeHttpOrder).items).toHaveLength(1);
    expect(normalizeHttpPage(await read(page, stack.accountId, "/journal"), normalizeHttpTrade).items).toEqual([]);
    expect(await observe(stack, entry.orderId, "100", { eligibilityProbe: true })).toEqual([]);
    const entryEvents = await observe(stack, entry.orderId, "100"); expect(entryEvents).toHaveLength(1);
    expect(entryEvents[0].price).toBe("100");
    expect(z.array(eventSchema).parse((await stack.command("repeat")).events)).toEqual([]);
    await page.getByRole("button", { name: "Refresh order", exact: true }).filter({ visible: true }).first().click();
    await expect(page.getByLabel("Orders")).toContainText("FILLED");
    expect(normalizeHttpAccount(await read(page, stack.accountId)).balance).toBe("9999.9");
    await expect(page.getByLabel("Account summary")).toContainText("9999.9 USDT");
    const open = await trade(page, stack.accountId); expect(open.status).toBe("OPEN"); expect(open.side).toBe("LONG"); expect(open.fills).toHaveLength(1);
    expect(normalizeHttpAccount(await read(page, stack.accountId)).reservedCollateral).toBe("100");
    await page.goto("/positions"); await expect(page.getByText("BTCUSDT · LONG", { exact: true })).toBeVisible();
    const openStats = await analytics(page, stack.accountId, 0); expect(openStats.metrics.netPnl).toBe("0");
    await openTicket(page, stack.accountId);
    const exit = await submit(page, stack.accountId, "SELL", "1");
    expect(await observe(stack, exit.orderId, "110")).toHaveLength(1);
    await page.reload();
    const closed = await renderTrade(page, stack.accountId);
    expect(closed.status).toBe("CLOSED"); expect(closed.grossPnl).toBe("10"); expect(closed.fees).toBe("0.21"); expect(closed.netPnl).toBe("9.79"); expect(closed.pnlPercent).toBe("9.79"); expect(closed.result).toBe("WIN");
    expect(normalizeHttpPage(await read(page, stack.accountId, "/positions"), normalizeHttpPosition).items[0].remainingQuantity).toBe("0");
    expect(normalizeHttpAccount(await read(page, stack.accountId)).balance).toBe("10009.79");
    const longStats = await analytics(page, stack.accountId, 1); expect(longStats.metrics.wins).toBe(1); expect(longStats.metrics.netPnl).toBe("9.79"); expect(longStats.metrics.profitFactor).toBeNull();
    proof.long = { tradeId: closed.tradeId, netPnl: closed.netPnl, fees: closed.fees, retrySingleEffect: true };

    // G: canonical metadata versions, retained draft on genuine 409.
    await renderTrade(page, stack.accountId);
    await page.getByLabel("Notes", { exact: true }).fill("owned browser draft");
    await page.getByLabel("Tags · comma separated").fill("e2e, reviewed");
    const updateStatus = await page.evaluate(async ({ accountId, tradeId, version }) => (await fetch(`/api/paper/accounts/${accountId}/journal/${tradeId}/metadata`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_version: version, notes: "concurrent authorized edit", tags: ["review"] }) })).status, { accountId: stack.accountId, tradeId: closed.tradeId, version: closed.metadataVersion });
    expect(updateStatus).toBe(200);
    await page.getByRole("button", { name: "Save notes & tags" }).click();
    await expect(page.getByRole("button", { name: "Reload latest metadata" })).toBeVisible();
    await expect(page.getByLabel("Notes", { exact: true })).toHaveValue("owned browser draft");
    await page.getByRole("button", { name: "Reload latest metadata" }).click();
    await expect(page.getByLabel("Notes", { exact: true })).toHaveValue("concurrent authorized edit");
    await page.getByLabel("Notes", { exact: true }).fill("reviewed browser notes");
    await page.getByLabel("Tags · comma separated").fill("e2e, reviewed");
    await page.getByRole("button", { name: "Save notes & tags" }).click();
    await expect(page.getByText(/Review metadata saved/)).toBeVisible();
    const edited = await trade(page, stack.accountId); expect(edited.notes).toBe("reviewed browser notes"); expect(edited.tags).toEqual(["e2e", "reviewed"]); expect(edited.netPnl).toBe(closed.netPnl); expect(edited.fills).toEqual(closed.fills);
    await stack.restartFrontend(); await page.reload(); await expect(page.getByLabel("Notes", { exact: true })).toHaveValue("reviewed browser notes");
    await expect(page.getByLabel("Trade charts")).toContainText("PENDING");
    await expect(page.locator(".product-account-badge")).toHaveText("PAPER · HTTP / BACKEND");
    const artifact = resolve("../docs/paper-e2e-v1"); mkdirSync(artifact, { recursive: true });
    await page.screenshot({ path: `${artifact}/${info.project.name}-closed-journal.png`, fullPage: true });

    // B: fresh flat account; frozen non-trivial average and partial close.
    await stack.newAccount(); await openTicket(page, stack.accountId);
    const a = await submit(page, stack.accountId, "BUY", "1"); const ea = await observe(stack, a.orderId, "100");
    const firstScaleTrade = await trade(page, stack.accountId);
    const b = await submit(page, stack.accountId, "BUY", "2"); const eb = await observe(stack, b.orderId, "101");
    const scale = await trade(page, stack.accountId);
    expect(scale.tradeId).toBe(firstScaleTrade.tradeId); expect(scale.fills).toHaveLength(2);
    expect(scale.averageEntry).toBe("100.66666666666666666666666666666666666666666666667");
    const partial = await submit(page, stack.accountId, "SELL", "1"); const ec = await observe(stack, partial.orderId, "102");
    const partly = await trade(page, stack.accountId); expect(partly.status).toBe("PARTIALLY_CLOSED"); expect(partly.remainingQuantity).toBe("2"); expect(partly.tradeId).toBe(scale.tradeId); expect(partly.fills).toHaveLength(3);
    const position = normalizeHttpPage(await read(page, stack.accountId, "/positions"), normalizeHttpPosition).items[0]; expect(position.side).toBe("LONG"); expect(position.remainingQuantity).toBe("2");
    expect(normalizeHttpAnalytics(await read(page, stack.accountId, "/analytics"), "HTTP / BACKEND").metrics.totalTrades).toBe(0);
    await page.goto(`/journal/${partly.tradeId}`); await expect(page.getByLabel("Trade summary")).toContainText("PARTIALLY CLOSED");
    await expect(page.getByText("Fill history · 3 fills")).toBeVisible();
    await openTicket(page, stack.accountId);
    const final = await submit(page, stack.accountId, "SELL", "2"); const ed = await observe(stack, final.orderId, "103");
    const scaled = await renderTrade(page, stack.accountId); expect(scaled.fills).toHaveLength(4); expect(scaled.tradeId).toBe(scale.tradeId); expect(scaled.grossPnl).toBe("6"); expect(scaled.fees).toBe("0.61"); expect(scaled.netPnl).toBe("5.39");
    expect([ea[0], eb[0], ec[0], ed[0]].map(event => event.provenance.sequence)).toEqual([1, 2, 3, 4]);
    expect(scaled.fills.map(fill => fill.time)).toEqual([ea[0], eb[0], ec[0], ed[0]].map(event => event.filled_at));
    await analytics(page, stack.accountId, 1); proof.scale = { tradeId: scaled.tradeId, averageEntry: scaled.averageEntry, netPnl: scaled.netPnl, fills: 4 };

    // C: fresh account SHORT, explicit BUY close, financial loss preserved.
    await stack.newAccount(); await openTicket(page, stack.accountId);
    const shortOpen = await submit(page, stack.accountId, "SELL", "1"); await observe(stack, shortOpen.orderId, "100");
    const short = await trade(page, stack.accountId); expect(short.side).toBe("SHORT"); expect(short.status).toBe("OPEN");
    await page.goto("/positions"); await expect(page.getByText("BTCUSDT · SHORT", { exact: true })).toBeVisible();
    await openTicket(page, stack.accountId);
    const shortExit = await submit(page, stack.accountId, "BUY", "1"); await observe(stack, shortExit.orderId, "110");
    const shortClosed = await renderTrade(page, stack.accountId); expect(shortClosed.netPnl).toBe("-10.21"); expect(shortClosed.result).toBe("LOSS");
    const shortStats = await analytics(page, stack.accountId, 1); expect(shortStats.metrics.losses).toBe(1); expect(shortStats.metrics.grossLoss).toBe("10.21"); expect(shortStats.metrics.profitFactor).toBe("0");
    expect(shortStats.breakdowns.find(row => row.dimension === "SIDE" && row.label === "LONG")?.metrics.totalTrades).toBe(0);
    expect(shortStats.breakdowns.find(row => row.dimension === "SIDE" && row.label === "SHORT")?.metrics.totalTrades).toBe(1);
    proof.short = { tradeId: shortClosed.tradeId, netPnl: shortClosed.netPnl };

    // D: contiguous observations: first does not touch; second fills LIMIT
    // at intent90 even though the observed close is95.
    await stack.newAccount(); await openTicket(page, stack.accountId);
    const limit = await submit(page, stack.accountId, "BUY", "1", "90");
    expect(await observe(stack, limit.orderId, "100", { low: "99", high: "101" })).toEqual([]);
    expect(normalizeHttpPage(await read(page, stack.accountId, "/journal"), normalizeHttpTrade).items).toEqual([]);
    expect(normalizeHttpPage(await read(page, stack.accountId, "/positions"), normalizeHttpPosition).items).toEqual([]);
    expect(normalizeHttpOrder(await read(page, stack.accountId, `/orders/${limit.orderId}`)).status).toBe("ACKNOWLEDGED");
    expect(normalizeHttpAnalytics(await read(page, stack.accountId, "/analytics"), "HTTP / BACKEND").metrics.totalTrades).toBe(0);
    const limitEvents = await observe(stack, limit.orderId, "95", { low: "89", high: "96" }); expect(limitEvents).toHaveLength(1); expect(limitEvents[0].price).toBe("90");
    const limitTrade = await trade(page, stack.accountId); expect(limitTrade.averageEntry).toBe("90");
    proof.limit = { tradeId: limitTrade.tradeId, exactLimit: "90", observationClose: "95", initiallyUnfilled: true };

    // E: actual backend owner checks PLUS Next account filter. Revocation clears
    // already loaded account/Journal/Analytics/detail resources, no demo fallback.
    expect(await stack.directStatus(stack.accountId, "", "GET", undefined, false)).toBe(401);
    for (const [path, method, body] of [["", "GET", undefined], ["/orders", "POST", { command_id: "foreign", symbol: "BTCUSDT", side: "BUY", order_type: "MARKET", quantity: "1" }], ["/journal/absent/metadata", "PATCH", { expected_version: 0, notes: "forged", tags: [] }], ["/analytics", "GET", undefined], ["/trades/absent/attachments", "GET", undefined]] as const)
      expect(await stack.directStatus(stack.foreignId, path, method, body)).toBe(403);
    expect(await page.evaluate(async id => (await fetch(`/api/paper/accounts/${id}`)).status, stack.foreignId)).toBe(403);
    const before = await read(page, stack.accountId);
    await stack.command("removeOwnership");
    await page.getByRole("button", { name: "Refresh orders" }).click();
    await expect(page.getByText("FORBIDDEN", { exact: true }).first()).toBeVisible();
    await expect(page.getByLabel("Account summary")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Submit paper intent" })).toHaveCount(0);
    await page.goto("/journal"); await expect(page.locator(".journal-card")).toHaveCount(0);
    await page.goto("/analytics"); await expect(page.locator(".analytics-core")).toHaveCount(0);
    await page.goto(`/journal/${limitTrade.tradeId}`); await expect(page.getByLabel("Trade summary")).toHaveCount(0);
    await stack.command("restoreOwnership"); await openTicket(page, stack.accountId);
    expect(await read(page, stack.accountId)).toEqual(before);
    await stack.command("revoke");
    const revoked = page.waitForResponse(response => response.url().endsWith(`/accounts/${stack.accountId}/orders`) && response.status() === 401, { timeout: 10_000 });
    await page.getByRole("button", { name: "Refresh orders" }).click();
    expect(z.object({ error: z.object({ code: z.literal("AUTH_REQUIRED") }) }).parse(await (await revoked).json()).error.code).toBe("AUTH_REQUIRED");
    await expect(page.getByText("AUTH REQUIRED", { exact: true }).first()).toBeVisible();
    await expect(page.getByLabel("Account summary")).toHaveCount(0);
    await expect(page.locator(".fixture-controls")).toHaveCount(0);
    expect(await stack.directStatus(stack.accountId)).toBe(401);
    expect(await page.content()).not.toMatch(/paper_v1_[A-Za-z0-9_-]{43}/);
    expect(await page.evaluate(() => Object.keys(localStorage))).toEqual([]);
    expect(await page.evaluate(() => Object.keys(sessionStorage))).toEqual([]);
    for (const intent of intents) expect(Object.keys(z.record(z.string(), z.unknown()).parse(intent)).sort()).toEqual(["command_id", "limit_price", "order_type", "quantity", "side", "symbol"]);
    expect(errors).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    proof.flows = ["A", "B", "C", "D", "E", "F", "G", "H"];
    proof.classification = "E2E_EXECUTION_PATH_VERIFIED";
    proof.productionWorker = "PRODUCTION_OBSERVATION_WORKER_NOT_IMPLEMENTED";
    writeFileSync(`${artifact}/${info.project.name}-proof.json`, JSON.stringify(proof, null, 2));
  } finally { await stack.stop(); }
});
