import { expect, test, type Page } from "@playwright/test";
import { writeFileSync } from "node:fs";

async function mount(page: Page, period = "15m", width = 1440) {
  await page.setViewportSize({ width, height: 1100 });
  await page.goto("/evidence.html");
  await expect(page.locator('.evidence-marker').first()).toBeVisible();
  await page.getByRole("button", { name: `Display ${period}`, exact: true }).click();
}
async function textIsReadable(page: Page) {
  const result = await page.locator('.evidence-marker[data-text-visible="true"]').evaluateAll((nodes) => {
    const boxes = nodes.map((node) => node.getBoundingClientRect());
    return { count: boxes.length, collisions: boxes.some((box, index) => boxes.slice(index + 1).some((other) => box.left < other.right && box.right > other.left && box.top < other.bottom && box.bottom > other.top)) };
  });
  expect(result.collisions).toBe(false);
  expect(result.count).toBeLessThan(100);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
}

for (const period of ["15m", "1h"]) for (const width of [1440, 390]) {
  test(`Clean View ${period} at ${width}px keeps counts, readable labels and highest trade weight`, async ({ page }) => {
    await mount(page, period, width);
    await expect(page.locator('[data-marker-layer="swing"][data-text-visible="true"]')).toHaveCount(0);
    await expect(page.locator('.chart-zone.fvg[data-label], .chart-zone.order-block[data-label]')).toHaveCount(0);
    await page.getByText("Layers & labels", { exact: false }).click();
    await expect(page.locator('[data-evidence-count="swing"]')).toHaveText("900");
    await expect(page.locator('[data-evidence-count="bos"]')).toHaveText("300");
    await expect(page.locator('[data-evidence-count="fvg"]')).toHaveText("40");
    await expect(page.locator('[data-evidence-count="entry"]')).toHaveText("1");
    for (const layer of ["entry", "tp", "sl"]) {
      const zone = page.locator(`.chart-zone.${layer}`);
      await expect(zone).toHaveCount(1);
      expect(await zone.evaluate((node) => getComputedStyle(node).zIndex)).toBe("30");
      await expect(zone).toHaveAttribute("data-label", layer.toUpperCase());
    }
    await textIsReadable(page);
    await page.screenshot({ path: `../docs/frontend-chart-evidence-v2/clean-${period}-${width}-fixture.png`, fullPage: true });
  });
}

test("focus and independent switches preserve all counts; Reset View restores clean display", async ({ page }) => {
  await mount(page);
  await page.getByText("Layers & labels", { exact: false }).click();
  await page.getByLabel("Swing H/L layer", { exact: true }).uncheck();
  await expect(page.locator('[data-marker-layer="swing"]')).toHaveCount(0);
  await expect(page.locator('[data-marker-layer="bos"]').first()).toBeVisible();
  await page.getByLabel("BOS layer", { exact: true }).uncheck();
  await expect(page.locator('[data-marker-layer="bos"]')).toHaveCount(0);
  await expect(page.locator('[data-marker-layer="mss"]').first()).toBeVisible();
  await page.getByRole("button", { name: "Structure", exact: true }).click();
  await expect(page.locator('.chart-zone.fvg, .chart-zone.support')).toHaveCount(0);
  await page.getByRole("button", { name: "Liquidity", exact: true }).click();
  await expect(page.locator('[data-marker-layer="mss"]')).toHaveCount(0);
  await expect(page.locator('.chart-zone.support')).toHaveCount(1);
  await page.getByRole("button", { name: "Zones", exact: true }).click();
  await expect(page.locator('.chart-zone.fvg')).toHaveCount(40);
  await expect(page.locator('.evidence-marker')).toHaveCount(0);
  await page.getByRole("button", { name: "Trade", exact: true }).click();
  await expect(page.locator('.chart-zone')).toHaveCount(3);
  await expect(page.locator('[data-evidence-count="swing"]')).toHaveText("900");
  await page.getByRole("button", { name: "Reset View", exact: true }).click();
  await expect(page.getByRole("button", { name: "All", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByLabel("Swing H/L layer", { exact: true })).toBeChecked();
  await expect(page.getByLabel("Swing H/L labels", { exact: true })).not.toBeChecked();
  await expect(page.locator('[data-marker-layer="bos"]').first()).toBeVisible();
});

test("cluster expansion, hidden/unprojectable evidence and every page remain reachable", async ({ page }) => {
  await mount(page);
  const cluster = page.locator('.evidence-marker.cluster').first();
  const count = await cluster.getAttribute("data-evidence-members");
  const target = (await cluster.boundingBox())!;
  await page.mouse.click(target.x + 6, target.y + 6);
  const inspector = page.getByLabel("Evidence details");
  await expect(inspector).toContainText(`Selected evidence · ${count}`);
  let seen = 0;
  do {
    seen += await inspector.locator('.evidence-records > details').count();
    const next = inspector.getByRole("button", { name: "Next evidence", exact: true });
    if (!(await next.isEnabled())) break;
    await next.click();
  } while (seen < 2000);
  expect(seen).toBe(Number(count));
  await page.getByRole("button", { name: "Display 1h", exact: true }).click();
  await page.getByRole("button", { name: "Browse all evidence", exact: true }).click();
  await expect(inspector).toContainText("All chart evidence · 1585");
  await inspector.getByLabel("Evidence detail layer").selectOption("swing");
  await inspector.getByLabel("Find evidence ID").fill("original-swing-899");
  await expect(inspector.locator('.evidence-records > details')).toHaveCount(1);
  await inspector.locator('.evidence-records > details > summary').click();
  await inspector.getByText("confirmedAt", { exact: true }).click();
  await expect(inspector).toContainText("2025-01-05T16:45:00.000Z");
});

test("real zoom/pan recalculates label density without resetting the view or blocking gestures", async ({ page }) => {
  await mount(page);
  await page.getByText("Layers & labels", { exact: false }).click();
  await page.getByLabel("Swing H/L labels", { exact: true }).check();
  const chart = page.locator('.primary-chart');
  const bounds = (await chart.boundingBox())!;
  const initialPositions = await page.locator('.evidence-marker').evaluateAll((nodes) => nodes.map((node) => (node as HTMLElement).style.left).join(","));
  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
  await page.mouse.wheel(0, -1100);
  await page.waitForTimeout(250);
  await textIsReadable(page);
  const zoomed = await page.locator('.evidence-marker').count();
  expect(await page.locator('.evidence-marker').evaluateAll((nodes) => nodes.map((node) => (node as HTMLElement).style.left).join(","))).not.toBe(initialPositions);
  await page.getByLabel("FVG labels", { exact: true }).check();
  expect(await page.locator('.evidence-marker').count()).toBe(zoomed);
  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
  const beforePan = await page.locator('.evidence-marker').evaluateAll((nodes) => nodes.map((node) => (node as HTMLElement).style.left).join(","));
  await page.mouse.down(); await page.mouse.move(bounds.x + bounds.width / 2 + 180, bounds.y + bounds.height / 2, { steps: 15 }); await page.mouse.up();
  await page.waitForTimeout(250); await textIsReadable(page);
  expect(await page.locator('.evidence-marker').evaluateAll((nodes) => nodes.map((node) => (node as HTMLElement).style.left).join(","))).not.toBe(beforePan);
  await page.mouse.wheel(0, 1800); await page.waitForTimeout(250); await textIsReadable(page);
  await page.getByRole("button", { name: "Reset View", exact: true }).click();
  await expect(page.getByLabel("Swing H/L labels", { exact: true })).not.toBeChecked();
  await page.setViewportSize({ width: 320, height: 844 });
  await textIsReadable(page);
  await page.screenshot({ path: "../docs/frontend-chart-evidence-v2/zoom-reset-mobile-fixture.png", fullPage: true });
});

test("recorded complete real Binance evidence remains readable at 15m/1h desktop/mobile", async ({ page }) => {
  test.setTimeout(240_000);
  await mount(page);
  await page.getByRole("button", { name: "Load recorded real evidence" }).click();
  await expect(page.getByRole("heading", { name: /Recorded real Binance/ })).toBeVisible({ timeout: 120_000 });
  await page.getByText("Layers & labels", { exact: false }).click();
  await expect(page.locator('[data-evidence-count="swing"]')).toHaveText("15781");
  await expect(page.locator('[data-evidence-count="support"]')).toHaveText("7630");
  const rows = [];
  for (const width of [1440, 390]) for (const period of ["15m", "1h"]) {
    await page.setViewportSize({ width, height: 1100 });
    await page.getByRole("button", { name: `Display ${period}`, exact: true }).click();
    await page.waitForTimeout(500);
    await textIsReadable(page);
    rows.push({ width, period, text_labels: await page.locator('[data-text-visible="true"]').count(), marker_groups: await page.locator('.evidence-marker').count() });
    await page.screenshot({ path: `../docs/frontend-chart-evidence-v2/recorded-real-btc-${period}-${width}.png`, fullPage: true });
  }
  await page.getByRole("button", { name: "Browse all evidence" }).click();
  await page.getByText(/Complete original API evidence/).click();
  await page.getByText("evaluation", { exact: true }).click();
  await page.getByText("market_structure_snapshot", { exact: true }).click();
  await expect(page.getByLabel("Evidence details")).toContainText("15m");
  writeFileSync("../docs/frontend-chart-evidence-v2/recorded-real-browser.json", JSON.stringify({ source: "Unmodified recorded real backend API response + cache candles; presentation replay, no new backend evaluation", status: "PASS", rows }, null, 2));
});
