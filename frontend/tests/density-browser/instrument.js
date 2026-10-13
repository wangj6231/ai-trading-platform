// Test-only measurement of the real library. No coordinate or projection replacement.
import * as native from 'lightweight-charts';
import { evidenceRecords } from '@/lib/chart-evidence';
import { projectSwingMarkers, projectStructureMarkers, projectZoneWindows, levelAvailabilityStart } from '@/lib/chart-view-model';
import { densityCells } from '../../src/lib/chart-density';
export * from 'lightweight-charts';
const state = { chart: null, series: null, nativeMarkers: 0, longestTask: 0, markerUpdateMs: 0, renders: [], operationStart: 0, longTasks: [] };
new PerformanceObserver(list => { for (const entry of list.getEntries()) { state.longestTask = Math.max(state.longestTask, entry.duration); state.longTasks.push({ start: entry.startTime, duration: entry.duration }); } }).observe({ type: 'longtask', buffered: true });
export function measureRender(callback) { return (...args) => { const started = performance.now(); try { return callback(...args); } finally { state.renders.push({ start: started, duration: performance.now() - started }); } }; }
window.startDensityOperation = () => { state.operationStart = performance.now(); };
window.densityActions = { range(from, to) { state.chart.timeScale().setVisibleLogicalRange({ from, to }); }, reset() { state.chart.timeScale().fitContent(); } };
window.densityFingerprint = async () => {
  const { source } = window.evidenceModel;
  const bytes = new TextEncoder().encode(JSON.stringify([source.supports,source.resistances,source.swings,source.structures,source.zones]));
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(value=>value.toString(16).padStart(2,'0')).join('');
};
window.checkDensityIntegrity = () => {
  const {source,signal,candles}=window.evidenceModel, rows=evidenceRecords(source,signal), byKey=new Map(rows.map(row=>[row.key,row]));
  const time=stamp=>Math.floor(Date.parse(stamp)/1000), end=candles.at(-1).timestamp;
  const windows=new Map(projectZoneWindows(source.zones,end).map(window=>[window.zone,window]));
  const errors=[], seen=new Set();
  for(const element of document.querySelectorAll('.chart-zone,.evidence-marker')) {
    const ids=element.dataset.evidenceKeys.split(',');
    if(new Set(ids).size!==ids.length || ids.length!==Number(element.dataset.evidenceMembers)) errors.push('incorrect cluster membership');
    for(const key of ids) if(!byKey.has(key)) errors.push(`foreign source ${key}`);
    if(element.classList.contains('chart-zone')) {
      for(const key of ids) {if(seen.has(key)) errors.push(`duplicated zone ${key}`); seen.add(key);}
      const row=byKey.get(ids[0]), item=row.detail;
      let from,to=time(end),lower,upper,terminal=false;
      if(['support','resistance'].includes(row.layer)) {from=time(levelAvailabilityStart(item));lower=item.lower;upper=item.upper;}
      else if(['fvg','ob'].includes(row.layer)) { const window=windows.get(item);from=time(window.from);to=time(window.to);terminal=window.terminal;lower=item.lower;upper=item.upper; }
      else {from=time(signal.validatedAt);lower=row.layer==='entry'?signal.entryMin:row.layer==='tp'?signal.takeProfit:signal.stopLoss;upper=row.layer==='entry'?signal.entryMax:lower;}
      if(Number(element.dataset.projectionFrom)!==from || Number(element.dataset.projectionTo)!==to || Number(element.dataset.sourceLower)!==lower || Number(element.dataset.sourceUpper)!==upper || element.dataset.terminal!==String(terminal)) errors.push(`rewritten original geometry ${row.key}`);
      if(typeof element.onfocus!=='function') errors.push(`zone not expandable ${row.key}`);
    } else {
      const item=byKey.get(ids[0]).detail, at=element.dataset.representativeAt;
      if(![item.pivotAt,item.confirmedAt].includes(at) || !candles.some(candle=>time(candle.timestamp)===time(at))) errors.push('rewritten marker timestamp');
      if(typeof element.onclick!=='function'||typeof element.onfocus!=='function') errors.push('marker not expandable');
    }
  }
  return errors;
};
export function createChart(...args) {
  const chart = native.createChart(...args); state.chart = chart;
  const add = chart.addSeries.bind(chart);
  chart.addSeries = (...params) => { const series = add(...params); state.series = series; return series; };
  return chart;
}
export function createSeriesMarkers(series, markers, options) {
  const api = native.createSeriesMarkers(series, markers, options); state.nativeMarkers = markers.length;
  const set = api.setMarkers.bind(api);
  api.setMarkers = markers => { const started = performance.now(); state.nativeMarkers = markers.length; set(markers); state.markerUpdateMs = performance.now() - started; };
  return api;
}
window.densityProbe = () => {
  const { source, candles, signal } = window.evidenceModel;
  const chart = state.chart, series = state.series, scale = chart.timeScale();
  const pane = document.querySelector('.chart-canvas').getBoundingClientRect();
  const width = pane.width - chart.priceScale('right').width(), height = pane.height - scale.height();
  const time = stamp => Math.floor(Date.parse(stamp) / 1000);
  const bars = new Map(candles.map(bar => [time(bar.timestamp), bar]));
  const rows = evidenceRecords(source, signal), keys = new Map(rows.map(row => [row.detail, row.key]));
  const relevant = new Set(), projectable = new Set();
  const point = (key, stamp, price) => { const x = scale.timeToCoordinate(time(stamp)), y = series.priceToCoordinate(price); if (x === null || y === null) return; projectable.add(key); if (x >= 0 && x <= width && y >= 0 && y <= height) relevant.add(key); };
  for (const [index, marker] of projectSwingMarkers(source.swings).entries()) { const bar = bars.get(time(marker.at)); if (bar) point(keys.get(source.swings[Math.floor(index / 2)]), marker.at, Number(marker.position === 'aboveBar' ? bar.high : bar.low)); }
  for (const [index, marker] of projectStructureMarkers(source.structures).entries()) { const bar = bars.get(time(marker.at)); if (bar) point(keys.get(source.structures[index]), marker.at, Number(marker.position === 'aboveBar' ? bar.high : bar.low)); }
  const end = candles.at(-1).timestamp;
  const zone = (key, from, to, lower, upper) => { const x1 = scale.timeToCoordinate(time(from)), x2 = scale.timeToCoordinate(time(to)), y1 = series.priceToCoordinate(upper), y2 = series.priceToCoordinate(lower); if ([x1,x2,y1,y2].some(value => value === null)) return; projectable.add(key); if (x2 >= 0 && x1 <= width && x2 >= x1 && Math.max(y1,y2) >= 0 && Math.min(y1,y2) <= height) relevant.add(key); };
  for (const item of [...source.supports, ...source.resistances]) zone(keys.get(item), levelAvailabilityStart(item), end, item.lower, item.upper);
  for (const item of projectZoneWindows(source.zones, end)) zone(keys.get(item.zone), item.from, item.to, item.zone.lower, item.zone.upper);
  if (signal && signal.finalDecision !== 'NO_TRADE' && signal.entryMin !== null && signal.entryMax !== null) {
    for (const row of rows.filter(row => ['entry','tp','sl'].includes(row.layer))) { const lower = row.layer === 'entry' ? signal.entryMin : row.layer === 'tp' ? signal.takeProfit : signal.stopLoss; const upper = row.layer === 'entry' ? signal.entryMax : lower; zone(row.key, signal.validatedAt, end, lower, upper); }
  }
  const mounted = new Set();
  for (const element of document.querySelectorAll('.chart-zone, .evidence-marker')) for (const key of (element.dataset.evidenceKeys ?? element.dataset.evidenceKey ?? '').split(',')) if (key) mounted.add(key);
  const layers = {};
  for (const row of rows) { const count = layers[row.layer] ??= { source: 0, viewport: 0, mountedSource: 0, offscreen: 0, unavailable: 0, visuals: 0 }; count.source++; if (relevant.has(row.key)) count.viewport++; if (mounted.has(row.key)) count.mountedSource++; if (!projectable.has(row.key)) count.unavailable++; else if (!relevant.has(row.key)) count.offscreen++; }
  for (const element of document.querySelectorAll('.chart-zone, .evidence-marker')) { const key = (element.dataset.evidenceKeys ?? element.dataset.evidenceKey ?? '').split(',')[0]; if (key && layers[key.split(':')[0]]) layers[key.split(':')[0]].visuals++; }
  const range=scale.getVisibleLogicalRange();
  return { layers, productionDensity: window.evidenceModel.density, budgets: densityCells(width,height,range.to-range.from), mountedMarkers: document.querySelectorAll('.evidence-marker').length, mountedZones: document.querySelectorAll('.chart-zone').length, clusters: document.querySelectorAll('.cluster, .geometry-cluster').length, nativeMarkers: state.nativeMarkers, longestTaskMs: state.longestTask, operationLongestTaskMs: Math.max(0, ...state.longTasks.filter(task => task.start >= state.operationStart).map(task => task.duration)), renderLatencyMs: Math.max(0, ...state.renders.filter(render => render.start >= state.operationStart).map(render => render.duration)), renderPasses: state.renders.filter(render => render.start >= state.operationStart).length, markerUpdateMs: state.markerUpdateMs, logicalRange: range, overflow: document.documentElement.scrollWidth > innerWidth };
};
