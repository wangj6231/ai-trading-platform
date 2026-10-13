import { expect, test } from "@playwright/test";
import { analysisFixture, signalFixture } from "../fixtures/mtf-contract";
import { evaluationFixture } from "../fixtures/evaluation-job";

test("ten chart periods keep server clock/cutoff/identity; context-only has no authority", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const strategyBodies: unknown[] = [];
  const chartPeriods: string[] = [];
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/api/evaluations") {
      strategyBodies.push(request.postDataJSON());
      return route.fulfill({ status: 202, json: evaluationFixture() });
    }
    if (url.pathname.endsWith("/signal")) return route.fulfill({ json: signalFixture });
    if (url.pathname.endsWith("/analysis")) return route.fulfill({ json: analysisFixture });
    const timeframe = url.searchParams.get("timeframe")!;
    chartPeriods.push(timeframe);
    return route.fulfill({ json: { symbol: "BTCUSDT", timeframe, source: signalFixture.source,
      retrieved_at: signalFixture.retrieved_at,
      provenance: { ...signalFixture.provenance, timeframe, received_candles: 1 },
      candles: [{ timestamp: "2025-01-01T00:15:00Z", open: 100, high: 102, low: 99, close: 101, volume: 1 }],
    } });
  });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/dashboard.html");
  const panel = page.getByLabel("Deterministic signal panel");
  await expect(panel.getByText("LONG", { exact: true })).toBeVisible();
  await expect(panel.getByText("fixture-strategy-v1", { exact: true })).toBeVisible();
  for (const period of ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d", "1w"]) {
    await page.getByRole("button", { name: period.toUpperCase(), exact: true }).click();
    await expect.poll(() => chartPeriods.includes(period)).toBe(true);
    await expect(panel.locator(".signal-market")).toContainText("15M");
    await expect(panel.getByText("LONG", { exact: true })).toBeVisible();
    await expect(panel.getByText(signalFixture.data_cutoff_at, { exact: true })).toBeVisible();
    await expect(panel.getByText("fixture-strategy-v1", { exact: true })).toBeVisible();
  }
  expect(strategyBodies).toEqual([{ symbol: "BTCUSDT" }]);
  const context = page.locator('[data-mtf-timeframe="1w"]');
  await expect(context).toContainText("CONTEXT ONLY · NO ALIGNMENT / VETO AUTHORITY");
  await expect(context).toContainText("UNAVAILABLE · NOT READY");
  await expect(panel.getByText("TAKE PROFIT", { exact: true })).toHaveCount(1);
  expect(errors).toEqual([]);
});
