"""Close current verification sections while retaining the historical loop ledger."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "experiments/backend_evaluation_performance_v1"
browser = json.loads((OUT / "async_live_browser.json").read_text())
assert browser["status"] == "PASS" and not browser["errors"]
times = " / ".join(f'{row["completed_ui_s"]:.3f}' for row in browser["rows"])
gap = max(row["maximum_main_thread_timer_gap_ms"] for row in browser["rows"])
live = (f"Final current-build real Next/default-proxy BTC/ETH UI PASS in {times} s; "
        f"all requests successful and new evaluation routes no-store. Maximum browser main-thread "
        f"timer gap {gap} ms. Desktop-to-mobile chart/header bounds PASS.")

def update(name, changes):
    path = ROOT / name
    text = path.read_text(encoding="utf-8")
    for before, after in changes:
        assert before in text, (name, before)
        text = text.replace(before, after)
    path.write_text(text, encoding="utf-8")

update("ASYNC_EVALUATION_V1_REPORT.md", [
    ("Status: full current non-PostgreSQL regression and deterministic equivalence PASS. Final CI coverage and final live proxy/header retest are in progress. No production-ready claim.",
     "Status: READY_FOR_LIVE_FRONTEND_RETEST. Current non-PostgreSQL regression, CI coverage, complete deterministic equivalence, concurrent API and final real frontend gates PASS. PostgreSQL NOT RUN; no production-ready claim."),
    ("| Backend CI coverage >=90% | RUNNING; no PASS claim yet |", "| Backend CI coverage >=90% | PASS: 91.06%; full coverage run 1183 PASS again, 1781.44 s |"),
    ("| Vitest / coverage | 136 PASS; final coverage values in console evidence |", "| Vitest / coverage | 137 PASS, 13 files; statements/lines 90.40%, branches 83.24%, functions 87.50% |"),
    ("| Production-page fixture browser | 7 PASS, including pending/running/cancel/failed and responsive layouts |", "| Production-page fixture browser | 8 PASS, including pending/running/cancel/failed, responsive resizing and completion across a closed bucket |"),
    ("| Real Next + real Binance | First complete BTC/ETH pass; final header retest pending after a real candles timeout during concurrent coverage |", f"| Real Next + real Binance | PASS, one real BTC/ETH test; {times} s to formal UI; original 10 s proxy, no-store and mobile bounds verified |"),
    ("Final independent live retest is pending; the failure is not erased or hidden by retries/timeouts.", live + " The earlier failure is retained; it is not erased by retries or enlarged timeouts."),
    ("The UI shows unavailable/not-ready rather than inventing MTF state, eligibility, confluence or confidence.", "The UI explicitly shows MTF evidence NOT RETURNED and readiness UNKNOWN for missing snapshots. It does not invent unavailable/not-ready state, eligibility, confluence or confidence."),
    ("a final real mobile capture is pending.", "the final real mobile capture is `async-live-ethusdt-mobile-completed.png`. `mobile-resize-completed-fixture.png` additionally records desktop-to-mobile resizing with complete chart axes/header bounds."),
    ("Completed large output still incurs browser parsing/rendering work.", "Completed large output still incurs browser parsing/rendering work. Completion refreshes wall time immediately: a result crossing the next closed 15m bucket is marked stale while preserving its formal backend decision and removing stale trade overlays. A scoped grid sizing fix keeps chart axes and headers inside the mobile viewport even after desktop completion."),
])
update("BACKEND_EVALUATION_PERFORMANCE_V1_REPORT.md", [
    ("Final CI coverage and live default-proxy/header retest are in progress.", "CI coverage 91.06% and final real default-proxy/header/mobile gate PASS. Classification: READY_FOR_LIVE_FRONTEND_RETEST."),
    ("Current CI coverage >=90% run is in progress, not claimed passed yet.", "Current CI coverage gate PASS at 91.06%; full coverage run 1183 PASS again in 1781.44 s."),
    ("Frontend: 136 Vitest/coverage PASS; typecheck, ESLint and build PASS; 76 existing browser tests and 7 actual-page fixture cases PASS.", "Frontend: 137 Vitest/coverage PASS (90.40% statements/lines, 83.24% branches, 87.50% functions); typecheck, ESLint and build PASS; 76 existing browser tests and 8 actual-page fixture cases PASS."),
    ("final independent proxy/header retest pending.", live),
    ("a measured approximately 1.1 s browser main-thread gap", f"a final measured {gap / 1000:.3f} s browser main-thread gap"),
    ("Verification is still in progress for the final coverage/header/live gate. The synchronous baseline remains `PERFORMANCE_STILL_INSUFFICIENT`; the accepted additive async product flow has passed full equivalence, current regression and initial real concurrency/browser gates. Final classification will be updated after final checks.", "`READY_FOR_LIVE_FRONTEND_RETEST` for the accepted additive asynchronous V1: full equivalence, regression/coverage, concurrent API and final actual frontend gates PASS. The preserved synchronous baseline remains `PERFORMANCE_STILL_INSUFFICIENT`; async acknowledgement does not establish faster computation."),
    ("First real current Next/default-proxy BTC/ETH UI PASS; later candles timeout preserved during concurrent coverage, final independent header/live retest pending. CI coverage is running;", live + " Earlier candles timeout during concurrent coverage remains recorded. CI coverage PASS at 91.06%;"),
    ("Earlier real browser UI complete 21.776 / 29.936 s.", "Earlier real browser UI complete 21.776 / 29.936 s. " + live),
    ("Retain the authorized additive V1. Continue final coverage and independent default-proxy/live verification.", "Retain the authorized additive V1: all available final gates PASS, PostgreSQL explicitly NOT RUN. Stop after the dashboard/evaluation slice. Late scoped frontend fixes cover unknown missing MTF evidence, mobile grid sizing and immediate completed-result freshness; all final frontend checks pass."),
])
update("BACKEND_INTERACTIVE_EVALUATION_DECISION.md", [
    ("Final coverage and independent live/header gate are in progress.", "Final coverage 91.06% and independent live/header/mobile gate PASS. READY_FOR_LIVE_FRONTEND_RETEST; PostgreSQL remains NOT RUN."),
])
update("FRONTEND_PRODUCT_V1_REPORT.md", [
    ("前端為 136 Vitest PASS、typecheck / ESLint / build PASS、既有 76 browser PASS、新增 7 production-page fixture PASS。首次真實 Next／Binance BTC／ETH 端到端通過；最後 no-store header 重測期間發生一次真實 candles timeout，畫面保持 unavailable，完整覆蓋率與獨立 live 重測尚在執行。", f"後端完整 coverage 回歸再次 1183 PASS，覆蓋率 91.06%。前端為 137 Vitest PASS、typecheck / ESLint / build PASS、既有 76 browser PASS、新增 8 production-page fixture PASS。最終真實 Next／Binance BTC／ETH 端到端通過，完成正式畫面約 {times} 秒；原本 10 秒代理、no-store header、桌面切換手機的完整圖表邊界皆通過。先前並行 coverage 時的 candles timeout 保留紀錄；畫面顯示技術錯誤，未偽裝成 NO_TRADE。"),
    ("仍顯示未提供／not-ready；不自行計算。", "明確顯示 evidence 未回傳、readiness unknown；不捏造 unavailable／not-ready 或自行計算。"),
    ("真實畫面已檢視，能看到大量證據標籤互相重疊；", "新增真實手機完成截圖 `async-live-ethusdt-mobile-completed.png`。已修正桌面完成後切換手機時的圖表裁切，並驗證跨過下一個收盤 bucket 的完成結果立即標示 stale。真實畫面已檢視，能看到大量證據標籤互相重疊；"),
])
print(json.dumps({"reports_updated": 4, "final_ui_seconds": times, "maximum_browser_gap_ms": gap}))
