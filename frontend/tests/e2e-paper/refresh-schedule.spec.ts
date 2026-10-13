/** A deferred network boundary pins a fill during the command's read cohort. */
import { test, expect } from "@playwright/test";
import { normalizeHttpOrder } from "../../src/lib/product/http-contract";
import { OwnedPaperStack } from "./owned-stack";

function deferred() { let resolve!: () => void; const promise = new Promise<void>(done => { resolve = done; }); return { promise, resolve }; }

test("a fill during the post-submit read cohort publishes the canonical account", async ({ page }) => {
  const stack = await new OwnedPaperStack().start();
  const held = deferred(), started = deferred(); let armed = false, orderId = "";
  try {
    await page.goto("/paper-trading");
    await expect(page.getByLabel("Account summary")).toContainText("10000 USDT");
    await expect(page.getByRole("button", { name: "Submit paper intent" })).toBeEnabled();
    await page.route("**/api/paper/accounts/*/orders", async route => {
      if (route.request().method() === "POST") {
        const response = await route.fetch();
        orderId = normalizeHttpOrder(await response.json()).orderId;
        armed = true; await route.fulfill({ response });
      } else {
        if (armed) { started.resolve(); await held.promise; }
        await route.continue();
      }
    });
    const account = page.waitForResponse(response => response.url().endsWith(`/accounts/${stack.accountId}`), { timeout: 10_000 });
    await page.getByLabel("Quantity", { exact: true }).fill("1");
    await page.getByRole("button", { name: "Submit paper intent" }).click();
    await started.promise;
    await expect(page.getByRole("button", { name: "Submitting intent…" })).toBeVisible();
    await stack.command("observe", { orderId, price: "100" });
    held.resolve();
    expect((await account).status()).toBe(200);
    await expect(page.getByRole("button", { name: "Submit paper intent" })).toBeEnabled();
    await expect(page.getByLabel("Orders")).toContainText("FILLED");
    await expect(page.getByLabel("Account summary")).toContainText("9999.9 USDT");
  } finally { held.resolve(); await page.unrouteAll({ behavior: "ignoreErrors" }); await stack.stop(); }
});
