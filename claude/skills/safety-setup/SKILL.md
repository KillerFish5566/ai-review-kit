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
- git 狀態：`.gitignore` 是否涵蓋 `.env`、`*.local.*`、`credentials*`、IDE 個人設定。

### 2. 判斷專案類型與適用章節

照 `security-checklist.md` 第 1 節判斷 A／B／C／D，再逐章填第 2 節「適用／不適用／為什麼」。不適用要寫理由（例：「無登入功能」），不要留空。

### 3. 決定檢查命令（第 4 節）

原則：**能直接驗證這個專案風險的命令才加**，不為數量加。優先順序：

1. 既有機制原本的跑法（測試、lint、build）— 直接沿用。
2. 秘密掃描：`gitleaks detect --no-banner`（有裝才加；沒裝就在第 6 節記「未安裝 gitleaks」）。
3. 依賴漏洞：依語言擇一 `pip-audit`、`npm audit --audit-level=high`、`dotnet list package --vulnerable`、`cargo audit`。
4. 有對外入口才加的：對應的整合測試或 smoke test。

每條先**實際跑一次**確認能跑；跑不了的標 `required: no` 並在第 6 節寫明。格式：

```checks
name | command | required
test | pytest -q | yes
audit | pip-audit | no
```

### 4. 關卡規則（第 5 節）

- 公開服務或處理別人資料：medium 也阻擋。只有自己用的本機工具：只擋 critical／high。
- 寫明目前有沒有遠端保護規則（branch protection、必經 CI）。沒有就寫「無；本地關卡可被略過」。

### 5. 未驗證事項（第 6 節）

盤點時答不出來的、沒工具跑的、需要使用者決定的，全部列進去，附「為什麼還沒驗證」。

### 6. 寫檔與收尾

1. 用範本產生 `.ai-review/config.md`（`{{KIT_VERSION}}` 取 `.ai-review/kit/VERSION`，`{{DATE}}` 取今天）。若已存在且使用者沒說 `--refresh`，**不要覆蓋**：改成列出差異問使用者。`--refresh` 時保留第 3 節與第 6 節既有內容再合併。
2. 執行 `py -3 .ai-review/kit/kit.py state` 確認狀態顯示「尚未準備」且初始化完成。
3. 回報使用者（白話、五句以內）：專案類型、適用幾章、登記了幾個既有機制、加了幾條檢查命令、第 6 節有幾項要他知道。然後列出「你需要決定的事」（例如 medium 要不要阻擋、要不要裝 gitleaks）。

## 不可以

- 不可以為了增加測試數量加沒有斷言的測試。
- 不可以刪除或停用既有檢查。
- 不可以把秘密的值寫進 config.md 或回覆。
- 不可以宣稱「已完成安全檢查」——這一步只是設定。
