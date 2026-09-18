---
kind: fix
id: {{ID}}
created: {{DATE}}
review: {{REVIEW_ID}}
handoff: {{NEW_HANDOFF_ID}}
kit_version: {{KIT_VERSION}}
---

# 修正報告 {{ID}}（回應 {{REVIEW_ID}}）

## 0. 摘要（給非技術使用者）

- 處理了 N 項：修正 N、不成立 N、延後 N（需要你決定）、資訊不足 N
- 下一步：已重新交接為 {{NEW_HANDOFF_ID}}，請再讓 Codex 審一次（狀態：待複查）

## 1. 逐項處理

### R-xxx-1 ｜ 結果：fixed / disputed / deferred / needs-info
- 處理方式：
- 改動：`path/to/file.ext`（行號）
- 針對性驗證：（命令＋輸出摘要，或重現步驟＋結果）
- 備註：

### R-xxx-Q1 ｜ 結果：
- 回應：

## 2. 需要使用者決定的事項

| 發現 | 建議 | 為什麼要你決定 |
|---|---|---|

## 3. 聲明

本報告為開發 AI 的修正紀錄，狀態為**待複查**，不構成獨立審查通過。
