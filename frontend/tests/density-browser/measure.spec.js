import { test, expect } from '@playwright/test';
import { writeFileSync } from 'node:fs';
test('complete recorded real render workload and interactions', async ({ page }) => {
  const baseline = process.env.EVIDENCE_BASELINE === '1', phase = baseline ? 'v2-baseline' : 'v3';
  await page.goto('/density.html');
  await page.waitForFunction(() => window.densityProbe && window.evidenceModel);
  const rows = [];
  async function measure(operation, action) {
    await page.evaluate(() => window.startDensityOperation());
    const start = Date.now(); await action();
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const result = await page.evaluate(() => window.densityProbe());
    rows.push({ operation, latencyMs: Date.now() - start, ...result });
    expect(result.overflow).toBe(false); return result;
  }
  await measure('initial recorded load (includes transfer/JSON/validation)', async () => { await page.getByRole('button', { name: 'Load recorded real evidence' }).click(); await expect(page.getByRole('heading', { name: /Recorded real/ })).toBeVisible({ timeout: 180000 }); });
  for (const width of [1440, 390, 320]) for (const period of ['15m', '1h']) {
    await measure(`viewport ${period} ${width}`, async () => { await page.setViewportSize({ width, height: 1100 }); await page.getByRole('button', { name: `Display ${period}`, exact: true }).click(); await page.waitForTimeout(250); });
    await page.screenshot({ path: `../docs/frontend-chart-evidence-v3/${phase}-${period}-${width}.png`, fullPage: true });
  }
  await page.setViewportSize({ width: 1440, height: 1100 }); await page.getByRole('button', { name: 'Display 15m', exact: true }).click();
  const box = await page.locator('.primary-chart').boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await measure('zoom in', async () => { await page.mouse.wheel(0, -1100); await page.waitForTimeout(250); });
  await measure('pan', async () => { await page.mouse.down(); await page.mouse.move(box.x + box.width / 2 + 160, box.y + box.height / 2, { steps: 10 }); await page.mouse.up(); await page.waitForTimeout(250); });
  await measure('layers open', async () => { await page.getByText('Layers & labels', { exact: false }).click(); });
  if (!baseline) await page.getByRole('button', { name: 'Close layers', exact: true }).click();
  await measure('structure presentation switch', async () => { if (baseline) await page.getByRole('button', { name: 'Structure', exact: true }).click(); else await page.getByLabel('Chart view').selectOption('Structure'); });
  if (!baseline) await page.getByLabel('Chart view').selectOption('All Evidence'); else await page.getByRole('button', { name: 'All', exact: true }).click();
  await measure('cluster expand', async () => { const cluster = page.locator('.evidence-marker.cluster, .geometry-cluster').first(); if (await cluster.count()) await cluster.focus(); });
  await measure('inspector open', async () => { await page.getByRole('button', { name: 'Browse all evidence', exact: true }).click(); });
  await expect(page.getByLabel('Evidence details')).toContainText('All chart evidence · 53482');
  await measure('mobile resize', async () => { await page.setViewportSize({ width: 320, height: 844 }); });
  writeFileSync(`../docs/frontend-chart-evidence-v3/${phase}-metrics.json`, JSON.stringify({ source: 'Complete unmodified recorded BTC response; real Lightweight Charts; test-only instrumentation', phase, rows }, null, 2));
});
