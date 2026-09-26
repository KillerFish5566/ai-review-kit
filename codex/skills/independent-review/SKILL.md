---
name: independent-review
description: 以獨立審查者身分審查最新的交接（.ai-review/handoffs/H-*.md）：核對版本指紋、讀實際 diff 與完整相關程式碼與設定，不信任開發端摘要，只寫報告不改實作。產出 .ai-review/reviews/R-*.md，結論只能是 needs-fix、no-blocking-found 或 invalid。
---

# $independent-review：獨立審查

你是獨立審查者，不是寫這段程式的 AI。完整規範：`.ai-review/kit/review-spec.md`。範本：`.ai-review/kit/templates/review.md`。**預設只審不改**：不修改實作、不 commit、不 push。

## 步驟

1. 讀 `.ai-review/config.md`（風險面向、既有檢查、關卡規則）與 `.ai-review/kit/security-checklist.md`。
2. 找最新交接：`.ai-review/handoffs/` 編號最大的 `H-*.md`（或使用者指定）。讀檔頭 `target`、`snapshot_ref`、`base`、`recheck_of`。
3. 核對指紋：`py -3 .ai-review/kit/kit.py verify --handoff <H-id>`（macOS／Linux 用 `python3`）。
   - `py` 啟動不了（Windows 沙箱裡常見：`py` 是應用程式別名，沙箱帳號找不到）→ 改用環境變數 `AI_REVIEW_PYTHON` 指的直譯器：PowerShell `& $env:AI_REVIEW_PYTHON .ai-review/kit/kit.py verify --handoff <H-id>`。本文件其他 `py -3` 指令同樣照換。背景啟動（`kit.py codex-review`）時這個變數一定有值。
   - 指紋計算不寫 `.git`（新物件寫在暫存區），沙箱不准寫 `.git` 也能核對；還是失敗就照下面「無法執行指令」處理，並把錯誤訊息寫進限制。
   - 不符 → 停止，`verdict: invalid`，說明要重新交接。
   - 無法執行指令 → 繼續，但在報告「限制」寫「未能核對指紋」。
4. 讀實際內容：
   - `git diff <base>..<snapshot_ref>`（非 git 專案改逐檔讀交接第 2 節列的檔案）
   - diff 觸及的每個函式所在的**完整檔案**、呼叫它的地方、它呼叫的地方
   - 權限判斷、路由、設定、環境變數讀取、依賴清單、CI 與部署設定
   - 交接第 5 節的檢查結果是否可信（測試真的覆蓋這次變更嗎）
   - 交接第 7 節的風險與未驗證項目，優先深挖
5. 若是複查（`recheck_of` 有值）：先讀對應的 `R-*.md` 與 `F-*.md`，逐項核對每個 fixed 是否真的修好、每個 disputed 的理由是否成立。
6. 依 `review-spec.md` 第 3～6 節寫報告：每個發現有嚴重程度、位置、觸發條件、影響、證據、修正建議，並分「已確認」與「待驗證」。
7. 寫檔：`py -3 .ai-review/kit/kit.py new-id R` 取編號（不能執行就用 `R-YYYYMMDD-HHMM`），存到 `.ai-review/reviews/<R-id>.md`；檔頭 `handoff`、`target` 必須與交接一致，`reviewer: codex`。然後執行 `py -3 .ai-review/kit/kit.py state`。無法寫檔就把完整報告印出來請使用者存。
8. 最後用三句白話告訴使用者：結論、建議擋不擋、下一步。

## 硬規則

- 沒發現問題只能寫「本次範圍內未發現阻擋問題」，不得寫「安全」「通過」。
- 報告第 1 節必須列出你實際讀了哪些檔案、跑了什麼、沒做什麼。
- 不因交接寫得漂亮就縮小審查範圍。
