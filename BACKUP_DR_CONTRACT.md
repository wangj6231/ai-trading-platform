# Backup / Disaster Recovery Contract

## Evidence status

只有Composepostgresnamedvolume及isolatedmigration/recoverytests證據。
沒有真basebackup/WALarchive/PITR、offsitecopy、KMSkeyrestore或restoredrill。
migrationdowngrade/reupgrade、workerrestart、backupfile存在皆不等於災難恢復。
Owner已核准 [PRODUCT_FOUNDATION_V1 D4](PRODUCT_FOUNDATION_V1.md)：Financial/Auth PG
RPO≤5minutes、RTO≤60minutes。是待驗證目標，不是上述測試已達標。
單一approvedjurisdiction；實際region/tool/KMS仍是deployment輸入。

## Required recoverable set

PG：accounts/orders/fills/trades/marks、Journalreferences/metadata/attachments、
authsubjects/digests/ownership、observations/deliverycheckpoints、signals/snapshots及
versionreferences。未來projection/jobs/securityaudit若部署需一併界定恢復策略。
objectreceipts與binaryobjects需一致manifest；cursor/DB/KMS版本與recoverycredentials
在SecretManager受控backup。舊decryptkey壽命至少coverapprovedbackup窗口。
marketfilecache可丟失rebootstrap，但canonical研究dataset/identity不能被新provider資料替代。

## Backup/PITR設計（未部署）

經核准的basebackups＋continuousWALarchive，encrypted且與runtimecredential隔離，
off-host/immutability與periodicverification，不取得額外批准不得跨legaljurisdiction。
Backup與liveDB分別加密、leastprivilege；KMS/keycustody不能只在DBhost。
Objectstorage支援時versioning/recovery；credential/keyrecoveryrunbook必須。
單純logicaldump不能被稱為continuousPITR。
monitorWALarchivefailure、backupage、retainedWAL/disk、restoretoolversion；沒有備份不能
繼續宣稱RPO達標。參考 [PostgreSQL PITR](https://www.postgresql.org/docs/16/continuous-archiving.html)。

## Isolated restore drill

1. 記錄故障／desiredrestoretime與可用backup/WAL範圍、version、keycustody。
2. 新隔離instance恢復，不覆寫liveDB，不啟動任何worker/providerdispatch。
3. 驗migrationhead、FK/constraints/triggers、NUMERIC/UTC、snapshot/identityhash、
   canonicalfilldedup與順序；Journal/accountreplay與storedprojection完全比較。
4. 交叉驗objectsmanifest/receipt；缺object明列，不造READYimage。
5. 驗digestscope/revoke，防恢復到舊revokedstate重新授權；需要authoritative
   post-restorecredentialrevocation/reissuance方案，由admin批准，不猜測權限。
6. replayworkercheckpointcrashwindows：PGadvisorylock不需恢復；eligibleordercursor
   決定補齊range，financialcommit/checkpoint不同步仍不得重複fee/fill。
7. 外部可觀察sideeffects／futurebrokerfills不能因restoreunknown就重新submit；
   先reconciliation。Paper仍依既有規則，禁用autoorders。
8. 記actualdata-lossbound/time-to-verified-service並比較approvedRPO/RTO；
   owneraccept後才切流量。失敗保留read-only/NOT_READY，不回退假金融state。

corruption先隔離讀寫、保留evidence、恢復或受控canonicalrebuild；不能直接改immutable
ledger或停trigger「修正結果」。cache/projection可重建，不應成為唯一recoverycopy。
runbook與drill是後續工作，不在本階段啟動productionbackup或修改securitystate。

## Approved readiness and cadence

Public commercial activation前至少一次完整isolatedrestorePASS，涵蓋DB啟動、migration一致、
subjects/ownership、ledger、accountprojection reconciliation、Journal可讀、Analytics重建、
workercheckpoint安全與credentials保護；與上列drill各步一致，不只驗database啟動。
可行時每月automated/isolatedrestore validation；launch後每季broaderDRdrill。
Restore失敗必須DR_READY=false；目前沒有完整restoreevidence，不標DR_READY=true。
Backup existence、migrationtest、policyapproval都不能代替DRverification。

## F5 initial retention/recovery frontier (historical)

F5 is `OWNER_DECISION_REQUIRED`: authoritative account closure/deletion, duplicates, reopening, calendar expiry and post-retention product behavior are not yet approved. See `FINANCIAL_RETENTION_LIFECYCLE_CONTRACT.md` and `PRODUCT_FOUNDATION_F5_REPORT.md`.

No canonical financial source or backup/archive was removed, no immutable guard was relaxed, and no restore drill was executed. Derived-state expiration cannot establish rebuildability after its canonical source expires. A future purge manifest must identify the retained/verified recovery sources and explicit unavailable behavior before claiming rebuild or restore safety. Approved RPO/RTO and single-jurisdiction policy remain unchanged; no new DR_READY claim is made.

Subsequent owner decision closes L1–L5 policy questions: expiry creates dry-run candidates only; no F5 financial purge or rebuild-source removal is authorized. At that policy-only point lifecycle implementation awaited test confirmation; subsequent implementation is not deployed recovery evidence. No change to DR_READY or RPO/RTO verification follows from policy approval.

The four lifecycle seams are now TEST_SEAMS_CONFIRMED. Recovery inventory must retain `account_lifecycle_events` together with AuthSubject/ownership and canonical account facts: losing closure evidence must not silently reactivate accounts or reset retention. New migration0015 refuses downgrade when lifecycle evidence exists. No source purge, restore drill or object/archive implementation accompanies this slice; restore/DR readiness remains NOT_VERIFIED.

Current lifecycle slice is PASS after 2,071 backend / 435 real PostgreSQL 16.11 tests; overall F5 PARTIAL_PASS. The migration roundtrip and populated-lifecycle downgrade refusal are verified, not a backup restore drill. DR_READY remains NOT_VERIFIED; no source/object/archive was removed and no RPO/RTO achievement is asserted. Losing lifecycle authority or its table is a technical failure, not an implicit ACTIVE/reopen fallback.
