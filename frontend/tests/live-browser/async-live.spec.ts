import { expect, test } from "@playwright/test";
import { writeFileSync } from "node:fs";

declare global { interface Window { __latencies: number[] } }

test("actual Next proxy and real BTC/ETH complete with usable chart during evaluation", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  const errors: string[] = [];
  const requests: { path: string; status: number; time: number; cacheControl: string | null }[] = [];
  const rows: { symbol: string; completed_ui_s: number; decision: string; maximum_main_thread_timer_gap_ms: number }[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("response", (response) => {
    if (response.url().includes("/api/")) requests.push({ path: new URL(response.url()).pathname, status: response.status(), time: Date.now(), cacheControl: response.headers()["cache-control"] ?? null });
  });
  await page.addInitScript(() => {
    window.__latencies = []; let previous = performance.now();
    setInterval(() => { const now = performance.now(); window.__latencies.push(now-previous); previous = now; }, 50);
  });
  for (const symbol of ["BTCUSDT", "ETHUSDT"]) {
    const start = Date.now();
    if (symbol === "BTCUSDT") await page.goto("/");
    else await page.getByLabel("Symbol", { exact: true }).selectOption(symbol);
    await expect(page.locator('[data-evaluation-status="RUNNING"]')).toBeVisible({ timeout: 30_000 });
    await expect(page.locator(".primary-chart canvas").first()).toBeVisible({ timeout: 20_000 });
    await expect(page.locator(".decision-banner")).toHaveCount(0);
    await page.screenshot({ path: `../docs/frontend-product-v1/async-live-${symbol.toLowerCase()}-running.png`, fullPage: true });
    await page.getByRole("button", { name: "1H", exact: true }).click();
    await expect(page.locator(".decision-banner")).toBeVisible({ timeout: 150_000 });
    rows.push({ symbol, completed_ui_s: (Date.now()-start)/1000,
      decision: await page.locator(".decision-banner").innerText(),
      maximum_main_thread_timer_gap_ms: await page.evaluate(() => Math.max(...window.__latencies)) });
    await page.screenshot({ path: `../docs/frontend-product-v1/async-live-${symbol.toLowerCase()}-completed.png`, fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  expect(errors).toEqual([]);
  expect(requests.filter((row) => row.path === "/api/evaluations")).toHaveLength(2);
  expect(requests.every((row) => row.status >= 200 && row.status < 300)).toBe(true);
  expect(requests.filter((row) => row.path.startsWith("/api/evaluations")).every((row) => row.cacheControl?.includes("no-store"))).toBe(true);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(async () => {
    const bounds = await page.locator(".primary-chart").boundingBox();
    return bounds ? bounds.x+bounds.width <= 390 : false;
  }).toBe(true);
  await expect.poll(async () => {
    const bounds = await page.locator(".chart-header").boundingBox();
    return bounds ? bounds.x+bounds.width <= 390 : false;
  }).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "../docs/frontend-product-v1/async-live-ethusdt-mobile-completed.png", fullPage: true });
  writeFileSync("../experiments/backend_evaluation_performance_v1/async_live_browser.json", JSON.stringify({
    source: "actual current Next production page + original default 10 s proxy + real Binance Spot backend; no fixtures", rows, requests, errors, status: "PASS",
  }, null, 2));
});
