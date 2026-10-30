import { test, expect } from "@playwright/test";

async function scope(page: import("@playwright/test").Page) {
  const response = await page.waitForResponse(response => /\/api\/paper\/accounts\/[^/]+$/.test(response.url()) && response.status() === 200);
  return (await response.json()).account_id as string;
}
test("actual authenticated proxy MARKET/LIMIT, idempotency, ACK, UNKNOWN, rejection, cancel and safe errors", async ({ page }) => {
  const pending = scope(page); await page.goto("/paper-trading"); const account = await pending; const base = `/api/paper/accounts/${account}`;
  const proof = await page.evaluate(async base => {
    const request = async (path: string, method = "GET", body?: unknown) => { const response = await fetch(base + path, { method, headers: { "Content-Type": "application/json" }, ...(body ? { body: JSON.stringify(body) } : {}) }); return { status: response.status, body: await response.json(), etag: response.headers.get("ETag") }; };
    const body = { command_id: "browser-market-once", symbol: "BTCUSDT", side: "BUY", order_type: "MARKET", quantity: "0.01", limit_price: null };
    const market = await request("/orders", "POST", body); const retry = await request("/orders", "POST", body); const conflict = await request("/orders", "POST", { ...body, quantity: "0.02" });
    const limit = await request("/orders", "POST", { ...body, command_id: "browser-limit-once", order_type: "LIMIT", limit_price: "99" });
    const cancel = await request(`/orders/${limit.body.order_id}/cancel`, "POST"); const allOrders = await request("/orders?limit=100");
    return { market, retry, conflict, limit, cancel, allOrders, missing: await request("/orders/missing"), invalid: await request("/orders?limit=0"), foreign: (await fetch("/api/paper/accounts/foreign-account")).status };
  }, base);
  expect(proof.market.status).toBe(200); expect(proof.market.body.status).toBe("ACKNOWLEDGED"); expect(proof.market.body.filled_quantity).toBe("0"); expect(proof.retry.body.order_id).toBe(proof.market.body.order_id); expect(proof.conflict.status).toBe(409);
  expect(proof.limit.body.limit_price).toBe("99"); expect(proof.cancel.body.cancellation_status).toBe("CANCELLED"); expect(proof.missing.status).toBe(404); expect(proof.invalid.status).toBe(422); expect(proof.foreign).toBe(403);
  expect(proof.allOrders.body.items.some((order: { status: string }) => order.status === "UNKNOWN")).toBe(true); expect(proof.allOrders.body.items.some((order: { error_code: string }) => order.error_code === "INSUFFICIENT_BALANCE")).toBe(true);
  await page.getByLabel("Quantity", { exact: true }).fill("0.01"); await page.getByRole("button", { name: "Submit paper intent" }).click(); await expect(page.getByRole("button", { name: "Submit paper intent" })).toBeEnabled();
  await expect(page.getByLabel("Orders")).toContainText("Acknowledged ≠ filled"); expect(await page.locator(".fixture-controls").count()).toBe(0);
});

for (const width of [1440, 390, 320]) test(`${width}px actual HTTP pages, pagination, independent fills/attachments, Journal conflict and Analytics`, async ({ page }) => {
  await page.setViewportSize({ width, height: 950 }); const errors: string[] = []; const browserHeaders: Record<string, string>[] = [];
  page.on("pageerror", error => errors.push(error.message)); page.on("request", request => { if (request.url().includes("/api/paper/")) browserHeaders.push(request.headers()); });
  const pending = scope(page); await page.goto("/paper-trading"); const account = await pending;
  await expect(page.getByLabel("Account summary")).toContainText("PAPER_DIRECTIONAL_V1"); await expect(page.getByText("HTTP / BACKEND", { exact: true }).first()).toBeVisible();
  const allTrades = await page.evaluate(async account => (await (await fetch(`/api/paper/accounts/${account}/trades?limit=100`)).json()).items, account);
  const trade = allTrades.find((trade: { fills: unknown[] }) => trade.fills.length === 4); expect(trade).toBeTruthy();
  await page.getByRole("navigation", { name: "Product navigation" }).getByRole("link", { name: "Journal", exact: true }).click(); await expect(page.locator(".journal-card")).toHaveCount(20);
  await expect(page.getByText(/not complete account history/)).toBeVisible(); await page.getByRole("button", { name: "Next journal page" }).click(); await expect(page.locator(".journal-card")).toHaveCount(allTrades.length - 20);
  await page.goto(`/journal/${trade.trade_id}`); await expect(page.getByText("Fill history · 4 fills")).toBeVisible(); await expect(page.getByLabel("Trade summary")).toContainText("5.39 USDT");
  await expect(page.getByText("No verified strategy attribution")).toBeVisible(); await expect(page.getByLabel("Trade charts")).toContainText("FAILED"); await expect(page.getByLabel("Trade charts")).toContainText("PENDING"); await expect(page.getByLabel("Trade charts").locator("img")).toHaveCount(0); await expect(page.getByLabel("Setup metadata")).toBeDisabled();
  await page.getByLabel("Notes", { exact: true }).fill(`draft-${width}`);
  const current = await page.evaluate(async ({ account, id }) => (await (await fetch(`/api/paper/accounts/${account}/trades/${id}`)).json()).annotations.version, { account, id: trade.trade_id });
  await page.evaluate(async ({ account, id, version }) => { const response = await fetch(`/api/paper/accounts/${account}/journal/${id}/metadata`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_version: version, notes: "concurrent server edit", tags: ["review"] }) }); if (!response.ok) throw new Error("controlled metadata update failed"); }, { account, id: trade.trade_id, version: current });
  await page.getByRole("button", { name: "Save notes & tags" }).click(); await expect(page.getByRole("button", { name: "Reload latest metadata" })).toBeVisible(); await expect(page.getByLabel("Notes", { exact: true })).toHaveValue(`draft-${width}`);
  await page.getByRole("button", { name: "Reload latest metadata" }).click(); await expect(page.getByLabel("Notes", { exact: true })).toHaveValue("concurrent server edit"); await page.getByLabel("Notes", { exact: true }).fill(`reviewed-${width}`); await page.getByRole("button", { name: "Save notes & tags" }).click(); await expect(page.getByText(/Review metadata saved/)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true); await page.screenshot({ path: `../docs/frontend-paper-http-v1/http-trade-${width}.png`, fullPage: true });
  await page.getByRole("navigation", { name: "Product navigation" }).getByRole("link", { name: "Positions", exact: true }).click(); await expect(page.getByText("BTCUSDT · LONG", { exact: true })).toBeVisible(); await expect(page.getByText("ETHUSDT · SHORT", { exact: true })).toBeVisible();
  await page.getByRole("navigation", { name: "Product navigation" }).getByRole("link", { name: "Analytics", exact: true }).click(); await expect(page.getByText(/No verified membership list/)).toBeVisible(); await expect(page.getByText(/Strategy analytics unavailable/)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true); await page.screenshot({ path: `../docs/frontend-paper-http-v1/http-analytics-${width}.png`, fullPage: true });
  for (const headers of browserHeaders) expect(headers.authorization).toBeUndefined(); expect(await page.content()).not.toMatch(/paper_v1_[A-Za-z0-9_-]{43}/); expect(await page.evaluate(() => Object.keys(localStorage))).toEqual([]); expect(await page.evaluate(() => Object.keys(sessionStorage))).toEqual([]); expect(errors).toEqual([]);
});
