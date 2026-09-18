---
kind: review
id: {{ID}}
created: {{DATE}}
handoff: {{HANDOFF_ID}}
target: {{TARGET}}
reviewer: codex
verdict: needs-fix | no-blocking-found | invalid
blocking: 0
kit_version: {{KIT_VERSION}}
---

# 獨立審查報告 {{ID}}

## 0. 結論（給非技術使用者）

- 結論：（例：本次範圍內未發現阻擋問題 ／ 找到 2 項必須先修的問題）
- 建議：（可以合併 ／ 先不要合併，修完再審一次）
- 下一步：（例：請開發端執行 /review-fix R-xxx）

## 1. 審查範圍與方法

- 交接：{{HANDOFF_ID}}，指紋 `{{TARGET}}`（核對結果：相符／未能核對）
- 讀過的 diff：`git diff <base>..<snapshot_ref>`
- 讀過的完整檔案：
  - 
- 執行過的指令與結果：
  - 
- 沒做的事（限制）：
  - 

## 2. 已確認的問題

### R-xxx-1 ｜ 嚴重程度：critical/high/medium/low
- 位置：`path/to/file.ext:行號`（函式名）
- 觸發條件：
- 影響：
- 證據：
  ```
  （關鍵程式碼幾行或重現步驟）
  ```
- 修正建議：

## 3. 待驗證的疑點（不構成阻擋，但開發端必須回應）

### R-xxx-Q1
- 位置：
- 疑點：
- 要怎麼驗證：

## 4. 對交接內容的核對

- 交接說跑過的檢查是否可信：
- 交接第 7 節的風險是否已在本報告處理：

## 5. 聲明

本報告由獨立審查者產出，未修改任何實作。「本次範圍內未發現阻擋問題」只代表在上述範圍與方法下沒有找到，不代表不存在。
