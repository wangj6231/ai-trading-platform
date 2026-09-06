import { expect, test, type Page } from "@playwright/test";
import type { FixtureOptions } from "./fixture";

// Golden quarter-pixel inputs are exactly representable; do not hide border
// inflation behind a pixel-sized tolerance.
const LAYOUT_TOLERANCE = 0.01;
const CHROME_LAYOUT_UNIT = 1 / 64;
const widths = [0, 0.25, 0.5, 1, 1.5, 2, 6];

async function mount(page: Page, options: FixtureOptions) {
  await page.goto("/");
  await page.evaluate((value) => window.chartFixture.mount(value), options);
  // Let the real ResizeObserver and initial chart requestAnimationFrame finish.
  await page.evaluate(() => new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  }));
  await expect(page.locator(".chart-zone")).toHaveCount(1);
}

async function rectangle(page: Page) {
  return page.evaluate(() => {
    const zone = document.querySelector(".chart-zone");
    if (!zone?.parentElement) return null;
    const rect = zone.getBoundingClientRect();
    const layer = zone.parentElement.getBoundingClientRect();
    return { left: rect.left - layer.left, width: rect.width, right: rect.right - layer.left };
  });
}

async function expectEndpoint(page: Page, start: number, end: number) {
  await expect.poll(async () => {
    const rect = await rectangle(page);
    if (!rect) return Number.POSITIVE_INFINITY; // Retry a redraw, never accept missing geometry.
    return Math.max(Math.abs(rect.left - start), Math.abs(rect.width - (end - start)), Math.abs(rect.right - end));
  }).toBeLessThanOrEqual(LAYOUT_TOLERANCE);
}

for (const kind of ["FVG", "IFVG", "ORDER_BLOCK"] as const) {
  for (const width of widths) {
    test(`${kind} terminal width ${width} has exact browser endpoint`, async ({ page }, testInfo) => {
      await mount(page, { start: 100, end: 100 + width, kind });
      const measured = await rectangle(page);
      await testInfo.attach("actual-browser-rectangle", {
        body: JSON.stringify({ kind, requestedWidth: width, ...measured }), contentType: "application/json",
      });
      await expectEndpoint(page, 100, 100 + width);
    });
  }
}

for (const [kind, state] of [
  ["FVG", "INVERTED"], ["FVG", "EXPIRED"], ["IFVG", "FILLED"],
  ["IFVG", "EXPIRED"], ["ORDER_BLOCK", "EXPIRED"],
] as const) {
  test(`${kind} ${state} also uses terminal geometry`, async ({ page }) => {
    await mount(page, { start: 100, end: 100.5, kind, state });
    await expectEndpoint(page, 100, 100.5);
  });
}

test("arbitrary projection stays within measured Chrome layout quantization", async ({ page }, testInfo) => {
  await mount(page, { start: 100.013, end: 100.347 });
  const rect = await rectangle(page);
  expect(rect).not.toBeNull();
  await testInfo.attach("fractional-browser-rectangle", { body: JSON.stringify(rect), contentType: "application/json" });
  // Left and width each have one layout-unit quantization; their sum has two.
  expect(Math.abs(rect!.left - 100.013)).toBeLessThan(CHROME_LAYOUT_UNIT);
  expect(Math.abs(rect!.width - 0.334)).toBeLessThan(CHROME_LAYOUT_UNIT);
  expect(Math.abs(rect!.right - 100.347)).toBeLessThan(2 * CHROME_LAYOUT_UNIT);
});

test("terminal decoration is inset and clipped without layout inflation", async ({ page }) => {
  await mount(page, { start: 100, end: 100.5 });
  const style = await page.locator(".chart-zone").evaluate((z) => {
    const css = getComputedStyle(z);
    return {
      borders: [css.borderLeftWidth, css.borderRightWidth],
      padding: [css.paddingLeft, css.paddingRight],
      minWidth: css.minWidth, overflow: css.overflow, clipPath: css.clipPath,
      shadow: css.boxShadow, outline: css.outlineStyle, transform: css.transform,
    };
  });
  expect(style.borders).toEqual(["0px", "0px"]);
  expect(style.padding).toEqual(["0px", "0px"]);
  expect(style.minWidth).toBe("0px");
  expect(style.overflow).toBe("hidden");
  expect(style.clipPath).toBe("inset(0px)");
  expect(style.shadow).toContain("inset");
  expect(style.outline).toBe("none");
  expect(style.transform).toBe("none");
});

test("live short zone retains extension and its horizontal borders", async ({ page }) => {
  await mount(page, { start: 100, end: 100.5, live: true });
  await expectEndpoint(page, 100, 144.5);
  const borders = await page.locator(".chart-zone").evaluate((z) => {
    const css = getComputedStyle(z);
    return [css.borderLeftWidth, css.borderRightWidth];
  });
  expect(borders).toEqual(["1px", "1px"]);
});

test("live clipped projection retains the existing 18px minimum", async ({ page }) => {
  await mount(page, { start: 100, end: 50, live: true });
  await expectEndpoint(page, 100, 118);
});

test("future candles cannot extend the trusted terminal timestamp", async ({ page }) => {
  await mount(page, { start: 100, end: 100.5 });
  await page.evaluate(() => window.chartFixture.appendFuture());
  await expectEndpoint(page, 100, 100.5);
});

test("pan reprojects the terminal endpoint", async ({ page }) => {
  await mount(page, { start: 100, end: 100.5 });
  await page.evaluate(() => window.chartFixture.pan(200, 201));
  await expectEndpoint(page, 200, 201);
});

test("real ResizeObserver reprojects the terminal endpoint", async ({ page }) => {
  await mount(page, { start: 100, end: 100.5 });
  const count = await page.evaluate(() => window.chartFixture.resizeCount());
  await page.evaluate(() => window.chartFixture.resize(200, 201));
  await expect.poll(() => page.evaluate(() => window.chartFixture.resizeCount())).toBeGreaterThan(count);
  await expectEndpoint(page, 200, 201);
});

for (const width of [0, 0.5, 6, 60]) {
  test(`terminal width ${width} paints nothing past its endpoint`, async ({ page }, testInfo) => {
    await mount(page, { start: 100, end: 100 + width });
    const zone = page.locator(".chart-zone");
    const clip = await zone.evaluate((z, end) => {
      const layer = z.parentElement!.getBoundingClientRect();
      const rect = z.getBoundingClientRect();
      // Compare device pixels entirely to the right, excluding the device pixel
      // containing a fractional endpoint (legitimate edge antialiasing).
      const x = Math.ceil((layer.left + end) * devicePixelRatio) / devicePixelRatio;
      return { x, y: rect.top - 4, width: 140, height: rect.height + 24 };
    }, 100 + width);
    const painted = await page.screenshot({ clip, animations: "disabled", scale: "device" });
    await zone.evaluate((z) => { (z as HTMLElement).style.visibility = "hidden"; });
    const hidden = await page.screenshot({ clip, animations: "disabled", scale: "device" });
    if (!painted.equals(hidden)) {
      await testInfo.attach("visible-zone-crop", { body: painted, contentType: "image/png" });
      await testInfo.attach("hidden-zone-crop", { body: hidden, contentType: "image/png" });
    }
    expect(painted.equals(hidden), "terminal decoration must not paint beyond trusted end").toBe(true);
  });
}
