# ARCH-01 — Verification Matrix

本文件定義 **change area → minimum required tests → freeze-level tests**。
是既有測試與缺口的盤點，不是本次執行全部測試的 pass report；不變更 threshold，
不授權執行 benchmark、P7-C、官方 R1-E 或調參。

## 1. 本次真正驗證了什麼

| 證據 | 結果 / 限制 |
|---|---|
| source/call-site inspection | 已讀 frontend handlers/client/dashboard、FastAPI factory/routes/service、provider boundary、engine hierarchy/seams、runner、AI service、repository/UoW、schemas、identity builders、migration tree、CI/gates |
| 無網路 Python introspection | Hot→Incremental→Optimized→Concrete MRO；同一 inherited evaluate；canonical pipelines=BTC/ETH 1m、targets3m/1m；OpenAPI六個業務 path、securitySchemes 空 |
| 原有 tests inspection | 已找到下表檔案与代表性 assertion；不以存在或名字代替本次 PASS |
| source/config identity | 以 SYSTEM_ARCHITECTURE 的 current dirty build 為基準；不是 Git HEAD clean build |
| ARCH-01 authored-file check | 寫文件前後比較 1,021 個既有可列舉檔案的 SHA-256：changed=0，新增僅五份文件；策略/config/source/build/dataset identity 全部不變 |
| documentation references | 五份文件的本地 Markdown 連結全部存在；61 個具名測試檔案與 14 個具名測試函式全部定位成功；這是引用檢查，不是執行測試 |
| P7-B 執行狀態 | 切換任務時停止尚未完成的 R1/full quality 與 scoped PG 實例；partial progress 不算 PASS，未啟動後续 microbenchmark |
| fresh suites | ARCH-01 **未重跑** backend/PG/frontend/compileall；不沿用舊 count 宣稱 current freeze |

若有人要把此 current build 標為 frozen，必須另以明確授權完成下列關卡並封存同 build
產物。這些文件本身不提供 freeze approval。

## 2. Gate definitions

| Gate | Freeze-level 要求 | 當前工具/證據 |
|---|---|---|
| D：documentation baseline | 五份文件路徑/callable/測試索引正確、互相無矛盾；no authored source/config/test change | ARCH-01 檔案檢查；不推論 runtime pass |
| B：backend quality | full pytest（含真 PG，0 fail/0 unexpected skip）、Ruff、mypy、compileall、coverage≥90% | `scripts/quality-gates.ps1` + 下列額外命令；目前 P7-B full gate 未完成 |
| P：persistence | `-m postgresql` 對獨立 PostgreSQL16 實際執行；SQLite units 也綠；必要 migration upgrade→downgrade→re-upgrade | `test_postgresql_persistence.py`；不可只看 create_all/SQLite |
| U：frontend | TS、ESLint、Vitest coverage、Playwright、production build | `npm run quality` + `npm run build`；coverage現有下限 statement60/branch55/function50/line60，不降低 |
| E：engine equivalence | reference vs selected implementation 全 typed output、prefix/rewind/append/config-variant、完整 retained state；sealed R1 1440+1440且全 report一致；預先聲明 Q1 checkpoint/cap紀錄 | integration P1/P3/P5/P6 tests + 對應 phase harness。CAP/未跑不是 PASS，不可升格 whole-Q1；不自動重跑研究 |
| I：identity/freeze manifest | 同 build 的 Strategy/Config/Source/Build/Dataset/Run identity、input archive、harness與環境 manifest；預期 source變更產生新 hash | core/backtest identity tests；state_hash不替代run identity，Git commit不替代content hash |
| X：cross-boundary contract | backend真DTO經proxy/browser解析、capability/cutoff/deployment routing契約 | 已有部分 fixture-based tests；下方 GAP 列出尚無的 end-to-end coverage |

「minimum」供局部變更的開發回饋，不能替代 freeze gate。含 strategy/engine/runner/
execution/identity/persistence 變更，原 CRITICAL/HIGH 安全測試應跟隨 full B/P 執行。

## 3. Change-area matrix

以下 backend test 路徑以 `backend/tests/` 為根；未帶目錄的測試檔名以該目錄下唯一 basename 解析，frontend 另標。測試檔存在不代表本階段已執行。

| Change area / boundary | Minimum required tests（既有） | Freeze-level tests |
|---|---|---|
| Next proxy / B01–B02 | frontend `backend-proxy.test.ts`、`api-safety.test.ts`、`trading-dashboard-race.test.tsx` | U + API integration + X routing/cutoff gaps |
| Signal/analysis HTTP schema / B03,B19 | `integration/test_deterministic_api.py`、`integration/test_api.py`、`unit/test_signal_schema.py`；frontend api-safety/signal-panel | B + U + X；不得單改TS assertion |
| Research cutoff auth / B04 | `integration/test_deterministic_api.py` cutoff/token cases、`unit/test_utc_datetime_contract.py` | B + I；若增加proxy passthrough還要U/X；目前未授權新增 |
| Provider adapter / B05 | `unit/test_binance_provider.py`、`test_market_data_normalization.py`、`test_timeframes.py` | B + canonical/lookahead + API error contracts；不需真OpenAI call |
| Trusted market-data/schedule / B06–B07 | `test_market_data_trust_boundary.py`、`test_market_session_calendar.py`、`test_candle.py`、`test_utc_datetime_contract.py` | B + I + deterministic API + E impacted paths |
| Resampling / B08,B11 | `test_incremental_resampling.py`、`test_multi_timeframe.py`、`test_backtest_canonical_data.py`、`integration/test_optimized_equivalence.py` | B + E + I；三實作都比對closed/boundary/gap cases |
| MACD/ATR | `unit/test_indicators.py`、P3/P5 configuration-variant differential tests | B + E + I；本階段不調參 |
| Swing/BOS/MSS/SR | `test_market_structure.py`、`test_structure_breaks.py`、`test_hot_structure.py` | B + E + snapshot/UTC/lookahead + U若DTO改動 |
| Liquidity/PIT history | `test_liquidity.py`、`test_hot_liquidity.py`、`test_order_blocks.py` | B + E + snapshot tests；尤其prefix/full-history cutoff equality |
| FVG/IFVG/OB lifecycle | `test_fvg.py`、`test_hot_fvg.py`、`test_order_blocks.py`、`test_hot_order_blocks.py` | B + E + snapshot + U terminal-zone geometry/lifecycle browser cases |
| Displacement/link projection | `test_displacement.py`、`test_hot_displacement.py`、`test_displacement_link_projection.py` | B + E + I；P7-B目前未完成，不因unit綠就freeze |
| ICT owned/delta | `test_high_probability_entry.py`、`integration/test_p5_hot_state_equivalence.py`、`test_p6_ict_delta.py` | B + E + I；include reference fallback modes、完整state/cache |
| MTF/score/risk/targets | `test_multi_timeframe.py`、`test_signal_score.py`、`test_risk_engine.py`、`test_risk_target_contract.py`、`test_strategy_engine_orchestration.py` | B + E + I + X schema；missing/veto不得upgrade |
| CRT optional module | `unit/test_crt.py`、`test_crt_signal_integration.py` | B + E impacted config + I；不可推論Concrete已呼叫detector |
| Coordinator/Protocol / B08–B12 | `integration/test_strategy_engine_orchestration.py`、P3/P5/P6 equivalence、`unit/test_backtest_lookahead.py` | B + E + I + X；candidate及invalidation需要獨立端到端證据 |
| Runner/canonical source / B11–B12 | `test_backtest_runner.py`、`test_backtest_canonical_data.py`、`test_backtest_lookahead.py`、`test_backtest_reproducibility.py` | B + E + I；所有runner wrapper完整report一致 |
| Entry/exit execution/lifecycle / B13 | `test_entry_execution_policy.py`、`test_execution_policy.py`、`test_signal_lifecycle.py` | B + P + E + I；opening gap/same-bar ambiguity/actual R不變 |
| Financial reporting | `unit/test_financial_metrics.py`、`test_backtest_runner.py`、`test_signal_persistence.py` | B + P + E report comparison；legacy/net denominator不混 |
| AI secondary validation / B15 | `unit/test_openai_validation.py`、`test_signal_persistence.py`、frontend `api-safety.test.ts`、`signal-panel.test.tsx` | B + P + U若契約受影響 + I unchanged response-content isolation；只mock API |
| Snapshot V2 / B14 | `test_snapshot_integrity_v2.py`、`test_signal_persistence.py`、`test_strategy_identity.py` | B + P + E candidate snapshot equality；model_construct/deep-metadata regressions |
| Repository/UoW / B16 | `test_signal_persistence.py`、`test_database_transactions.py`、`test_database.py` | B + P；final-commit failure、rollback、read-only、locked terminal replay |
| ORM/PG/migrations / B17 | `integration/test_postgresql_persistence.py` 全套及SQLite persistence units | B + P + migration cycle；JSONB/UTC/Core/raw SQL/ORM/concurrency皆需實際PG |
| Identity/config/build manifest / B18 | `test_algorithm_identity.py`、`test_strategy_identity.py`、`test_backtest_reproducibility.py`、snapshot tests | B + P + E + I；不能靠只排除變更檔來讓hash一致 |
| Chart ViewModels/lifecycle / B19 | frontend `api-safety.test.ts`、`chart-lifecycle.test.ts`、`price-chart-geometry.test.tsx`、browser `terminal-layout.spec.ts` | U + backend schema/snapshot regressions if contract changes |
| Dashboard race/error rendering | frontend `trading-dashboard-race.test.tsx`、`signal-panel.test.tsx`、`backend-proxy.test.ts` | U + X；stale response不等於same-cutoff association已驗證 |
| Deployment Settings / health | `unit/test_config.py`、`test_deployment_security.py`、`integration/test_api.py` | B + P + U build + X deployment smoke；不推論外部auth/TLS/backup已驗證 |

## 4. 代表性 hard-safety tests（已定位、非本次新 PASS）

- `test_p3_matches_reference_at_every_transition_fixture_prefix`、
  `test_p3_prefix_replay_is_invariant_to_later_candles`、
  `test_p3_runner_uses_shared_lifecycle_and_execution`；P5 wrapper 使用 HotState class 重跑這些契約。
- `test_owned_adapter_matches_full_boundary_and_complete_diagnostic_state`、
  `test_external_caller_cannot_supply_a_trusted_flag`（P6）。
- `test_application_service_cannot_return_success_when_final_commit_fails`
  （unit transaction）、`test_final_deferred_commit_failure_rolls_back_and_cannot_report_success`（PG）。
- `test_row_lock_serializes_conflicting_terminal_updates`、
  `test_select_for_update_lock_releases_after_transaction_rollback`（PG）。
- `test_database_rejects_direct_terminal_take_profit_rewrite`、
  `test_database_rejects_terminal_execution_evidence_via_orm_and_raw_sql`、
  `test_safe_v2_metadata_persists_and_remains_immutable_in_postgresql`（PG）。
- `test_postgresql_ai_provenance_is_immutable`、
  `test_new_migration_downgrades_and_reupgrades_without_hash_changes`（PG）。
- frontend assertions：reject malformed payload/unknown provenance/modified geometry；
  ignores stale signal after selection change；current timeout stays technical error；
  terminal zone end remains fixed while new candles arrive。

## 5. GRILL coverage gaps（要求證明，不假裝已存在測試）

| Finding | 最少仍缺的 assertion / scope | 現有測試為何不足 |
|---|---|---|
| ARCH-F01 | 三個 endpoint 在跨分鐘回覆不同cutoff時，UI不得表示同一analysis snapshot | race tests辨識selection/abort，不聯結same-selection跨回覆provenance |
| ARCH-F02 | UI預設/selector capability 對 canonical pipeline 的部署契約 | component/API通常各用fixtures與test config，不讀同一部署capability |
| ARCH-F03 | 非預設 API_V1_PREFIX + Next route + healthcheck | individual proxy timeout/API tests不是Compose routing整合 |
| ARCH-F04 | provider重試+CPU在timeout/abort/多並行請求下的行為 | mock provider/engine功能測試不測實際event-loop阻塞與資源預算 |
| ARCH-F05 | 先要明確選定要接線的workflow，再有live→AI/persist或report→DB端到端測試 | 現在根本沒有此public caller；不能寫成只是少一個test |
| ARCH-F06 | 所有受支援gap/session/config組合跨三種aggregation輸出契約 | 已有差分只證明覆蓋到的組合；不能直接當通用等價證明 |
| ARCH-F07 | real coordinator 首次送出已發出candidate的structural invalidation，runner確實取消WAITING | lifecycle/fake-engine tests只證明consumer，非real producer |
| ARCH-F08 | 若未來引入並行，需owner隔離/重入/多symbol測試；當前P7-B完整E/B/P關卡 | private-state unit tests與未完成run都不等於並行服務ready |
| ARCH-F09 | deployed backend DTO→Next→browser以及DB field/serializer同步的contract fixture | 多層手寫schema各自綠，仍可能跨層漂移 |

不新增上述功能或測試、不調整風險參數來讓測試通過。下一步是否修正由使用者另行決定。

## 6. 現有命令與 isolation 限制

Root：`scripts/quality-gates.ps1` 會執行 backend Ruff/mypy/full pytest coverage，
再執行 frontend `npm run quality`。它**不含** production build、compileall、
R1/Q1 differential 或自動啟動 PG，也不自行拒絕所有 PG skip。

Backend（cwd=`backend/`）：

```powershell
.\.venv\Scripts\python.exe -m pytest --cov=app --cov-report=term-missing
.\.venv\Scripts\python.exe -m pytest -m postgresql -q
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m mypy app
.\.venv\Scripts\python.exe -m compileall -q app tests
```

Frontend（cwd=`frontend/`）：`npm run quality`、`npm run build`。
CI workflow 提供 PostgreSQL16 service 並執行 frontend build；這是 workflow 定義，
不表示此 dirty worktree 已在 CI 完成。

PostgreSQL 只能用 process-scoped `TEST_POSTGRES_URL` 指向 localhost/127.0.0.1 的
`ai_trading_test`。沒有它時 fixture 會 skip，因此 freeze verifier **必須检查實際
executed count、failed與skipped**，不是只看退出碼。fixture 為 Alembic 暫設並還原
process `DATABASE_URL`；操作人員不得 globally 設 DATABASE_URL 或把測試指向業務DB。
可用 Compose test service 或獨立 native PG，需記錄當次實際版本與乾淨 shutdown。
ARCH-01 沒有再啟動 PostgreSQL，也沒有 migration schema change。

結論：文件 baseline 可驗證；**目前 complete-build freeze readiness 仍 UNVERIFIED**。
