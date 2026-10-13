import { type Page } from "@playwright/test";
import { analysisFixture, signalFixture } from "../fixtures/mtf-contract";
import { evaluationFixture } from "../fixtures/evaluation-job";
import type { SymbolCode } from "@/types/trading";
import type { EvaluationJob } from "@/lib/evaluations";

export async function fixtureNetwork(page: Page, decision: "LONG" | "SHORT" | "NO_TRADE" = "LONG", fail = false,
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
