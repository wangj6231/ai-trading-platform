import { expect, test, type Page } from "@playwright/test";
import { analysisFixture, signalFixture } from "../fixtures/mtf-contract";
import { evaluationFixture } from "../fixtures/evaluation-job";
import type { SymbolCode } from "@/types/trading";
import type { EvaluationJob } from "@/lib/evaluations";

async function fixtureNetwork(page: Page, decision: "LONG" | "SHORT" | "NO_TRADE" = "LONG", fail = false,
  lifecycle?: { status: EvaluationJob["status"]; reads: number; cancellations: number; results: number }) {
  await page.clock.install({ time: new Date("2025-01-01T00:31:00Z") });
  const strategyBodies: unknown[] = [];
  const jobs = new Map<string, SymbolCode>();
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (fail) return route.fulfill({ status: 503, json: { error: { code: "BACKEND_UNAVAILABLE", message: "Backend service is unavailable." } } });
    if (url.pathname === "/api/evaluations") {
      const symbol: SymbolCode = request.postDataJSON().symbol;
      strategyBodies.push(request.postDataJSON());
      const id = `00000000-0000-4000-8000-${String(strategyBodies.length).padStart(12, "0")}`;
      jobs.set(id, symbol);
      return route.fulfill({ status: 202, json: evaluationFixture(lifecycle?.status ?? "COMPLETED", symbol, id) });
    }
    const symbol = url.searchParams.get("symbol") ?? jobs.get(url.pathname.split("/")[3]) ?? "BTCUSDT";
    if (/^\/api\/evaluations\/[^/]+$/.test(url.pathname)) {
      if (request.method() === "DELETE" && lifecycle) { lifecycle.cancellations++; lifecycle.status = "CANCELLED"; }
      else if (lifecycle) lifecycle.reads++;
      return route.fulfill({ json: evaluationFixture(lifecycle?.status ?? "COMPLETED", symbol as SymbolCode, url.pathname.split("/")[3]) });
    }
    const data = { ...signalFixture.provenance, symbol };
    if (url.pathname.endsWith("/signal")) {
      if (lifecycle) lifecycle.results++;
      return route.fulfill({ json: { ...signalFixture, symbol, provenance: data, decision, algorithm_decision: decision, final_decision: decision,
        ...(decision === "NO_TRADE" ? { entry_min: null, entry_max: null, take_profit: null, stop_loss: null, risk_reward: null, reason_codes: ["MTF_NOT_ALIGNED", "NO_CANDIDATE"] } : decision === "SHORT" ? { take_profit: 90, stop_loss: 110 } : {}),
      } });
    }
    if (url.pathname.endsWith("/analysis")) {
      if (lifecycle) lifecycle.results++;
      const analysis = structuredClone(analysisFixture);
      Object.assign(analysis, { symbol, provenance: data });
      analysis.evaluation.symbol = symbol;
      const mtf = analysis.evaluation.multi_timeframe_result;
      if (decision !== "LONG") Object.assign(mtf, { alignment: decision === "NO_TRADE" ? "CONFLICTING" : "ALIGNED", eligibility: decision === "NO_TRADE" ? "NO_TRADE" : "SHORT_ELIGIBLE", trade_allowed: decision !== "NO_TRADE", bullish_count: 0, bearish_count: decision === "SHORT" ? 3 : 1 });
      if (decision === "SHORT") for (const row of Object.values(mtf.timeframes)) if (row.role !== "CONTEXT_ONLY") row.state = "BEARISH";
      mtf.timeframes["2h"].stale = true;
      mtf.timeframes["2h"].reason_codes = ["MTF_STATE_STALE"];
      return route.fulfill({ json: analysis });
    }
    const timeframe = url.searchParams.get("timeframe")!;
    const period = { "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400, "1w": 604800 }[timeframe] ?? 900;
    const cutoff = Math.floor(Date.parse(data.data_cutoff_at) / (period * 1000)) * period * 1000;
    const candles = Array.from({ length: 120 }, (_, index) => {
      const open = 100 + Math.sin(index / 8) * 4 + index / 50;
      const close = open + Math.sin(index * 2) * 1.2;
      return { timestamp: new Date(cutoff - (120 - index) * period * 1000).toISOString(), open, high: Math.max(open, close) + 1, low: Math.min(open, close) - 1, close, volume: 20 };
    });
    return route.fulfill({ json: { symbol, timeframe, source: data.provider, retrieved_at: data.retrieved_at, candles,
      provenance: { ...data, timeframe, received_candles: candles.length, data_cutoff_at: new Date(cutoff).toISOString(), first_candle_at: candles[0].timestamp, last_candle_at: candles.at(-1)!.timestamp },
    } });
  });
  return strategyBodies;
}

async function checkLayout(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
}

test("desktop actual chart and every display period preserve strategy; refresh and symbol operate", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const bodies = await fixtureNetwork(page);
  await page.goto("/");
  const panel = page.getByLabel("Deterministic signal panel");
  await expect(panel.getByText("LONG", { exact: true })).toBeVisible();
  await expect(page.locator(".primary-chart canvas").first()).toBeVisible();
  await expect(panel.getByText("fixture-strategy-v1", { exact: true })).toBeVisible();
  await checkLayout(page);
  await page.screenshot({ path: "../docs/frontend-product-v1/desktop-fixture.png", fullPage: true });
  for (const timeframe of ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d", "1w"]) {
    await page.getByRole("button", { name: timeframe.toUpperCase(), exact: true }).click();
    await expect(page.locator(".primary-chart canvas").first()).toBeVisible();
    await expect(panel.getByText("LONG", { exact: true })).toBeVisible();
    await expect(panel.getByText(signalFixture.data_cutoff_at, { exact: true })).toBeVisible();
  }
  expect(bodies).toEqual([{ symbol: "BTCUSDT" }]);
  await page.getByRole("button", { name: "Refresh strategy", exact: true }).click();
  await expect.poll(() => bodies.length).toBe(2);
  await page.getByLabel("Symbol", { exact: true }).selectOption("ETHUSDT");
  await expect(panel.locator(".signal-market")).toContainText("ETHUSDT");
  await expect(panel.getByText("LONG", { exact: true })).toBeVisible();
  expect(bodies.slice(-1)).toEqual([{ symbol: "ETHUSDT" }]);
  await expect(page.getByLabel("Symbol", { exact: true }).locator("option")).toHaveCount(2);
  expect(errors).toEqual([]);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(async () => {
    const bounds = await page.locator(".chart-header").boundingBox();
    return bounds ? bounds.x+bounds.width <= 390 : false;
  }).toBe(true);
  await expect.poll(async () => {
    const bounds = await page.locator(".primary-chart").boundingBox();
    return bounds ? bounds.x+bounds.width <= 390 : false;
  }).toBe(true);
  await page.screenshot({ path: "../docs/frontend-product-v1/mobile-resize-completed-fixture.png", fullPage: true });
});

test("queued and running execution show no provisional decision; chart remains operable until full completion", async ({ page }) => {
  const lifecycle = { status: "PENDING" as EvaluationJob["status"], reads: 0, cancellations: 0, results: 0 };
  await page.setViewportSize({ width: 1440, height: 1000 });
  const bodies = await fixtureNetwork(page, "LONG", false, lifecycle);
  await page.goto("/");
  await expect(page.getByText("Evaluation queued", { exact: true })).toBeVisible();
  await expect(page.locator(".primary-chart canvas").first()).toBeVisible();
  await expect(page.getByLabel("Loading signal", { exact: true })).toBeVisible();
  await expect(page.locator(".decision-banner")).toHaveCount(0);
  expect(lifecycle.results).toBe(0);
  await page.screenshot({ path: "../docs/frontend-product-v1/async-pending-fixture.png", fullPage: true });
  lifecycle.status = "RUNNING";
  await page.clock.runFor(1600);
  await expect(page.locator('[data-evaluation-status="RUNNING"]')).toBeVisible();
  await page.getByRole("button", { name: "1D", exact: true }).click();
  expect(bodies).toEqual([{ symbol: "BTCUSDT" }]);
  await expect(page.locator(".decision-banner")).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await checkLayout(page);
  await page.screenshot({ path: "../docs/frontend-product-v1/async-running-mobile-fixture.png", fullPage: true });
  lifecycle.status = "COMPLETED";
  await page.clock.runFor(1600);
  await expect(page.getByLabel("Deterministic signal panel").getByText("LONG", { exact: true })).toBeVisible();
  expect(lifecycle.results).toBe(2);
  const reads = lifecycle.reads;
  await page.clock.runFor(60_000);
  expect(lifecycle.reads).toBe(reads);
});

for (const terminal of ["FAILED", "CANCELLED"] as const) {
  test(`${terminal} is an execution outcome and never NO_TRADE`, async ({ page }) => {
    const lifecycle = { status: "RUNNING" as EvaluationJob["status"], reads: 0, cancellations: 0, results: 0 };
    await page.setViewportSize({ width: 390, height: 844 });
    await fixtureNetwork(page, "LONG", false, lifecycle);
    await page.goto("/");
    await expect(page.locator('[data-evaluation-status="RUNNING"]')).toBeVisible();
    if (terminal === "CANCELLED") {
      await page.getByRole("button", { name: "Cancel evaluation", exact: true }).click();
      expect(lifecycle.cancellations).toBe(1);
    } else lifecycle.status = "FAILED";
    await page.clock.runFor(1600);
    await expect(page.locator(`[data-evaluation-status="${terminal}"]`)).toBeVisible();
    await expect(page.getByText("ANALYSIS UNAVAILABLE", { exact: true })).toBeVisible();
    await expect(page.getByText("NO_TRADE", { exact: true })).toHaveCount(0);
    await expect(page.locator(".decision-banner")).toHaveCount(0);
    expect(lifecycle.results).toBe(0);
    await checkLayout(page);
    await page.screenshot({ path: `../docs/frontend-product-v1/async-${terminal.toLowerCase()}-fixture.png`, fullPage: true });
  });
}

test("completion across a new closed bucket immediately marks the accepted result stale", async ({ page }) => {
  const lifecycle = { status: "RUNNING" as EvaluationJob["status"], reads: 0, cancellations: 0, results: 0 };
  await fixtureNetwork(page, "LONG", false, lifecycle);
  await page.goto("/");
  await expect(page.locator('[data-evaluation-status="RUNNING"]')).toBeVisible();
  // Change wall time without firing the existing 30-second freshness timer.
  await page.clock.setSystemTime(new Date("2025-01-01T00:45:01Z"));
  lifecycle.status = "COMPLETED";
  await page.clock.runFor(1600);
  const panel = page.getByLabel("Deterministic signal panel");
  await expect(panel.getByText("LONG", { exact: true })).toBeVisible();
  await expect(panel.getByText("STALE SNAPSHOT", { exact: true })).toBeVisible();
  await expect(page.locator(".chart-zone.entry, .chart-zone.tp, .chart-zone.sl")).toHaveCount(0);
});

test("mobile roles, required/veto, context status and NO_TRADE remain readable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await fixtureNetwork(page, "NO_TRADE");
  await page.goto("/");
  const panel = page.getByLabel("Deterministic signal panel");
  await expect(panel.locator(".decision-banner").getByText("NO_TRADE", { exact: true })).toBeVisible();
  await expect(panel.getByText("MTF_NOT_ALIGNED", { exact: true })).toBeVisible();
  await expect(panel.getByText("NO_CANDIDATE", { exact: true })).toBeVisible();
  await expect(panel.getByText("TAKE PROFIT", { exact: true })).toHaveCount(0);
  const context = page.locator('[data-mtf-timeframe="1w"]');
  await expect(context).toContainText("NO ALIGNMENT / VETO AUTHORITY");
  await expect(context).toContainText("UNAVAILABLE · NOT READY");
  await expect(context.locator(".authority-badges")).toHaveCount(0);
  await expect(page.locator('[data-mtf-timeframe="1d"] .veto-badge')).toContainText("VETO");
  await expect(page.locator('[data-mtf-timeframe="2h"]')).toContainText("STALE");
  await checkLayout(page);
  await page.screenshot({ path: "../docs/frontend-product-v1/mobile-no-trade-fixture.png", fullPage: true });
  for (const width of [320, 768, 1050, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await checkLayout(page);
    await expect(page.getByRole("button", { name: "1W", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Refresh strategy", exact: true })).toBeVisible();
  }
});

test("stale clock warns and removes trade overlays while preserving backend decision", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await fixtureNetwork(page, "SHORT");
  await page.goto("/");
  const panel = page.getByLabel("Deterministic signal panel");
  await expect(panel.getByText("SHORT", { exact: true })).toBeVisible();
  await page.clock.fastForward(15 * 60 * 1000);
  await expect(panel.getByText("STALE SNAPSHOT", { exact: true })).toBeVisible();
  await expect(panel.getByText("SHORT", { exact: true })).toBeVisible();
  await expect(page.locator(".chart-zone.entry, .chart-zone.tp, .chart-zone.sl")).toHaveCount(0);
  await page.screenshot({ path: "../docs/frontend-product-v1/stale-short-fixture.png", fullPage: true });
});

test("loading and API error are separate from NO_TRADE and retries are usable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  let release!: () => void;
  const pending = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/**", async (route) => { await pending; await route.fulfill({ status: 503, json: { error: { code: "BACKEND_UNAVAILABLE", message: "Backend service is unavailable." } } }); });
  await page.goto("/");
  await expect(page.getByText("LOADING MARKET DATA", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Loading signal", { exact: true })).toBeVisible();
  await page.screenshot({ path: "../docs/frontend-product-v1/loading-fixture.png", fullPage: true });
  release();
  await expect(page.getByText("CHART DATA UNAVAILABLE", { exact: true })).toBeVisible();
  await expect(page.getByText("ANALYSIS UNAVAILABLE", { exact: true })).toBeVisible();
  await expect(page.getByText("NO_TRADE", { exact: true })).toHaveCount(0);
  await checkLayout(page);
  await page.screenshot({ path: "../docs/frontend-product-v1/error-fixture.png", fullPage: true });
  await page.unrouteAll({ behavior: "wait" });
  await fixtureNetwork(page);
  await page.getByRole("button", { name: "RETRY", exact: true }).click();
  await expect(page.getByLabel("Deterministic signal panel").getByText("LONG", { exact: true })).toBeVisible();
});
