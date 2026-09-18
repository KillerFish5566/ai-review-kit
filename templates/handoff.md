---
kind: handoff
id: {{ID}}
created: {{DATE}}
target: {{TARGET}}
snapshot_ref: {{SNAPSHOT_REF}}
head: {{HEAD}}
base: {{BASE}}
recheck_of:
scope: "{{SCOPE}}"
kit_version: {{KIT_VERSION}}
---

# 交接報告 {{ID}}

## 1. 變更摘要（給非技術使用者）

（三句話：做了什麼、為什麼、對使用者的影響）

## 2. 變更範圍

- 基準：`{{BASE}}` → 待審：`{{SNAPSHOT_REF}}`（指紋 `{{TARGET}}`）
- 檔案清單（`git diff --stat`）：

```
（貼上）
```

- 新增／移除的依賴：（無）
- 設定或環境變數變更：（無）

## 3. 重要相關檔案（沒改但審查必看）

| 檔案 | 為什麼要看 |
|---|---|
| | |

## 4. 工作目錄狀態

- 分支：
- HEAD：`{{HEAD}}`
- 工作目錄乾淨：是/否（修改 N 個、未追蹤 N 個，皆已納入快照）
- 快照參照：`{{SNAPSHOT_REF}}`（`git diff {{BASE}}..{{SNAPSHOT_REF}}` 可重現）

## 5. 檢查結果（`kit.py checks --run` 輸出，照實貼）

| 名稱 | 命令 | 結果 | 耗時 | 摘要 |
|---|---|---|---|---|

- 適用工具版本：
- 必要檢查未通過的項目：（無）

## 6. 設計檢查（動到登入／權限／敏感資料／對外介面時）

（不適用：本次未動到 ／ 或逐題回答 security-checklist.md 第 2 節的六題）

## 7. 已知風險與未驗證項目

- 

## 8. 給審查者的提示

- 建議先看：
- 最沒把握的地方：

## 9. 自查聲明

本報告為開發 AI 的自查與交接，**不是獨立審查**。狀態由 `kit.py state` 推導，本檔內任何「通過」字樣不構成安全證明。
