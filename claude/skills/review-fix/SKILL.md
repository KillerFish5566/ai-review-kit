---
name: review-fix
description: 讀取獨立審查報告（.ai-review/reviews/R-xxx.md），逐項核對、修正並做針對性驗證，對不成立的發現寫出可檢驗的理由，產生修正報告並重新交接，狀態變為「待複查」。不得自行宣告審查通過。
argument-hint: "[R-xxx 審查編號；省略則取最新一份]"
---

# /review-fix：處理獨立審查發現

完整規範：`.ai-review/kit/fix-spec.md`。範本：`.ai-review/kit/templates/fix.md`。

## 步驟

1. **找報告**：`$ARGUMENTS` 有編號就用它；沒有就取 `.ai-review/reviews/` 編號最大的。先 `py -3 .ai-review/kit/kit.py state` 看狀態是不是「需修正」；若是「尚未準備」，代表審查後程式碼已變，先跟使用者確認要處理的是哪個版本的發現。
2. **列清單**：把報告第 2 節（已確認）與第 3 節（待驗證）全部列出來，一項都不漏。
3. **逐項處理**，每項只能是 `fixed`／`disputed`／`deferred`／`needs-info`：
   - `fixed`：改完後做**針對性驗證**（修注入就用惡意輸入實測、修權限就換角色實測、修邏輯就加或跑對應測試）。記命令與輸出摘要。
   - `disputed`：寫出第三方能檢驗的理由（程式碼路徑、為什麼到不了那裡）。「我覺得不會」不算理由。
   - `deferred`：只有使用者拍板才行；critical／high 不得延後。列入 `config.md` 第 6 節。
   - `needs-info`：寫清楚缺什麼。
4. **不順手改無關的東西**。發現要改的範圍超出審查項目，先問使用者要不要另開一次交接。
5. **寫修正報告**：`py -3 .ai-review/kit/kit.py new-id F` 取編號，複製範本到 `.ai-review/fixes/<F-id>.md`，`review` 填 R 編號。
6. **重新交接**：執行 `/review-ready --recheck <R-id>` 的完整流程（snapshot → checks → 新的 H 報告）。把新的 H 編號填回修正報告的 `handoff` 欄。
7. **推導狀態**：`py -3 .ai-review/kit/kit.py state` → 應為「待複查」。
8. **回報使用者**（白話）：處理幾項、修了幾項、不成立幾項（各一句理由）、要他決定幾項（列出來），下一步是再讓 Codex 審一次。固定一句：**目前為待複查，不是通過。**

## 不可以

- 不可以刪除或忽略任何一項發現。
- 不可以把狀態改成「本次範圍內未發現阻擋問題」。
- 不可以用移除既有安全機制的方式「解決」發現。
