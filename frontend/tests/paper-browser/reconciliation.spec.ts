import { expect, test } from "@playwright/test";

for (const width of [1440, 390, 320]) test(`${width}px recorded HTTP contract nullability in unchanged Paper pages`, async ({ page }) => {
  await page.setViewportSize({ width, height: 950 });
  const errors: string[] = []; const paperRequests: string[] = [];
  page.on("pageerror", error => errors.push(error.message)); page.on("request", request => { if (/\/api\/paper\//.test(request.url())) paperRequests.push(request.url()); });
  await page.goto("/paper-trading"); await page.locator(".fixture-controls summary").click(); await page.getByLabel("Fixture scenario").selectOption("K");
  await expect(page.getByText("No verified strategy attribution")).toBeVisible(); await expect(page.getByText(/Saved backend TestClient contract evidence/)).toBeVisible();
  await expect(page.getByLabel("Account summary").getByRole("heading")).toHaveText("3f512681-9b67-403d-9dfa-5e6f163715ec");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("navigation", { name: "Product navigation" }).getByRole("link", { name: "Journal", exact: true }).click(); await expect(page.locator(".journal-card")).toHaveCount(1);
  await expect(page.getByLabel("Strategy version")).toBeDisabled(); await page.getByRole("link", { name: "Review execution" }).click();
  await expect(page.getByText("Fill history · 4 fills")).toBeVisible(); await expect(page.getByLabel("Setup metadata")).toBeDisabled(); await expect(page.getByText("USER_UPLOAD · NOT_READY")).toBeVisible();
  await expect(page.getByLabel("Trade charts").locator("img")).toHaveCount(0); await expect(page.getByLabel("Trade summary")).toContainText("Position reference unavailable");
  await expect(page.getByLabel("Trade summary")).toContainText("6 USDT"); await expect(page.getByLabel("Trade summary")).toContainText("5.39 USDT");
  await page.getByLabel("Notes", { exact: true }).fill("Review nullable contract without setup."); await page.getByLabel("Tags · comma separated").fill("verified"); await page.getByRole("button", { name: "Save notes & tags" }).click(); await expect(page.getByText(/Review metadata saved/)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `../docs/frontend-paper-contract-reconciliation-v1/trade-detail-${width}-recorded-fixture.png`, fullPage: true });
  await page.getByRole("navigation", { name: "Product navigation" }).getByRole("link", { name: "Analytics", exact: true }).click();
  await expect(page.getByText(/No verified membership list/)).toBeVisible(); await expect(page.getByText(/Strategy analytics unavailable/)).toBeVisible(); await expect(page.locator(".analytics-breakdown").filter({ hasText: "STRATEGY" })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `../docs/frontend-paper-contract-reconciliation-v1/analytics-${width}-recorded-fixture.png`, fullPage: true });
  expect(paperRequests).toEqual([]); expect(errors).toEqual([]);
});
