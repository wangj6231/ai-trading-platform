# Secret / Key Management Contract

現況：Settings使用SecretStr/hide_input_in_errors；opaque auth token以SHA256digest
保存。沒有證據已部署SecretManager/KMS、輪替排程、key版本ring或brokercredentials。
256-bit随机opaque secret不是password，不改成plaintext以方便debug。

| 類型 | current / future owner | lifecycle契約，未部署的要求 |
|---|---|---|
| application/session secret | 尚無consumercookieauth | futureSecretManager供給，分env，短scope，keyversion；managedIdP/server-sessionpolicy已批准，provider未選 |
| Paperopaquecredential | auth DBdigest +一次internalissuance | issue/revoke/expiry已有；raw僅交付一次；audit event不含token/digest |
| cursorHMAC key | optionalSettings；未指定則perapp random32bytes | 多instance必用共享stablekey；未來kid ring+舊cursor有限接受窗口；不把cursor當auth |
| DB credential | deploymentSecretStr | runtime與migrationrole分權，輪替connect/dispose影響先演練，不能記完整URL |
| third-party API key | optionalOpenAI等serverSettings | 初始產品不啟用AIworkflow；leastscope/rotation/撤銷，不能入provenance |
| futurebrokersecret | 尚不存在 | managedKMS/HSM versioned envelope encryption；no plaintextcolumns |
| encryptionkey | managedplatform未選 | wrappedDEK+kid+algorithmversion，KMS leastprivilege，recovery與audit |

未來brokersecret屬可逆秘密，不可用opaquecredentialdigest方式取回，也不能自製crypto。
以平台vetted AEAD封裝：每secretrecord有unique nonce、ciphertext/tag、wrappedDEK、
KMSkey/version與AAD(account/provider/environment/credentialidentity/schema)。
AAD與授權scope一致；調換ciphertext不能跨accountdecrypt。明文只在adapter使用的短期記憶體。
不得承諾Pythonstring可可靠zeroize；應減少複本、限制dump/debug、隔離process權限。
KMSdeny/unavailable failclosed，不能fallbackplaintext；舊key需保留至備份restore窗口結束。
Managed envelope概念參考 [AWS KMS](https://docs.aws.amazon.com/kms/latest/developerguide/concepts.html)，
不是選定AWS部署。

Secrets不得進Git、frontendbundle、Journal、executionprovenance、trace/log/异常context。
環境檔不是managedvault；須在CIartifact與bundle做canary掃描，不印真值。
SecretManager讀取僅workloadidentity授權；不為應用放可管理所有keys的cloudadminsecret。
rotation→dual-version如契約需要→healthcheck→revoke→auditedverification；沒有驗證
keyring前不得直接輪替cursor導致大量失效後宣稱無中斷。
currentopaquecredentialrevoke不改帳戶ownership，也不自動取消合法已提交訂單。

Secretaccess、issue/revoke、faileddecrypt、keyrotation與breakglass另行securityaudit。
Managedexternalidentity與singleprimaryowner已批准，見 [PRODUCT_FOUNDATION_V1](PRODUCT_FOUNDATION_V1.md)。
Actualcloud/IdP、rotationinterval、keycustody是在scopeddeploymenttask預登記的輸入。
Backup另加密，approvedKMS/secretinfrastructure，key不得只在DBhost；恢復runbook與isolateddrill必須。
參考 [OWASP Secrets Management](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)。
