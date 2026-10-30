import { expect, test } from '@playwright/test';
import { readFileSync, writeFileSync } from 'node:fs';
test.skip(process.env.EVIDENCE_BASELINE === '1', 'V3 behavior suite; baseline measures frozen V2 only');
async function frames(page) { await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))); }
async function mount(page, width = 1440, period = '15m', recorded = false) {
  await page.setViewportSize({ width, height: 1100 }); await page.goto('/density.html');
  await expect(page.locator('.evidence-marker').first()).toBeVisible();
  if (recorded) { await page.getByRole('button', { name: 'Load recorded real evidence' }).click(); await expect(page.getByRole('heading', { name: /Recorded real/ })).toBeVisible({ timeout: 180000 }); }
  await page.getByRole('button', { name: `Display ${period}`, exact: true }).click(); await frames(page);
}
async function assertCounts(page) {
  expect(await page.evaluate(() => window.checkDensityIntegrity())).toEqual([]);
  const probe = await page.evaluate(() => window.densityProbe());
  expect(probe.overflow).toBe(false);
  expect(probe.mountedMarkers).toBeLessThanOrEqual(probe.budgets.markerBudget);
  const trade = ['entry','tp','sl'].reduce((sum,layer)=>sum+(probe.layers[layer]?.visuals??0),0);
  expect(probe.mountedZones-trade).toBeLessThanOrEqual(probe.budgets.zoneBudget);
  for (const [layer, count] of Object.entries(probe.layers)) {
    const actual = probe.productionDensity[layer];
    expect(actual.source, `${layer} source`).toBe(count.source);
    expect(actual.viewport, `${layer} viewport`).toBe(count.viewport);
    expect(actual.renderedSource, `${layer} rendered source`).toBe(count.mountedSource);
    expect(actual.visuals, `${layer} visual count`).toBe(count.visuals);
    expect(actual.offscreen, `${layer} offscreen`).toBe(count.offscreen);
    expect(actual.unavailable, `${layer} unprojectable`).toBe(count.unavailable);
    expect(actual.source).toBe(actual.viewport + actual.offscreen + actual.unavailable);
    expect(actual.renderedSource).toBeLessThanOrEqual(actual.viewport);
  }
  const overlap = await page.locator('.evidence-marker[data-text-visible="true"]').evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect()).some((box, index, boxes) => boxes.slice(index + 1).some(other => box.left < other.right && box.right > other.left && box.top < other.bottom && box.bottom > other.top)));
  expect(overlap).toBe(false); return probe;
}
async function inspectAllMembers(page, cluster, screenshot) {
  const ids = (await cluster.getAttribute('data-evidence-keys')).split(',');
  expect(new Set(ids).size).toBe(ids.length); expect(Number(await cluster.getAttribute('data-evidence-members'))).toBe(ids.length);
  await cluster.focus();
  const inspector = page.getByLabel('Evidence details');
  await expect(inspector).toContainText(`Selected evidence · ${ids.length}`);
  await expect(inspector).toContainText('Source ID:'); await expect(inspector).toContainText('Projection: Viewport');
  if (screenshot) await page.screenshot({path:`../docs/frontend-chart-evidence-v3/${screenshot}.png`,fullPage:true});
  const seen = [];
  do {
    seen.push(...await inspector.locator('.evidence-records > details').evaluateAll(nodes => nodes.map(node => node.dataset.evidenceKey)));
    const next = inspector.getByRole('button', { name: 'Next evidence', exact: true }); if (!(await next.isEnabled())) break; await next.click();
  } while (seen.length <= ids.length);
  expect(seen.sort()).toEqual(ids.sort());
  await inspector.getByRole('button', { name: 'Close evidence' }).click();
}
for (const width of [1440, 390, 320]) for (const period of ['15m', '1h']) test(`dense fixture: three presets, counts, trade and mobile controls ${period} ${width}`, async ({ page }) => {
  await mount(page, width, period);
  await expect(page.getByLabel('Chart view')).toHaveValue('Decision');
  await expect(page.locator('.chart-zone.fvg, .chart-zone.order-block, [data-marker-layer="swing"]')).toHaveCount(0);
  for (const preset of ['Decision', 'Structure', 'All Evidence']) {
    await page.getByLabel('Chart view').selectOption(preset); await frames(page); await assertCounts(page);
    for (const trade of ['entry', 'tp', 'sl']) { const zone = page.locator(`.chart-zone.${trade}`); await expect(zone).toHaveCount(1); await expect(zone).toHaveAttribute('data-label', trade.toUpperCase()); expect(await zone.evaluate(node => getComputedStyle(node).zIndex)).toBe('30'); }
    await page.screenshot({ path: `../docs/frontend-chart-evidence-v3/dense-${preset.replace(' ', '-')}-${period}-${width}.png`, fullPage: true });
  }
  const height = await page.locator('.primary-chart').evaluate(node => node.clientHeight);
  await page.getByRole('button', { name: 'Layers & labels', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'Chart layers' })).toBeVisible();
  expect(await page.locator('.primary-chart').evaluate(node => node.clientHeight)).toBe(height);
  await page.getByLabel('BOS layer', { exact: true }).uncheck(); await expect(page.locator('[data-marker-layer="bos"]')).toHaveCount(0);
  await expect(page.locator('[data-evidence-count="support"]')).toHaveText('480');
  await page.screenshot({ path: `../docs/frontend-chart-evidence-v3/dense-layers-${period}-${width}.png`, fullPage: true });
  await page.keyboard.press('Escape'); await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button', { name: 'Reset View', exact: true }).click(); await frames(page);
  await expect(page.getByLabel('Chart view')).toHaveValue('Decision'); await assertCounts(page);
});
test('dense fixture: original SR members, zoom split, virtualization and reset', async ({ page }) => {
  await mount(page);
  await inspectAllMembers(page,page.locator('.evidence-marker.cluster').first(),'dense-marker-cluster');
  await inspectAllMembers(page, page.locator('.chart-zone.support.geometry-cluster').first());
  const initial = await assertCounts(page);
  await page.evaluate(() => window.densityActions.range(420, 480)); await frames(page);
  const zoom = await assertCounts(page); expect(zoom.layers.bos.viewport).toBeLessThan(initial.layers.bos.viewport);
  expect(zoom.layers.support.mountedSource).toBe(initial.layers.support.mountedSource);
  expect(zoom.layers.support.visuals).toBeGreaterThan(initial.layers.support.visuals);
  const mountedSource = await page.locator('.chart-zone.support, .chart-zone.resistance').evaluateAll(nodes => nodes.flatMap(node => node.dataset.evidenceKeys.split(',')));
  expect(new Set(mountedSource).size).toBe(mountedSource.length);
  await page.evaluate(() => window.densityActions.range(650, 700)); await frames(page);
  const far = await assertCounts(page);
  // Native chart clamps scrolling to keep an edge candle; active windows can still intersect it.
  // Historical markers are offscreen, while every remaining zone must intersect the actual range.
  await expect(page.locator('.evidence-marker')).toHaveCount(0);
  expect(far.layers.bos.offscreen).toBeGreaterThan(initial.layers.bos.offscreen);
  await page.getByRole('button', { name: 'Reset View', exact: true }).click(); await frames(page); await assertCounts(page);
  await expect(page.locator('.chart-zone.entry')).toHaveCount(1);
  await page.getByRole('button', { name: 'Browse all evidence', exact: true }).click();
  await expect(page.getByLabel('Evidence details')).toContainText('All chart evidence · 2543');
  await page.getByLabel('Evidence detail layer').selectOption('support'); await page.getByLabel('Find evidence ID').fill('original-support-479');
  await expect(page.locator('.evidence-records > details')).toHaveCount(1); await expect(page.getByLabel('Evidence details')).toContainText('original-support-479');
});
test('recorded real: all presets at both periods/all widths, exact counts and every SR cluster member', async ({ page }) => {
  await mount(page, 1440, '15m', true);
  const originalFingerprint=await page.evaluate(()=>window.densityFingerprint());
  const baseline = JSON.parse(readFileSync('../docs/frontend-chart-evidence-v3/v2-baseline-metrics.json', 'utf8'));
  const results = [];
  for (const width of [1440,390,320]) for (const period of ['15m','1h']) {
    await page.setViewportSize({ width, height: 1100 }); await page.getByRole('button', { name: `Display ${period}`, exact: true }).click();
    for (const preset of ['Decision','Structure','All Evidence']) {
      await page.getByLabel('Chart view').selectOption(preset); await frames(page);
      const probe = await assertCounts(page); expect(Object.values(probe.layers).reduce((sum,count) => sum + count.source,0)).toBe(53482);
      if (preset === 'Decision') { const before = baseline.rows.find(row => row.operation === `viewport ${period} ${width}`); expect(probe.mountedZones + probe.mountedMarkers).toBeLessThan(before.mountedZones + before.mountedMarkers); }
      await page.screenshot({ path: `../docs/frontend-chart-evidence-v3/recorded-${preset.replace(' ', '-')}-${period}-${width}.png`, fullPage: true });
      results.push({ width, period, preset, ...probe });
    }
  }
  await page.setViewportSize({width:1440,height:1100}); await page.getByRole('button',{name:'Display 15m',exact:true}).click(); await page.getByLabel('Chart view').selectOption('Decision'); await frames(page);
  for (const kind of ['support','resistance']) await inspectAllMembers(page, page.locator(`.chart-zone.${kind}.geometry-cluster`).first(),`recorded-${kind}-cluster`);
  const box=await page.locator('.primary-chart').boundingBox(); await page.mouse.move(box.x+box.width/2,box.y+box.height/2);
  await page.mouse.wheel(0,-1100); await page.waitForTimeout(250); await assertCounts(page); await page.screenshot({path:'../docs/frontend-chart-evidence-v3/recorded-zoom-in.png',fullPage:true});
  await page.mouse.down();await page.mouse.move(box.x+box.width/2+180,box.y+box.height/2,{steps:10});await page.mouse.up();await page.waitForTimeout(250);await assertCounts(page);await page.screenshot({path:'../docs/frontend-chart-evidence-v3/recorded-pan.png',fullPage:true});
  await page.mouse.wheel(0,1800);await page.waitForTimeout(250);await assertCounts(page);await page.screenshot({path:'../docs/frontend-chart-evidence-v3/recorded-zoom-out.png',fullPage:true});
  await page.getByRole('button',{name:'Reset View',exact:true}).click();await frames(page);await assertCounts(page);
  expect(await page.evaluate(()=>window.densityFingerprint())).toBe(originalFingerprint);
  await page.setViewportSize({width:320,height:740});await page.getByRole('button',{name:'Layers & labels',exact:true}).click();
  await page.screenshot({path:'../docs/frontend-chart-evidence-v3/recorded-mobile-layers-320.png',fullPage:true});
  await page.keyboard.press('Escape');
  await page.getByRole('button',{name:'Browse all evidence',exact:true}).click();await page.getByText(/Complete original API evidence/).click();await page.getByText('evaluation',{exact:true}).click();await page.getByText('market_structure_snapshot',{exact:true}).click();await expect(page.getByLabel('Evidence details')).toContainText('15m');
  writeFileSync('../docs/frontend-chart-evidence-v3/preset-matrix.json',JSON.stringify({status:'PASS',source:'Complete recorded real; no backend evaluation',results},null,2));
});
test('price-axis dragging updates geometry while moving and after release outside chart',async({page})=>{
  await mount(page);
  const chart=await page.locator('.primary-chart').boundingBox();
  const before=await page.locator('.chart-zone.entry').getAttribute('style');
  await page.mouse.move(chart.x+chart.width-25,chart.y+chart.height/2);await page.mouse.down();
  await page.mouse.move(chart.x+chart.width-25,chart.y+chart.height/2+100,{steps:15});await frames(page);await assertCounts(page);
  expect(await page.locator('.chart-zone.entry').getAttribute('style')).not.toBe(before);
  await page.screenshot({path:'../docs/frontend-chart-evidence-v3/dense-price-axis-drag.png',fullPage:true});
  await page.mouse.move(chart.x+chart.width+5,chart.y+chart.height+15);await page.mouse.up();await frames(page);await assertCounts(page);
  await page.getByRole('button',{name:'Reset View',exact:true}).click();await frames(page);await assertCounts(page);
});
test('partial stale suppression retains current trade selection and original archive counts',async({page})=>{
  await mount(page);await page.getByRole('button',{name:'Simulate stale analysis',exact:true}).click();await frames(page);
  await expect(page.locator('.evidence-marker,.chart-zone.support,.chart-zone.resistance')).toHaveCount(0);
  const trade=page.locator('.chart-zone.entry');await expect(trade).toHaveCount(1);await trade.focus();
  await expect(page.getByLabel('Evidence details')).toContainText('Selected evidence · 1');await expect(page.getByLabel('Evidence details')).toContainText('Projection: Viewport · rendered source member');
  await page.getByRole('button',{name:'Close evidence',exact:true}).click();
  await page.getByRole('button',{name:'Layers & labels',exact:true}).click();await expect(page.locator('[data-density-layer="support"]')).toContainText('480 stale suppressed');await expect(page.locator('[data-density-layer="entry"]')).toContainText('1 rendered source');await page.keyboard.press('Escape');
  await page.getByRole('button',{name:'Simulate stale analysis',exact:true}).click();await page.getByRole('button',{name:'Simulate stale signal',exact:true}).click();await frames(page);
  await expect(page.locator('.chart-zone.entry,.chart-zone.tp,.chart-zone.sl')).toHaveCount(0);
  await page.getByRole('button',{name:'Layers & labels',exact:true}).click();await expect(page.locator('[data-density-layer="entry"]')).toContainText('1 source · 0 viewport · 0 rendered source');await expect(page.locator('[data-density-layer="entry"]')).toContainText('1 stale suppressed');await page.keyboard.press('Escape');
  await page.getByRole('button',{name:'Browse all evidence',exact:true}).click();await page.getByLabel('Evidence detail layer').selectOption('entry');await expect(page.getByLabel('Evidence details')).toContainText('Stale-suppressed archive');
});
