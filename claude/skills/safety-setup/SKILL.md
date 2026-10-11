---
name: safety-setup
description: 盤點本專案的架構、使用對象、對外入口、敏感資料與既有檢查，依實際風險與 OWASP ASVS 5.0 產生 .ai-review/config.md（專案專屬的檢查命令、關卡規則、未驗證事項）。每個專案做一次，之後只在架構大改時重做。
argument-hint: "[--refresh 重做盤點但保留第 3 節既有機制與第 6 節未驗證事項]"
---

# /safety-setup：專案安全檢查初始化

你在做的是**盤點與設定**，不是掃描漏洞。產物是 `.ai-review/config.md`。先讀 `.ai-review/kit/security-checklist.md`（對應表）與 `.ai-review/kit/templates/config.md`（範本）。

## 步驟

### 1. 盤點（用工具看，不用猜）

- 架構：語言、框架、進入點、目錄結構（`ls`、讀 README、package.json／pyproject／csproj／requirements）。
- 對外入口：HTTP 路由、CLI 參數、檔案匯入、外掛 API、排程、webhook。每個列一行。
- 使用對象與開放方式：只有自己？團隊？公開？部署在哪？
- 敏感資料：找 `.env*`、`config*`、`secrets*`、資料庫連線、token 讀取點、個資欄位。**只記錄「有沒有、放哪裡」，不要把值印出來或寫進任何檔案。**
- 既有檢查：`.github/workflows/*`、`.pre-commit-config.yaml`、測試目錄與跑法、lint／format 設定、`Makefile`／npm scripts、既有的 hooks。**全部登記到第 3 節，一條都不拿掉。**
- git 狀態：跑 `py -3 .ai-review/kit/kit.py ignore-check --json`（唯讀；檢查 `.gitignore` 有沒有排除金鑰、憑證、AI 對話逐字稿與記憶，並列出「已經被 git 追蹤、但符合清單」的檔）。它只回條目與路徑，不讀檔案內容；你也不要去打開那些檔看內容。IDE 個人設定（`.vscode/`、`.idea/`）不在它的清單裡，另外看一眼 `.gitignore`。

### 2. 判斷專案類型與適用章節

照 `security-checklist.md` 第 1 節判斷 A／B／C／D，再逐章填第 2 節「適用／不適用／為什麼」。不適用要寫理由（例：「無登入功能」），不要留空。

### 3. 決定檢查命令（第 4 節）

原則：**能直接驗證這個專案風險的命令才加**，不為數量加。優先順序：

1. 既有機制原本的跑法（測試、lint、build）— 直接沿用。
2. 秘密掃描：`gitleaks detect --no-banner --redact`（有裝才加；沒裝就在第 6 節記「未安裝 gitleaks」）。一定要加 `--redact`：掃到金鑰時輸出只留遮蔽後的字樣，金鑰原文才不會寫進 `.ai-review/.cache/checks-*.json`、再被貼進會 commit 的交接報告。
3. 依賴漏洞：依語言擇一 `pip-audit`、`npm audit --audit-level=high`、`dotnet list package --vulnerable`、`cargo audit`。
4. 有對外入口才加的：對應的整合測試或 smoke test。

每條先**實際跑一次**確認能跑；跑不了的標 `required: no` 並在第 6 節寫明。第 4 節**至少要有一條**命令，kit 才算「已初始化」（`/review-ready` 會檢查）；真的沒有可跑的，就放秘密掃描一條 `required: no`（沒裝會記 skipped，不會冒充通過）。格式：

```checks
name | command | required
test | pytest -q | yes
audit | pip-audit | no
secrets | gitleaks detect --no-banner --redact | no
```

### 4. 關卡規則（第 5 節）

- 公開服務或處理別人資料：medium 也阻擋。只有自己用的本機工具：只擋 critical／high。
- 寫明目前有沒有遠端保護規則（branch protection、必經 CI）。沒有就寫「無；本地關卡可被略過」。

### 5. 未驗證事項（第 6 節）

盤點時答不出來的、沒工具跑的、需要使用者決定的，全部列進去，附「為什麼還沒驗證」，狀態填 `未解`。

`ignore-check` 的結果照下面寫進第 6 節的表：

- `missing` 裡每一條各寫一列：日期＝今天；事項＝「`.gitignore` 沒排除 `<條目>`（<白話說明>）」；為什麼還沒驗證＝「等使用者決定要不要補」；誰決定可接受＝使用者；狀態＝未解。`ignore-check` 判 `partial`（只排除了一部分）的，事項後面加「（只排除了一部分，例如 <`uncovered_probes` 前兩個> 沒排除）」，建議補的仍是標準那一行。`ignore-check` 狀態是 `local-only` 的（只在這台電腦的排除設定裡）事項後面加「（只在本機排除，別人 clone 下來不受保護）」。
- `tracked` 裡每一條另寫一列：事項＝「已被 git 追蹤、符合 `<條目>` 的檔：<路徑，最多列 5 個，超過寫共幾個>」；為什麼還沒驗證＝「補 .gitignore 對已追蹤檔沒用，要使用者決定怎麼處理」；誰決定＝使用者；狀態＝未解。只寫路徑，不寫內容。
- `accepted`（config.md ```ignore-ok 區塊裡已決定不排除的）不寫。
- `--refresh` 時：同一條目已經有一列（事項含同一個 `<條目>`）就不要重複加；已經補好的舊列不刪，狀態改成「已解 <今天>」。
- 範本第 6 節有 ```ignore-ok 區塊；既有 config.md 沒有這個區塊，`--refresh` 時照範本補上（只加區塊與說明，不動其他內容）。

**不自動改 `.gitignore`**：使用者說要補才補；補之前先把要加的那幾行（`suggested_lines`）原樣給他看，他同意再加。某條在本專案是正常資料（例如 `*.jsonl` 是題庫），使用者說不排除，就在 ```ignore-ok 區塊記一行「條目 | 日期 | 理由」。

### 6. 寫檔與收尾

1. 用範本產生 `.ai-review/config.md`（`{{KIT_VERSION}}` 取 `.ai-review/kit/VERSION`，`{{DATE}}` 取今天）。若已存在且使用者沒說 `--refresh`，**不要覆蓋**：改成列出差異問使用者。`--refresh` 時保留第 3 節與第 6 節既有內容再合併，另外：
   - 整理第 6 節：表格沒有「狀態」欄（舊格式）就補上這一欄；逐列判斷，已經解決的標「已解 YYYY-MM-DD」（日期取證據上的日期，查不到就寫今天並在事項後加「（整理時確認）」），還沒解決或判斷不了的標「未解」。**不刪任何一列。**
   - meta 的 `kit_version` 更新成 `.ai-review/kit/VERSION` 的目前版本。
2. 執行 `py -3 .ai-review/kit/kit.py state` 確認狀態顯示「尚未準備」且初始化完成（要 meta 有填、第 4 節至少一條命令；沒完成它會印原因）。
3. 回報使用者（白話、五句以內）：專案類型、適用幾章、登記了幾個既有機制、加了幾條檢查命令、第 6 節有幾項要他知道。`ignore-check` 有缺漏或已追蹤檔時加一句白話提醒，例如「`.gitignore` 少排除 3 種機密檔（金鑰、憑證、AI 對話紀錄），我沒有動它，要不要補由你決定」。然後列出「你需要決定的事」（例如 medium 要不要阻擋、要不要裝 gitleaks、要不要補 `.gitignore` 的那幾行——附上要加的行、已追蹤的符合檔要不要處理）。

## 不可以

- 不可以為了增加測試數量加沒有斷言的測試。
- 不可以刪除或停用既有檢查。
- 不可以把秘密的值寫進 config.md 或回覆。
- 不可以自己改 `.gitignore`，也不可以自己 `git rm --cached` 已追蹤的檔；使用者同意了才做。
- 不可以宣稱「已完成安全檢查」——這一步只是設定。
